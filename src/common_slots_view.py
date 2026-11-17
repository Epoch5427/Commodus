import json
from typing import Callable, Dict, List, Optional, Set, Tuple
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .import_dialog import ImportDialog
from .schedule_parser import (
    DAY_NAMES, DAY_SHORT, ImportedSchedule,
    build_room_occupancy_index, compute_common_slots, format_common_slots_text,
    format_duration, format_empty_rooms_text, format_minutes, parse_schedule_file,
)
from .timetable_view import COURSE_COLORS, DAYS, PX_PER_MINUTE

DURATION_OPTIONS_MINUTES = [1, 15, 30, 45, 60, 90, 120, 180]


class ScheduleInspectDialog(Adw.Dialog):
    __gtype_name__ = "CommodusScheduleInspectDialog"

    def __init__(self, sched: ImportedSchedule, on_renamed: Callable[[], None], **kwargs):
        super().__init__(**kwargs)
        self.sched = sched
        self.on_renamed = on_renamed
        self.set_title(sched.name)
        self.set_content_width(480)
        self.set_content_height(520)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        body.set_margin_top(14)
        body.set_margin_bottom(20)
        body.set_margin_start(16)
        body.set_margin_end(16)

        info_group = Adw.PreferencesGroup(title="Schedule Info")
        self.name_row = Adw.EntryRow(title="Name", show_apply_button=True)
        self.name_row.set_text(sched.name)
        self.name_row.connect("apply", self._apply_name)
        self.name_row.connect("changed", self._apply_name)
        info_group.add(self.name_row)
        info_group.add(Adw.ActionRow(title="Source", subtitle=GLib.markup_escape_text(sched.source_type)))
        body.append(info_group)

        by_day: Dict[int, List[Dict]] = {}
        for m in sched.meetings:
            if m.get("day", 0) > 0 and m.get("start", -1) >= 0:
                by_day.setdefault(m["day"], []).append(m)

        if by_day:
            for d in sorted(by_day.keys()):
                day_group = Adw.PreferencesGroup(title=DAY_NAMES[d])
                for m in sorted(by_day[d], key=lambda x: (x["start"], x["end"])):
                    t_range = f"{format_minutes(m['start'])} – {format_minutes(m['end'])}"
                    sec_part = f" ({m['id']})" if m.get("id") else ""
                    type_part = f" {m['type']}" if m.get("type") else ""
                    day_group.add(Adw.ActionRow(
                        title=GLib.markup_escape_text(f"{m['course']}{type_part}{sec_part}"),
                        subtitle=GLib.markup_escape_text(f"{t_range} • {m.get('instructor', 'TBA')}"),
                    ))
                body.append(day_group)
        else:
            empty_group = Adw.PreferencesGroup(title="Meetings")
            empty_group.add(Adw.ActionRow(title="No scheduled time blocks"))
            body.append(empty_group)

        scroll.set_child(body)
        toolbar_view.set_content(scroll)
        self.set_child(toolbar_view)

    def _apply_name(self, entry):
        txt = entry.get_text().strip()
        if txt and txt != self.sched.name:
            self.sched.name = txt
            self.set_title(txt)
            self.on_renamed()


class CommonSlotsView:
    """Manages the Common Free Slots view, backed by GSettings (gschema)."""

    def __init__(
        self,
        parent_window: Adw.ApplicationWindow,
        settings: Gio.Settings,
        widgets: Dict[str, Gtk.Widget],
        toast_fn: Callable[..., None],
        get_current_schedule_fn: Callable[[], Tuple[Optional[Dict], int]],
    ):
        self.parent = parent_window
        self.settings = settings
        self.w = widgets
        self.toast_fn = toast_fn
        self.get_current_schedule_fn = get_current_schedule_fn

        self.schedules: List[ImportedSchedule] = []
        self._saving_schedules = False
        self._room_index: Dict = {}
        self._day_overlays: Dict[int, Gtk.Overlay] = {}
        self._active_cards: Dict[int, List[Gtk.Widget]] = {c: [] for c in range(1, 8)}
        self._grid_start_min = 8 * 60 + 30
        self._grid_hours = 13
        self._last_result: Optional[Dict] = None

        self._rebuild_grid_skeleton(self._grid_start_min, 20 * 60 + 30)
        self._connect_signals()
        self.settings.connect("changed::cs-schedules", self._on_schedules_setting_changed)
        self._load_schedules_from_settings()
        self._update_filter_subtitles()
        self.recompute_and_render()

    def _connect_signals(self):
        self.w["import_pdf_btn"].connect("clicked", self._on_import_files_clicked)
        self.w["paste_btn"].connect("clicked", self._on_paste_schedule_clicked)
        self.w["use_current_btn"].connect("clicked", self._on_use_current_clicked)
        self.w["clear_btn"].connect("clicked", self._on_clear_all_clicked)

        self.w["status_pdf_btn"].connect("clicked", self._on_import_files_clicked)
        self.w["status_paste_btn"].connect("clicked", self._on_paste_schedule_clicked)
        self.w["status_current_btn"].connect("clicked", self._on_use_current_clicked)

        self.w["schedules_listbox"].connect("row-activated", self._on_schedule_row_activated)
        self.w["min_duration_combo"].connect("notify::selected", lambda *_: self.recompute_and_render())
        for btn in self.w["day_checks"].values():
            btn.connect("toggled", self._on_filters_changed)
        for sp in (self.w["start_hours"], self.w["start_minutes"], self.w["end_hours"], self.w["end_minutes"]):
            sp.connect("value-changed", self._on_filters_changed)

        self.w["grid_view_btn"].connect("toggled", self._on_view_mode_toggled)
        self.w["show_busy_btn"].connect("toggled", lambda *_: self.recompute_and_render())
        self.w["copy_btn"].connect("clicked", lambda *_: self.copy_all_free_slots())

    def set_has_current_schedule(self, available: bool):
        self.w["use_current_btn"].set_sensitive(available)
        self.w["status_current_btn"].set_sensitive(available)

    def set_course_data(self, course_data: Dict):
        self._room_index = build_room_occupancy_index(course_data)
        if self.schedules:
            self.recompute_and_render()

    def _load_schedules_from_settings(self):
        try:
            raw = self.settings.get_string("cs-schedules")
            items = json.loads(raw) if raw else []
            self.schedules = [ImportedSchedule.from_dict(d) for d in items if isinstance(d, dict)]
        except Exception:
            self.schedules = []
        self._rebuild_schedules_listbox()

    def _save_schedules_to_settings(self):
        self._saving_schedules = True
        try:
            self.settings.set_string("cs-schedules", json.dumps([s.to_dict() for s in self.schedules]))
        finally:
            self._saving_schedules = False

    def _on_schedules_setting_changed(self, *_args):
        if self._saving_schedules:
            return
        self._load_schedules_from_settings()
        self.recompute_and_render()

    def _ensure_unique_name(self, candidate: str) -> str:
        existing = {s.name for s in self.schedules}
        if candidate not in existing:
            return candidate
        idx = 2
        while f"{candidate} ({idx})" in existing:
            idx += 1
        return f"{candidate} ({idx})"

    def _add_schedule(self, sched: ImportedSchedule):
        sched.name = self._ensure_unique_name(sched.name)
        self.schedules.append(sched)
        self._save_schedules_to_settings()
        self._rebuild_schedules_listbox()
        self.recompute_and_render()

    def _on_import_files_clicked(self, _btn):
        file_dialog = Gtk.FileDialog()
        file_dialog.set_title("Import Schedule Files")

        all_filter = Gtk.FileFilter(name="Schedule Files (PDF, Text)")
        all_filter.add_mime_type("application/pdf")
        all_filter.add_pattern("*.pdf")
        all_filter.add_mime_type("text/plain")
        all_filter.add_pattern("*.txt")

        pdf_filter = Gtk.FileFilter(name="Self-Service PDF Documents")
        pdf_filter.add_mime_type("application/pdf")
        pdf_filter.add_pattern("*.pdf")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(all_filter)
        filters.append(pdf_filter)
        file_dialog.set_filters(filters)
        file_dialog.set_default_filter(all_filter)
        file_dialog.open_multiple(self.parent, None, self._on_files_selected)

    def _on_files_selected(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return

        added = 0
        errors: List[str] = []
        for i in range(files.get_n_items()):
            gfile = files.get_item(i)
            path = gfile.get_path() if gfile else None
            if not path:
                continue
            sched, err = parse_schedule_file(path)
            if sched:
                sched.name = self._ensure_unique_name(sched.name)
                self.schedules.append(sched)
                added += 1
            else:
                errors.append(f"• {gfile.get_basename()}: {err}")

        if added > 0:
            self._save_schedules_to_settings()
            self._rebuild_schedules_listbox()
            self.recompute_and_render()
            self.toast_fn(f"Imported {added} schedule(s)")

        if errors:
            msg_dlg = Adw.MessageDialog(
                transient_for=self.parent,
                heading="Some Files Could Not Be Imported",
                body="\n".join(errors[:5]),
            )
            msg_dlg.add_response("ok", "OK")
            msg_dlg.set_default_response("ok")
            msg_dlg.connect("response", lambda d, _r: d.close())
            msg_dlg.present()

    def _on_paste_schedule_clicked(self, _btn):
        dialog = ImportDialog(
            validate_generator=False,
            show_name=True,
            default_name=f"Schedule {len(self.schedules) + 1}",
            title="Add Schedule",
            action_label="Add",
        )
        dialog.connect("imported", self._on_dialog_schedule_added)
        dialog.present(self.parent)

    def _on_dialog_schedule_added(self, _dialog, sched: ImportedSchedule):
        self._add_schedule(sched)
        self.toast_fn(f"Added {sched.name}")

    def _on_use_current_clicked(self, _btn):
        sched_data, idx = self.get_current_schedule_fn()
        if not sched_data:
            self.toast_fn("No generated schedule available")
            return

        meetings, courses = [], set()
        for m in sched_data.get("meetings", []):
            if m.get("day", 0) > 0 and m.get("start", -1) >= 0 and m.get("end", -1) > m.get("start", -1):
                courses.add(m["course"])
                meetings.append(dict(m))

        if not meetings:
            self.toast_fn("Current schedule has no timed blocks")
            return

        sched = ImportedSchedule(
            name=f"Generated #{idx + 1}",
            source_type="Generator",
            meetings=meetings,
            scheduled_courses=courses,
        )
        self._add_schedule(sched)
        self.toast_fn(f"Added {sched.name}")

    def _on_clear_all_clicked(self, _btn):
        if not self.schedules:
            return
        self.schedules.clear()
        self._save_schedules_to_settings()
        self._rebuild_schedules_listbox()
        self.recompute_and_render()
        self.toast_fn("Cleared all imported schedules")

    def _rebuild_schedules_listbox(self):
        lb = self.w["schedules_listbox"]
        child = lb.get_first_child()
        while child:
            lb.remove(child)
            child = lb.get_first_child()

        for idx, sched in enumerate(self.schedules):
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(sched.name),
                subtitle=GLib.markup_escape_text(
                    f"{sched.total_courses} course(s) • {sched.block_count} block(s) • {sched.source_type}"
                ),
            )
            row.set_title_lines(1)
            row.set_subtitle_lines(1)
            row.set_activatable(True)
            row.sched_ref = sched

            color_hex = COURSE_COLORS[idx % len(COURSE_COLORS)]
            prefix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
            cb = Gtk.CheckButton(active=sched.enabled, valign=Gtk.Align.CENTER)
            cb.set_tooltip_text("Include this schedule in comparison")
            cb.connect("toggled", self._on_sched_enabled_toggled, sched)
            dot = Gtk.Label(use_markup=True)
            dot.set_markup(f"<span foreground='{color_hex}'>●</span>")
            prefix_box.append(cb)
            prefix_box.append(dot)
            row.add_prefix(prefix_box)

            rm_btn = Gtk.Button(
                icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                css_classes=["flat", "destructive-action"],
            )
            rm_btn.set_tooltip_text(f"Remove {sched.name}")
            rm_btn.connect("clicked", self._on_remove_schedule_clicked, sched)
            row.add_suffix(rm_btn)
            lb.append(row)

        has_schedules = len(self.schedules) > 0
        lb.set_visible(has_schedules)
        self.w["clear_btn"].set_sensitive(has_schedules)

    def _on_sched_enabled_toggled(self, cb, sched: ImportedSchedule):
        sched.enabled = cb.get_active()
        self._save_schedules_to_settings()
        self.recompute_and_render()

    def _on_remove_schedule_clicked(self, _btn, sched: ImportedSchedule):
        if sched in self.schedules:
            self.schedules.remove(sched)
            self._save_schedules_to_settings()
            self._rebuild_schedules_listbox()
            self.recompute_and_render()

    def _on_schedule_row_activated(self, _lb, row):
        sched = getattr(row, "sched_ref", None)
        if not sched:
            return
        dialog = ScheduleInspectDialog(
            sched=sched,
            on_renamed=lambda: (
                self._save_schedules_to_settings(),
                self._rebuild_schedules_listbox(),
                self.recompute_and_render(),
            ),
        )
        dialog.present(self.parent)

    def _get_excluded_days(self) -> Set[int]:
        return {day_idx for day_idx, btn in self.w["day_checks"].items() if btn.get_active()}

    def _get_time_window(self) -> Tuple[int, int]:
        st = self.w["start_hours"].get_value_as_int() * 60 + self.w["start_minutes"].get_value_as_int()
        en = self.w["end_hours"].get_value_as_int() * 60 + self.w["end_minutes"].get_value_as_int()
        return st, en

    def _get_min_duration(self) -> int:
        idx = self.w["min_duration_combo"].get_selected()
        return DURATION_OPTIONS_MINUTES[idx] if 0 <= idx < len(DURATION_OPTIONS_MINUTES) else 30

    def _update_filter_subtitles(self):
        excl = sorted(self._get_excluded_days())
        self.w["days_expander"].set_subtitle(", ".join(DAY_SHORT[d] for d in excl) if excl else "None")
        st, en = self._get_time_window()
        self.w["time_expander"].set_subtitle(f"{format_minutes(st)} – {format_minutes(en)}")

    def _on_filters_changed(self, *_args):
        self._update_filter_subtitles()
        self.recompute_and_render()

    def _on_view_mode_toggled(self, _btn):
        if self._last_result and self._last_result["active_schedules"] and not self._last_result["invalid_window"]:
            self.w["content_stack"].set_visible_child_name("grid" if self.w["grid_view_btn"].get_active() else "list")

    def _rebuild_grid_skeleton(self, window_start: int, window_end: int):
        grid = self.w["grid"]
        child = grid.get_first_child()
        while child:
            grid.remove(child)
            child = grid.get_first_child()

        self._day_overlays.clear()
        self._active_cards = {c: [] for c in range(1, 8)}

        start_hour_min = (min(window_start, 8 * 60 + 30) // 60) * 60 + 30
        if start_hour_min > window_start:
            start_hour_min -= 60
        end_hour_min = max(window_end, 20 * 60 + 30)
        span_hours = max(2, ((end_hour_min - start_hour_min + 59) // 60) + 1)

        self._grid_start_min, self._grid_hours = start_hour_min, span_hours
        grid.set_row_spacing(0)
        grid.set_column_spacing(10)
        grid.set_valign(Gtk.Align.START)
        grid.set_hexpand(True)
        grid.set_halign(Gtk.Align.FILL)

        for i in range(span_hours):
            label = Gtk.Label(label=format_minutes(start_hour_min + i * 60))
            label.add_css_class("dim-label")
            label.set_halign(Gtk.Align.END)
            label.set_valign(Gtk.Align.START)
            label.set_margin_end(6)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_valign(Gtk.Align.START)
            box.set_size_request(55, 1 if i == span_hours - 1 else 60)
            box.append(label)
            grid.attach(box, 0, i + 1, 1, 1)

        for col_idx, day in enumerate(DAYS, start=1):
            day_label = Gtk.Label(label=f"<b>{day}</b>", use_markup=True)
            day_label.set_margin_bottom(8)
            day_label.set_halign(Gtk.Align.CENTER)
            grid.attach(day_label, col_idx, 0, 1, 1)

            overlay = Gtk.Overlay()
            dummy = Gtk.Box()
            dummy.set_size_request(120, (span_hours - 1) * 60)
            overlay.set_child(dummy)
            overlay.set_hexpand(True)
            overlay.set_halign(Gtk.Align.FILL)
            overlay.set_valign(Gtk.Align.START)
            grid.attach(overlay, col_idx, 1, 1, span_hours - 1)
            self._day_overlays[col_idx] = overlay

    def _clear_grid_cards(self):
        for col_idx, overlay in self._day_overlays.items():
            for card in self._active_cards[col_idx]:
                overlay.remove_overlay(card)
            self._active_cards[col_idx].clear()

    def _create_slot_card(
        self, start: int, end: int, title_text: str, subtitle_text: str,
        tooltip_text: str, css_class: str, on_click: Optional[Callable] = None,
    ) -> Optional[Gtk.Widget]:
        start_y = int((start - self._grid_start_min) * PX_PER_MINUTE)
        height = int((end - start) * PX_PER_MINUTE) - 1
        if start_y < 0:
            height += start_y
            start_y = 0
        if height <= 4:
            return None

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")
        card.add_css_class(css_class)
        card.set_size_request(-1, height)
        card.set_halign(Gtk.Align.FILL)
        card.set_valign(Gtk.Align.START)
        card.set_margin_top(start_y)
        card.set_tooltip_text(tooltip_text)

        if on_click:
            gesture = Gtk.GestureClick.new()
            gesture.set_button(Gdk.BUTTON_PRIMARY)
            gesture.connect("pressed", lambda g, *_: (on_click(), g.set_state(Gtk.EventSequenceState.CLAIMED)))
            card.add_controller(gesture)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        inner.set_margin_top(4)
        inner.set_margin_bottom(4)
        inner.set_margin_start(6)
        inner.set_margin_end(6)
        card.append(inner)

        title_lbl = Gtk.Label(
            label=f"<b>{GLib.markup_escape_text(title_text)}</b>",
            use_markup=True, halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END,
        )
        title_lbl.add_css_class("caption")
        inner.append(title_lbl)

        if height >= 36 and subtitle_text:
            sub_lbl = Gtk.Label(label=subtitle_text, halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
            sub_lbl.add_css_class("dim-label")
            sub_lbl.add_css_class("caption")
            inner.append(sub_lbl)

        return card

    def recompute_and_render(self):
        excl_days = self._get_excluded_days()
        win_start, win_end = self._get_time_window()
        min_dur = self._get_min_duration()
        result = compute_common_slots(
            schedules=self.schedules, excluded_days=excl_days,
            window_start=win_start, window_end=win_end, min_duration=min_dur,
        )
        self._last_result = result
        active: List[ImportedSchedule] = result["active_schedules"]

        if not self.schedules:
            self.w["summary_label"].set_text("")
            self.w["copy_btn"].set_sensitive(False)
            self.w["status_page"].set_title("Find Common Free Slots")
            self.w["status_page"].set_description(
                "Import two or more schedules from Commodus or Self-Service PDFs to find when everyone is free."
            )
            self.w["content_stack"].set_visible_child_name("empty")
            return

        if not active:
            self.w["summary_label"].set_text("0 active schedules")
            self.w["copy_btn"].set_sensitive(False)
            self.w["status_page"].set_title("No Active Schedules")
            self.w["status_page"].set_description("Check at least one schedule in the sidebar to inspect free slots.")
            self.w["content_stack"].set_visible_child_name("empty")
            return

        if result["invalid_window"]:
            self.w["summary_label"].set_text("Invalid time range")
            self.w["copy_btn"].set_sensitive(False)
            self.w["status_page"].set_title("Invalid Active Hours")
            self.w["status_page"].set_description("Start time must be earlier than end time.")
            self.w["content_stack"].set_visible_child_name("empty")
            return

        slot_count, total_min = result["total_slot_count"], result["total_free_minutes"]
        sched_word = "Schedule" if len(active) == 1 else "Schedules"
        self.w["summary_label"].set_text(
            f"{len(active)} {sched_word} • {slot_count} Free Slot(s) ({format_duration(total_min)})"
        )
        self.w["copy_btn"].set_sensitive(slot_count > 0)

        if win_start < self._grid_start_min or win_end > self._grid_start_min + (self._grid_hours - 1) * 60:
            self._rebuild_grid_skeleton(win_start, win_end)
        else:
            self._clear_grid_cards()

        sched_name_map = {s.id: s.name for s in active}
        total_active = len(active)
        show_busy = self.w["show_busy_btn"].get_active()
        slot_room_cache: Dict[Tuple[int, int, int], Tuple[int, str]] = {}

        def get_room_info(day_num: int, st: int, en: int) -> Tuple[int, str]:
            key = (day_num, st, en)
            if key not in slot_room_cache:
                slot_room_cache[key] = format_empty_rooms_text(self._room_index, day_num, st, en, min_dur)
            return slot_room_cache[key]

        for day in range(1, 8):
            if day in excl_days or day not in self._day_overlays:
                continue

            for slot in result["free_slots_by_day"].get(day, []):
                t_range = f"{format_minutes(slot['start'])} – {format_minutes(slot['end'])}"
                dur_str = format_duration(slot["duration"])
                _, rooms_txt = get_room_info(day, slot["start"], slot["end"])
                rooms_block = f"\n\n{rooms_txt}" if rooms_txt else ""
                tooltip = (
                    f"Free Slot: {DAY_NAMES[day]} {t_range}\n"
                    f"Duration: {dur_str}\n"
                    f"Everyone is free"
                    f"{rooms_block}\n\n"
                    f"Click to copy slot"
                )

                def copy_single(d=day, tr=t_range, dr=dur_str):
                    txt = f"{DAY_NAMES[d]} {tr} ({dr})"
                    self.parent.get_clipboard().set(txt)
                    self.toast_fn(f"Copied: {txt}")

                card = self._create_slot_card(
                    slot["start"], slot["end"], t_range, f"Free • {dur_str}",
                    tooltip, "free-slot-card", on_click=copy_single,
                )
                if card:
                    self._day_overlays[day].add_overlay(card)
                    self._active_cards[day].append(card)

            if show_busy:
                for seg in result["busy_segments_by_day"].get(day, []):
                    t_range = f"{format_minutes(seg['start'])} – {format_minutes(seg['end'])}"
                    busy_names = [sched_name_map[sid] for sid in seg["busy_ids"] if sid in sched_name_map]
                    free_names = [s.name for s in active if s.id not in seg["busy_key"]]
                    title_txt = "All Busy" if len(busy_names) == total_active else f"{len(busy_names)}/{total_active} Busy"

                    tip_lines = [f"Busy: {DAY_NAMES[day]} {t_range}"]
                    for sid in seg["busy_ids"]:
                        courses = sorted({
                            f"{m['course']}" + (f" {m['type']}" if m.get("type") else "")
                            for m in seg["details"].get(sid, [])
                        })
                        tip_lines.append(f"• {sched_name_map.get(sid, sid)}: {', '.join(courses)}")
                    if free_names:
                        tip_lines.append(f"Free: {', '.join(free_names)}")

                    card = self._create_slot_card(
                        seg["start"], seg["end"], title_txt, ", ".join(busy_names),
                        "\n".join(tip_lines), "busy-slot-card",
                    )
                    if card:
                        self._day_overlays[day].add_overlay(card)
                        self._active_cards[day].append(card)

        container = self.w["list_container"]
        child = container.get_first_child()
        while child:
            container.remove(child)
            child = container.get_first_child()

        for day in range(1, 8):
            if day in excl_days:
                continue
            slots = result["free_slots_by_day"].get(day, [])
            group = Adw.PreferencesGroup(title=DAY_NAMES[day])
            if not slots:
                empty_row = Adw.ActionRow(title="No common free slots")
                empty_row.set_sensitive(False)
                group.add(empty_row)
            else:
                for slot in slots:
                    t_range = f"{format_minutes(slot['start'])} – {format_minutes(slot['end'])}"
                    dur_str = format_duration(slot["duration"])
                    room_cnt, rooms_txt = get_room_info(day, slot["start"], slot["end"])
                    room_hint = f" • {room_cnt} empty room(s)" if room_cnt > 0 else ""
                    row = Adw.ActionRow(
                        title=GLib.markup_escape_text(t_range),
                        subtitle=GLib.markup_escape_text(
                            f"{dur_str} free • All {len(active)} schedule(s) available{room_hint}"
                        ),
                    )
                    if rooms_txt:
                        row.set_tooltip_text(rooms_txt)
                    copy_btn = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
                    copy_btn.set_tooltip_text("Copy this slot")

                    def on_copy_row(_b, d=day, tr=t_range, dr=dur_str):
                        txt = f"{DAY_NAMES[d]} {tr} ({dr})"
                        self.parent.get_clipboard().set(txt)
                        self.toast_fn(f"Copied: {txt}")

                    copy_btn.connect("clicked", on_copy_row)
                    row.add_suffix(copy_btn)
                    group.add(row)
            container.append(group)

        self.w["content_stack"].set_visible_child_name("grid" if self.w["grid_view_btn"].get_active() else "list")

    def copy_all_free_slots(self):
        if not self._last_result or not self._last_result["active_schedules"]:
            return
        text = format_common_slots_text(
            schedules=self.schedules,
            free_slots_by_day=self._last_result["free_slots_by_day"],
            excluded_days=self._get_excluded_days(),
        )
        if not text:
            return
        self.parent.get_clipboard().set(text)
        self.toast_fn("Common free slots copied to clipboard")
        btn = self.w["copy_btn"]
        btn.set_icon_name("object-select-symbolic")
        GLib.timeout_add(2000, lambda: btn.set_icon_name("edit-copy-symbolic") or False)
