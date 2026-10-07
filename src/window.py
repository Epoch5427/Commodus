import os
if os.name == "nt":
    import sys
    # 1. Kill the D-Bus timeout instantly (bypasses gdbus.exe search and freeze)
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = "none"

    # 2. Disable accessibility bus timeouts
    os.environ["GTK_A11Y"] = "none"

    # 3. Fonts configuration & cache persistence
    base_dir = (
        sys._MEIPASS
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    os.environ["FONTCONFIG_PATH"] = os.path.join(base_dir, "etc", "fonts")
    os.environ["FONTCONFIG_FILE"] = os.path.join(
        base_dir, "etc", "fonts", "fonts.conf"
    )
    os.environ["XDG_CACHE_HOME"] = os.environ.get(
        "LOCALAPPDATA", os.path.expanduser("~")
    )
from gi.repository import Adw, Gtk, Gio, GLib, Gdk, Pango, GObject
import json
import re
import time

from .import_dialog import ImportDialog
from .branch_dialog import BranchDialog
from .diagnostics import ConstraintConfig, ScheduleDiagnostics
from .scheduler_runner import SchedulerOptions, SchedulerRunner
from .timetable_view import COURSE_COLORS, TimetableView
from .database_service import DatabaseService

@Gtk.Template(resource_path='/io/github/Epoch5427/Commodus/window.ui')
class CommodusWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'CommodusWindow'

    toast_overlay = Gtk.Template.Child()
    split_view = Gtk.Template.Child()
    show_sidebar_btn = Gtk.Template.Child()
    network_banner = Gtk.Template.Child()

    major_combo = Gtk.Template.Child()
    semester_combo = Gtk.Template.Child()
    clear_sec = Gtk.Template.Child()
    update_db_btn = Gtk.Template.Child()
    searchentry = Gtk.Template.Child()
    listbox = Gtk.Template.Child()
    numcourses = Gtk.Template.Child()

    checksun = Gtk.Template.Child()
    checkmon = Gtk.Template.Child()
    checktue = Gtk.Template.Child()
    checkwed = Gtk.Template.Child()
    checkthu = Gtk.Template.Child()
    checkfri = Gtk.Template.Child()
    checksat = Gtk.Template.Child()

    time = Gtk.Template.Child()
    start_hours = Gtk.Template.Child()
    start_minutes = Gtk.Template.Child()
    end_hours = Gtk.Template.Child()
    end_minutes = Gtk.Template.Child()

    gap_time = Gtk.Template.Child()
    gap_day = Gtk.Template.Child()
    gap_start_hours = Gtk.Template.Child()
    gap_start_minutes = Gtk.Template.Child()
    gap_end_hours = Gtk.Template.Child()
    gap_end_minutes = Gtk.Template.Child()

    ls_expander = Gtk.Template.Child()
    ls_listbox = Gtk.Template.Child()
    tuner = Gtk.Template.Child()
    sec_tuner = Gtk.Template.Child()
    generate = Gtk.Template.Child()

    prev_btn = Gtk.Template.Child()
    next_btn = Gtk.Template.Child()
    schedule_counter_label = Gtk.Template.Child()
    fav_btn = Gtk.Template.Child()
    copy_btn = Gtk.Template.Child()
    branch_btn = Gtk.Template.Child()
    import_btn = Gtk.Template.Child()

    stats_btn = Gtk.Template.Child()
    stats_summary_label = Gtk.Template.Child()

    schedule_scroll = Gtk.Template.Child()
    schedule_status = Gtk.Template.Child()
    schedule = Gtk.Template.Child()

    prefs_dialog = Gtk.Template.Child()
    fulltitle_switch = Gtk.Template.Child()
    block_info_combo = Gtk.Template.Child()
    theme_system_btn = Gtk.Template.Child()
    theme_light_btn = Gtk.Template.Child()
    theme_dark_btn = Gtk.Template.Child()
    wrap_switch = Gtk.Template.Child()
    cross_section_switch = Gtk.Template.Child()
    delete_save = Gtk.Template.Child()
    local_load_switch = Gtk.Template.Child()
    fpickerbutton = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.settings = Gio.Settings.new("io.github.Epoch5427.Commodus")

        self.data = {}
        self.curriculum_data = {}
        self.selected_courses = set()
        self.course_preferences = {}
        self._saved_selected_courses = set()
        self.schedules = []  # Stores lightweight tuples: (score: float, raw_data_str: str)
        self.current_schedule_idx = 0
        self.json_path = None
        self._net_hide_timer_id = None
        self.imported_exact_match = None
        self._active_toasts = set()

        self._is_restoring = False
        self._initial_ls_load = True

        self.major_keys = []
        self.semester_keys = []

        self.favorites = set()  # In-memory session favorites
        self._next_long_pressed = False
        self._prev_long_pressed = False

        self.timetable = TimetableView(self.schedule, self._on_right_click_block)

        self.placeholder_label = Gtk.Label(label="Loading Course Catalog...")
        self.placeholder_label.add_css_class("dim-label")

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_hexpand(True)
        placeholder.set_vexpand(True)
        placeholder.append(self.placeholder_label)

        self.listbox.set_placeholder(placeholder)

        # Runner Signals:
        self.scheduler = SchedulerRunner()
        self.scheduler.connect('progress', self._on_scheduler_progress)
        self.scheduler.connect('completed', self._on_scheduler_completed)

        self.major_combo.connect("notify::selected", self._on_major_changed)
        self.semester_combo.connect("notify::selected", self._on_semester_changed)
        self.clear_sec.connect("clicked", self.on_clear_sec_clicked)
        self.update_db_btn.connect("clicked", self.on_update_db_clicked)
        self.searchentry.connect("search-changed", self._on_search_changed)

        self.network_banner.connect("button-clicked", self._on_banner_retry)

        self.generate.connect("clicked", self.on_generate_clicked)
        self.prev_btn.connect("clicked", self._on_previous_clicked)
        self.next_btn.connect("clicked", self._on_next_clicked)
        self.copy_btn.connect("clicked", self.on_copy_schedule_clicked)
        self.branch_btn.connect("clicked", self.on_branch_clicked)
        self.import_btn.connect("clicked", self.on_import_clicked)

        self.wrap_switch.connect("notify::active", lambda *_: self._update_navigation_buttons())
        self.delete_save.connect("activated", self._on_delete_save_clicked)
        self.fpickerbutton.connect("clicked", self.open_json)
        self.local_load_switch.connect("notify::enable-expansion", lambda sw, *_: self.fpickerbutton.set_sensitive(sw.get_enable_expansion()))

        self.ls_checkboxes = {}
        self.ls_expander.connect("notify::enable-expansion", self._on_ls_expander_toggled)

        self.fav_btn.connect("clicked", self.on_toggle_favorite_clicked)

        next_gesture = Gtk.GestureLongPress.new()
        next_gesture.connect("pressed", self._on_next_btn_long_pressed)
        self.next_btn.add_controller(next_gesture)

        prev_gesture = Gtk.GestureLongPress.new()
        prev_gesture.connect("pressed", self._on_prev_btn_long_pressed)
        self.prev_btn.add_controller(prev_gesture)

        # Theme initialization and listeners
        self._sync_theme_from_settings()
        self.settings.connect("changed::theme", lambda *_: self._sync_theme_from_settings())

        self.theme_system_btn.connect("toggled", self._on_theme_toggled, 0)
        self.theme_light_btn.connect("toggled", self._on_theme_toggled, 1)
        self.theme_dark_btn.connect("toggled", self._on_theme_toggled, 2)
        self.block_info_combo.connect("notify::selected", lambda *_: self.draw_schedule_index(self.current_schedule_idx) if self.schedules else None)
        self.fulltitle_switch.connect("notify::active", lambda *_: self.draw_schedule_index(self.current_schedule_idx) if self.schedules else None)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_ctrl)

        self.listbox.set_filter_func(self._filter_courses)
        self.listbox.set_sort_func(self._sort_courses)

        self.connect("close-request", self.on_close_request)

        self._init_course_styles()
        self._init_stats_popover()
        self._init_network_indicator()
        self._setup_settings_bindings()
        self._load_saved_courses_and_preferences()

        # Database & Network Service
        self.db_service = DatabaseService()
        self.db_service.connect('cached-loaded', self._on_cached_database_loaded)
        self.db_service.connect('fetch-started', lambda *_: self._show_net_status_spinning())
        self.db_service.connect('fetch-completed', self._on_fetch_completed)
        self.db_service.connect('fetch-failed', self._on_fetch_failed)
        self.db_service.connect('update-progress', lambda _, msg: self.show_toast(msg))
        self.db_service.connect('update-completed', self._on_update_workflow_completed)
        self.db_service.connect('local-loaded', self._on_local_json_loaded)

        self._network_fetch_completed = False
        self.db_service.load_cached_async()
        self.db_service.fetch_database_async()

        GLib.timeout_add(650, lambda: self.show_sidebar_btn.set_active(True))

    def _on_ls_expander_toggled(self, expander, param):
        if expander.get_enable_expansion():
            for data in self.ls_checkboxes.values():
                data['checkbox'].set_active(True)
            expander.set_expanded(False)
        self._save_courses_and_preferences()

    def _update_ls_listbox(self):
        # Save state of existing checkboxes
        active_states = {course: data['checkbox'].get_active() for course, data in self.ls_checkboxes.items()}

        # Clear listbox
        child = self.ls_listbox.get_first_child()
        while child:
            self.ls_listbox.remove(child)
            child = self.ls_listbox.get_first_child()

        self.ls_checkboxes.clear()

        saved_excluded = set(self.settings.get_strv("exclude-full-courses"))

        # Re-add in sorted order
        for course in sorted(self.selected_courses):
            row = Adw.ActionRow(title=course)
            checkbox = Gtk.CheckButton(valign=Gtk.Align.CENTER)

            # If the course was already there, restore its state
            if course in active_states:
                checkbox.set_active(active_states[course])
            elif getattr(self, "_initial_ls_load", True):
                if course in saved_excluded:
                    checkbox.set_active(True)
                else:
                    checkbox.set_active(False)
            else:
                # If new, it should be active if the expander is enabled
                checkbox.set_active(self.ls_expander.get_enable_expansion())

            checkbox.connect("toggled", lambda *_: self._save_courses_and_preferences())

            row.add_suffix(checkbox)
            row.set_activatable_widget(checkbox)
            self.ls_listbox.append(row)
            self.ls_checkboxes[course] = {'row': row, 'checkbox': checkbox}

        was_initial = getattr(self, "_initial_ls_load", True)
        self._initial_ls_load = False

        if not was_initial:
            self._save_courses_and_preferences()

    # =========================================================================
    # HEADERBAR NETWORK SPINNER & STATUS INDICATOR
    # =========================================================================

    def _find_header_bar(self):
        if hasattr(self, 'show_sidebar_btn') and self.show_sidebar_btn:
            hb = self.show_sidebar_btn.get_ancestor(Adw.HeaderBar)
            if hb:
                return hb
            hb_gtk = self.show_sidebar_btn.get_ancestor(Gtk.HeaderBar)
            if hb_gtk:
                return hb_gtk
        return None

    def _init_network_indicator(self):
        self.net_status_stack = Gtk.Stack()
        self.net_status_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.net_status_stack.set_transition_duration(200)
        self.net_status_stack.set_valign(Gtk.Align.CENTER)
        self.net_status_stack.set_margin_end(6)
        self.net_status_stack.set_visible(False)

        # Use Adw.Spinner directly
        self.net_spinner = Adw.Spinner()
        self.net_spinner.set_size_request(16, 16)
        self.net_status_stack.add_named(self.net_spinner, "spinner")

        self.net_success_icon = Gtk.Image.new_from_icon_name("circle-checkmark-symbolic")
        self.net_success_icon.add_css_class("success")
        self.net_status_stack.add_named(self.net_success_icon, "success")

        self.net_error_icon = Gtk.Image.new_from_icon_name("cross-large-circle-outline-symbolic")
        self.net_error_icon.add_css_class("error")
        self.net_status_stack.add_named(self.net_error_icon, "error")

        header_bar = self._find_header_bar()
        if header_bar:
            header_bar.pack_end(self.net_status_stack)

    def _show_net_status_spinning(self):
        if self._net_hide_timer_id:
            GLib.source_remove(self._net_hide_timer_id)
            self._net_hide_timer_id = None

        self.net_status_stack.set_visible(False)
        self.net_status_stack.set_visible_child_name("spinner")
        self.net_status_stack.set_visible(True)

        self.net_status_stack.set_tooltip_text("Fetching course database...")

    def _show_net_status_success(self):
        self.net_status_stack.set_visible(True)
        self.net_status_stack.set_visible_child_name("success")
        self.net_status_stack.set_tooltip_text("Course database updated")

        if self._net_hide_timer_id:
            GLib.source_remove(self._net_hide_timer_id)
        self._net_hide_timer_id = GLib.timeout_add(2000, self._hide_net_status)

    def _show_net_status_error(self):
        self.net_status_stack.set_visible(True)
        self.net_status_stack.set_visible_child_name("error")
        self.net_status_stack.set_tooltip_text("Database fetch failed")

        if self._net_hide_timer_id:
            GLib.source_remove(self._net_hide_timer_id)
        self._net_hide_timer_id = GLib.timeout_add(2000, self._hide_net_status)

    def _hide_net_status(self):
        self.net_status_stack.set_visible(False)
        self._net_hide_timer_id = None
        return False

    # =========================================================================
    # ON-DEMAND (LAZY) PARSING HELPER (~3 microseconds)
    # =========================================================================
    def _get_schedule_at(self, index):
        """Parses a single schedule on demand from the stored raw text string."""
        if not (0 <= index < len(self.schedules)):
            return None

        item = self.schedules[index]
        if isinstance(item, dict):
            return item

        score, raw_data = item
        try:
            meetings_raw = json.loads(raw_data)
            if isinstance(meetings_raw, list):
                meetings = [
                    {
                        "course": m[0],
                        "type": m[1],
                        "id": m[2],
                        "location": m[3],
                        "instructor": m[4],
                        "day": m[5],
                        "start": m[6],
                        "end": m[7],
                        "seats": m[8]
                    }
                    for m in meetings_raw
                ]
                return {"score": score, "meetings": meetings}
            elif isinstance(meetings_raw, dict):
                return meetings_raw
        except Exception:
            return None

    def _init_course_styles(self):
        css_rules = [
            f".course-color-{i} {{ border-left: 2px solid {color}; }}"
            for i, color in enumerate(COURSE_COLORS)
        ]

        css_rules.append("""
        .theme-button radio {
          -gtk-icon-source: none;
          margin: 1px;
          padding: 6px;
          min-height: 40px;
          min-width: 40px;
          border: solid 1px #c0bfbc;
          border-radius: 100%;
          transition: all 200ms ease-out;
        }

        .theme-button:checked radio {
          margin: 0;
          border-width: 2px;
          border-color: @accent_bg_color;
        }

        .theme-button image {
          margin: 26px 0 0 -26px;
          padding: 2px;
          min-width: 24px;
          min-height: 24px;
          color: @accent_fg_color;
          background-color: @accent_bg_color;
          border-radius: 100%;
          opacity: 0;
          transform: scale(0.75) translate(-1px, -1px);
          transition: all 200ms ease-out;
        }

        .theme-button:checked image {
          opacity: 1;
        }

        .theme-button-system radio {
          background: linear-gradient(135deg, #ffffff 0%, #ffffff 49%, #3d3846 51%, #3d3846 100%);
        }

        .theme-button-light radio {
          background-color: #ffffff;
        }

        .theme-button-dark radio {
          background-color: #3d3846;
        }
        """)

        provider = Gtk.CssProvider()
        provider.load_from_data("\n".join(css_rules).encode('utf-8'))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _setup_settings_bindings(self):
        b = self.settings.bind
        flags = Gio.SettingsBindFlags.DEFAULT

        b("time-enabled", self.time, "enable-expansion", flags)
        b("start-hours", self.start_hours, "value", flags)
        b("start-minutes", self.start_minutes, "value", flags)
        b("end-hours", self.end_hours, "value", flags)
        b("end-minutes", self.end_minutes, "value", flags)

        b("gap-enabled", self.gap_time, "enable-expansion", flags)
        b("gap-day", self.gap_day, "selected", flags)
        b("gap-start-hours", self.gap_start_hours, "value", flags)
        b("gap-start-minutes", self.gap_start_minutes, "value", flags)
        b("gap-end-hours", self.gap_end_hours, "value", flags)
        b("gap-end-minutes", self.gap_end_minutes, "value", flags)

        b("checksun", self.checksun, "active", flags)
        b("checkmon", self.checkmon, "active", flags)
        b("checktue", self.checktue, "active", flags)
        b("checkwed", self.checkwed, "active", flags)
        b("checkthu", self.checkthu, "active", flags)
        b("checkfri", self.checkfri, "active", flags)
        b("checksat", self.checksat, "active", flags)

        b("exclude-full", self.ls_expander, "enable-expansion", flags)
        b("tuner", self.tuner, "selected", flags)
        b("sec-tuner", self.sec_tuner, "selected", flags)

        b("block-info", self.block_info_combo, "selected", flags)

        b("use-fulltitle", self.fulltitle_switch, "active", flags)

        b("wrap-mode", self.wrap_switch, "active", flags)
        b("allow-cross-section", self.cross_section_switch, "active", flags)
        b("local-load", self.local_load_switch, "enable-expansion", flags)

        self.fpickerbutton.set_sensitive(self.local_load_switch.get_enable_expansion())

    def _load_saved_courses_and_preferences(self):
        self._saved_selected_courses = set(self.settings.get_strv("selected-courses"))
        try:
            raw_pref = self.settings.get_string("course-preferences")
            self.course_preferences = json.loads(raw_pref) if raw_pref else {}
        except Exception:
            self.course_preferences = {}

    def _sync_theme_from_settings(self):
        theme_val = self.settings.get_int("theme")

        if theme_val == 1:
            self.theme_light_btn.set_active(True)
        elif theme_val == 2:
            self.theme_dark_btn.set_active(True)
        else:
            self.theme_system_btn.set_active(True)

        self._apply_theme(theme_val)

    def _on_theme_toggled(self, btn, theme_val):
        # Prevent triggering multiple saves when the radio group changes state
        if not btn.get_active():
            return

        if self.settings.get_int("theme") != theme_val:
            self.settings.set_int("theme", theme_val)

        self._apply_theme(theme_val)

    def _apply_theme(self, theme_val):
        style_manager = Adw.StyleManager.get_default()
        if theme_val == 1:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif theme_val == 2:
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.PREFER_LIGHT)

    def _save_courses_and_preferences(self):
        # Prevent premature overwrites of settings during startup bindings
        if getattr(self, '_initial_ls_load', True):
            return

        self.settings.set_strv("selected-courses", list(self.selected_courses))
        self.settings.set_string("course-preferences", json.dumps(self.course_preferences))
        if hasattr(self, 'ls_checkboxes'):
            excluded_full = [course for course, data in self.ls_checkboxes.items() if data['checkbox'].get_active()]
            self.settings.set_strv("exclude-full-courses", excluded_full)

    def _init_stats_popover(self):
        self.stats_popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_size_request(280, -1)

        heading = Gtk.Label(label="<b>Schedule Breakdown</b>", use_markup=True, halign=Gtk.Align.START)
        box.append(heading)

        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")

        def create_stat_row(icon_name, title):
            row = Adw.ActionRow(title=title)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
            listbox.append(row)
            return row

        self.stat_campus_days_row = create_stat_row("month-symbolic", "Campus Days")
        self.stat_days_off_row = create_stat_row("today-symbolic", "Days Off")
        self.stat_class_time_row = create_stat_row("work-week-symbolic", "Weekly Class Time")
        self.stat_break_time_row = create_stat_row("media-playback-pause-symbolic", "Total Break Time")
        self.stat_max_break_row = create_stat_row("box-dotted-symbolic", "Longest Break")
        self.stat_time_window_row = create_stat_row("preferences-system-time-symbolic", "Daily Time Window")

        box.append(listbox)
        self.stats_popover.set_child(box)
        self.stats_btn.set_popover(self.stats_popover)

        popover_key_ctrl = Gtk.EventControllerKey()
        popover_key_ctrl.connect("key-pressed", self._on_popover_key_pressed)
        self.stats_popover.add_controller(popover_key_ctrl)

    def _on_popover_key_pressed(self, controller, keyval, keycode, state):
        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if keyval == Gdk.KEY_Right:
            if is_shift:
                self._on_next_favorite()
                return True
            elif self.next_btn.get_sensitive():
                self._on_next_clicked(None)
                return True
        elif keyval == Gdk.KEY_Left:
            if is_shift:
                self._on_prev_favorite()
                return True
            elif self.prev_btn.get_sensitive():
                self._on_previous_clicked(None)
                return True
        return False

    def _format_duration(self, minutes):
        h, m = divmod(minutes, 60)
        if h > 0 and m > 0: return f"{h}h {m}m"
        elif h > 0: return f"{h}h"
        return f"{m}m"

    def _format_time(self, minutes):
        h, m = divmod(minutes, 60)
        return f"{h:02d}:{m:02d}"

    def _compute_schedule_stats(self, schedule_data):
        meetings = schedule_data.get("meetings", [])
        valid_meetings = [
            m for m in meetings
            if m.get("day", 0) > 0 and m.get("start", -1) >= 0 and m.get("end", -1) > m.get("start", -1)
        ]

        if not valid_meetings:
            return None

        day_names = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
        day_meetings = {}
        for m in valid_meetings:
            d = m["day"]
            day_meetings.setdefault(d, []).append((m["start"], m["end"]))

        active_days = sorted(day_meetings.keys())
        all_days = [1, 2, 3, 4, 5, 6, 7]
        free_days = [d for d in all_days if d not in active_days]

        total_class_minutes = 0
        total_gap_minutes = 0
        max_gap_minutes = 0
        max_gap_day = None

        earliest_overall = 24 * 60
        latest_overall = 0
        TRANSITION_BUFFER = 10

        for d, intervals in day_meetings.items():
            intervals.sort(key=lambda x: (x[0], x[1]))

            merged = []
            for start, end in intervals:
                duration = end - start
                total_class_minutes += duration

                earliest_overall = min(earliest_overall, start)
                latest_overall = max(latest_overall, end)

                if not merged:
                    merged.append([start, end])
                else:
                    if start <= merged[-1][1] + TRANSITION_BUFFER:
                        merged[-1][1] = max(merged[-1][1], end)
                    else:
                        merged.append([start, end])

            for i in range(len(merged) - 1):
                gap = merged[i + 1][0] - merged[i][1]
                if gap > TRANSITION_BUFFER:
                    total_gap_minutes += gap
                    if gap > max_gap_minutes:
                        max_gap_minutes = gap
                        max_gap_day = d

        return {
            "num_days": len(active_days),
            "active_day_names": [day_names[d] for d in active_days],
            "free_day_names": [day_names[d] for d in free_days],
            "total_class_minutes": total_class_minutes,
            "total_gap_minutes": total_gap_minutes,
            "max_gap_minutes": max_gap_minutes,
            "max_gap_day": day_names.get(max_gap_day, ""),
            "earliest_start": earliest_overall if earliest_overall <= latest_overall else 0,
            "latest_end": latest_overall if earliest_overall <= latest_overall else 0,
        }

    def _update_stats_popover(self, stats):
        days_str = ", ".join(stats["active_day_names"]) if stats["active_day_names"] else "None"
        self.stat_campus_days_row.set_subtitle(f"{stats['num_days']} days ({days_str})")

        free_str = ", ".join(stats["free_day_names"]) if stats["free_day_names"] else "None"
        self.stat_days_off_row.set_subtitle(f"{len(stats['free_day_names'])} days ({free_str})")

        self.stat_class_time_row.set_subtitle(self._format_duration(stats["total_class_minutes"]))

        gap_str = self._format_duration(stats["total_gap_minutes"]) if stats["total_gap_minutes"] > 0 else "None (Back-to-back)"
        self.stat_break_time_row.set_subtitle(gap_str)

        if stats["max_gap_minutes"] > 0:
            max_gap_str = f"{self._format_duration(stats['max_gap_minutes'])} ({stats['max_gap_day']})"
        else:
            max_gap_str = "No gaps"
        self.stat_max_break_row.set_subtitle(max_gap_str)

        time_window = f"{self._format_time(stats['earliest_start'])} – {self._format_time(stats['latest_end'])}"
        self.stat_time_window_row.set_subtitle(time_window)

    def dismiss_toasts(self):
        """Dismisses all visible and queued toasts."""
        if hasattr(self.toast_overlay, "dismiss_all"):
            try:
                self.toast_overlay.dismiss_all()
            except Exception:
                pass
        for toast in list(self._active_toasts):
            try:
                toast.dismiss()
            except Exception:
                pass
        self._active_toasts.clear()

    def show_toast(self, text, timeout=1, dismiss_existing=False):
        if dismiss_existing:
            self.dismiss_toasts()
        toast = Adw.Toast.new(text)
        toast.set_timeout(timeout)
        self._active_toasts.add(toast)
        toast.connect("dismissed", lambda t: self._active_toasts.discard(t))
        self.toast_overlay.add_toast(toast)

    def _filter_courses(self, row):
        query = self.searchentry.get_text().strip()
        if not query or query == "*":
            return True
        course_code = getattr(row, 'course_code', '')
        title = getattr(row, 'clean_title', '')
        full_str = f"{course_code} {title}"
        try:
            return bool(re.search(query, full_str, re.IGNORECASE))
        except re.error:
            return query.lower() in full_str.lower()

    def _sort_courses(self, row1, row2):
        c1 = getattr(row1, 'course_code', '')
        c2 = getattr(row2, 'course_code', '')
        s1 = c1 in self.selected_courses
        s2 = c2 in self.selected_courses
        if s1 != s2:
            return -1 if s1 else 1
        return -1 if c1 < c2 else (1 if c1 > c2 else 0)

    def _on_search_changed(self, _entry):
        self.listbox.invalidate_filter()

    def _on_cached_database_loaded(self, _service, db_data, spec_data, local_db_path):
        if not self._network_fetch_completed:
            if db_data:
                self.placeholder_label.set_text("No courses match your search")
                self.data = db_data
                self.json_path = local_db_path
                self.populate_listbox()

            if spec_data:
                self.curriculum_data = spec_data
                self._populate_curriculum_dropdowns()

    def _on_fetch_completed(self, _service, parsed_db, parsed_spec, local_db_path):
        self._network_fetch_completed = True
        had_prior_data = bool(self.data)

        self.placeholder_label.set_text("No courses match your search")
        self.data = parsed_db
        self.json_path = local_db_path
        self.populate_listbox()
        self._show_net_status_success()

        if had_prior_data:
            self.show_toast("Course database updated")

        if parsed_spec:
            self.curriculum_data = parsed_spec
            self._populate_curriculum_dropdowns()

        self.network_banner.set_revealed(False)
        self.update_db_btn.set_sensitive(True)

    def _on_fetch_failed(self, _service, error_message):
        self._show_net_status_error()
        self.update_db_btn.set_sensitive(True)

        if self.data:
            self.network_banner.set_title("Offline: Using cached database.")
            self.network_banner.set_button_label("Retry")
            self.network_banner.set_revealed(True)
            self.show_toast("Loaded cached database")
        else:
            self.network_banner.set_title("Cannot reach database. Check internet connection.")
            self.network_banner.set_button_label("Retry")
            self.network_banner.set_revealed(True)

    def on_update_db_clicked(self, _btn):
        self.update_db_btn.set_sensitive(False)
        self.show_toast("Initializing remote update...", timeout=2)
        self._show_net_status_spinning()
        self.db_service.trigger_remote_update()

    def _on_update_workflow_completed(self, _service, success, message):
        if not success:
            self.show_error_dialog(message)
            self._hide_net_status()
            self.update_db_btn.set_sensitive(True)
        else:
            self.show_toast(message)

    def _on_banner_retry(self, _banner):
        self.network_banner.set_revealed(False)
        self.show_toast("Connecting to database...")
        self.db_service.fetch_database_async()

    def _populate_curriculum_dropdowns(self):
        if not self.curriculum_data or "majors" not in self.curriculum_data:
            return

        self._is_restoring = True
        self.major_keys = ["none"]
        major_names = ["—"]

        for key in self.curriculum_data["majors"].keys():
            self.major_keys.append(key)
            major_names.append(key)

        self.major_combo.set_model(Gtk.StringList.new(major_names))

        saved_major = self.settings.get_string("saved-major")
        if saved_major and saved_major in self.major_keys:
            self.major_combo.set_selected(self.major_keys.index(saved_major))
        else:
            self.semester_combo.set_model(Gtk.StringList.new(["—"]))
            self.semester_combo.set_sensitive(False)

        self._is_restoring = False

    def _on_major_changed(self, combo, pspec):
        idx = combo.get_selected()
        if idx <= 0 or idx >= len(self.major_keys):
            # Guard clearing the major setting behind _is_restoring flag
            if not getattr(self, '_is_restoring', False):
                self.settings.set_string("saved-major", "")
            self.semester_combo.set_model(Gtk.StringList.new(["—"]))
            self.semester_combo.set_sensitive(False)
            return

        major_key = self.major_keys[idx]
        if not getattr(self, '_is_restoring', False):
            self.settings.set_string("saved-major", major_key)

        major_data = self.curriculum_data["majors"][major_key]

        self.semester_keys = ["none"]
        sem_names = ["—"]

        for sem_key, sem_val in major_data.get("curriculum", {}).items():
            self.semester_keys.append(sem_key)
            sem_num = sem_val.get("semester_number", sem_key)
            sem_names.append(str(sem_num))

        self.semester_combo.set_model(Gtk.StringList.new(sem_names))
        self.semester_combo.set_sensitive(True)
        self.semester_combo.set_selected(0)

    def _on_semester_changed(self, combo, pspec):
        major_idx = self.major_combo.get_selected()
        sem_idx = combo.get_selected()

        if major_idx <= 0 or sem_idx <= 0:
            return

        major_key = self.major_keys[major_idx]
        sem_key = self.semester_keys[sem_idx]

        if not getattr(self, '_is_restoring', False):
            self.apply_curriculum_preset(major_key, sem_key)

    def apply_curriculum_preset(self, major_key, semester_key):
        try:
            major_info = self.curriculum_data.get("majors", {}).get(major_key, {})
            semester_info = major_info.get("curriculum", {}).get(semester_key, {})
            preset_courses = semester_info.get("courses", [])

            self.selected_courses.clear()

            if not preset_courses:
                self.populate_listbox()
                self._update_courses_counter()
                self.show_message_dialog(
                    heading="No Courses Listed",
                    body="No courses are defined for this semester preset."
                )
                return

            missing_courses = []
            for course_code in preset_courses:
                if course_code in self.data:
                    self.selected_courses.add(course_code)
                else:
                    missing_courses.append(course_code)

            self.populate_listbox()
            self._update_courses_counter()
            self._save_courses_and_preferences()

            if missing_courses:
                missing_str = "\n".join(f"• {c}" for c in missing_courses)
                self.show_message_dialog(
                    heading="Missing Courses",
                    body=f"Some courses could not be selected because they are not in the database:\n\n{missing_str}"
                )

        except Exception as e:
            print(f"Error applying preset: {e}")

    def on_clear_sec_clicked(self, _btn):
        self.selected_courses.clear()
        self.course_preferences.clear()
        self._save_courses_and_preferences()
        self._update_courses_counter()
        self.populate_listbox()

    def _get_course_credits(self, course_code):
        c_info = self.data.get(course_code, [])
        if not c_info: return 0.0

        def parse_cred(val):
            try:
                # Handle edge cases like "3-4" credits by taking the max
                if isinstance(val, str) and "-" in val:
                    return float(val.split("-")[-1].strip())
                return float(val)
            except (ValueError, TypeError):
                return None

        # Prefer Lecture sections for credit calculation to avoid zero-credit labs
        for section in c_info:
            if section.get("subtype") == "Lecture" or section.get("type") == "Lecture":
                cred_val = section.get("creditHours", section.get("hours", section.get("credits", 0)))
                parsed = parse_cred(cred_val)
                if parsed is not None:
                    return parsed

        # Fallback to the first section with a valid > 0 credit value
        for section in c_info:
            cred_val = section.get("creditHours", section.get("hours", section.get("credits", 0)))
            parsed = parse_cred(cred_val)
            if parsed is not None and parsed > 0:
                return parsed

        return 0.0

    def _get_total_credits(self, selected_set=None):
        if selected_set is None:
            selected_set = self.selected_courses
        return sum(self._get_course_credits(c) for c in selected_set)

    def _update_courses_counter(self):
        total_credits = self._get_total_credits()
        max_credits = 21.0
        target_fraction = min(total_credits / max_credits, 1.0)
        oldnum = self.numcourses.get_fraction()

        # Stop previous animation if one is currently in-flight
        if hasattr(self, '_counter_anim') and self._counter_anim:
            self._counter_anim.skip()

        target = Adw.PropertyAnimationTarget.new(self.numcourses, "fraction")

        self._counter_anim = Adw.TimedAnimation(
            widget=self.numcourses,
            value_from=oldnum,
            value_to=target_fraction,
            duration=500,
            easing=Adw.Easing.EASE,
            target=target,
        )

        if total_credits < 12:
            status = "Underload"
        elif total_credits > 18:
            status = "Overload"
        else:
            status = "Normal"

        cred_str = f"{int(total_credits)}" if total_credits.is_integer() else f"{total_credits}"
        self.numcourses.set_text(f"{cred_str} Credits")
        self.numcourses.set_tooltip_text(f"Total Credits: {cred_str}/21 ({status})")
        self._counter_anim.play()

        self._update_ls_listbox()

    def populate_listbox(self):
        if getattr(self, '_populate_source_id', None):
            GLib.source_remove(self._populate_source_id)
            self._populate_source_id = None

        while True:
            row = self.listbox.get_row_at_index(0)
            if not row:
                break
            self.listbox.remove(row)

        saved_selection = self._saved_selected_courses if hasattr(self, '_saved_selected_courses') and self._saved_selected_courses else set(self.selected_courses)
        self.selected_courses = set(saved_selection)

        self._update_courses_counter()

        selected_keys = sorted([k for k in self.data.keys() if k in saved_selection])
        unselected_keys = sorted([k for k in self.data.keys() if k not in saved_selection])
        ordered_keys = selected_keys + unselected_keys

        key_iter = iter(ordered_keys)

        def chunk_loader():
            start_time = time.time()
            try:
                # Process chunks for up to 12ms per frame to avoid blocking the main UI thread
                while time.time() - start_time < 0.012:
                    course_code = next(key_iter)
                    self._append_course_to_listbox(course_code, saved_selection)
            except StopIteration:
                self._saved_selected_courses = set()
                self._populate_source_id = None
                return False

            return True

        self._populate_source_id = GLib.idle_add(chunk_loader)

    def _append_course_to_listbox(self, course_code, saved_selection):
        display_title = self._get_clean_course_title(course_code)
        escaped_title = GLib.markup_escape_text(display_title)

        row = Adw.ActionRow(title=escaped_title)
        row.course_code = course_code
        row.clean_title = display_title
        row.set_title_lines(2)

        chboxcont = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        row.add_suffix(chboxcont)

        sections_list = self.data[course_code]
        lec_instructors = set()
        lab_instructors = set()
        tut_instructors = set()
        lec_sections = set()
        lab_sections = set()
        tut_sections = set()

        for sec in sections_list:
            inst = sec.get("instructor")
            subtype = sec.get("subtype")
            s_id = sec.get("section")

            if inst and inst != "Not Assigned":
                if subtype == "Lecture": lec_instructors.add(inst)
                elif subtype == "Lab": lab_instructors.add(inst)
                elif subtype == "Tutorial": tut_instructors.add(inst)

            if s_id:
                if subtype == "Lecture": lec_sections.add(s_id)
                elif subtype == "Lab": lab_sections.add(s_id)
                elif subtype == "Tutorial": tut_sections.add(s_id)

        lec_inst_list = sorted(list(lec_instructors))
        lab_inst_list = sorted(list(lab_instructors))
        tut_inst_list = sorted(list(tut_instructors))
        lec_sec_list = sorted(list(lec_sections))
        lab_sec_list = sorted(list(lab_sections))
        tut_sec_list = sorted(list(tut_sections))

        has_instructors = len(lec_inst_list) > 1 or len(lab_inst_list) > 1 or len(tut_inst_list) > 1
        has_sections = len(lec_sec_list) > 1 or len(lab_sec_list) > 1 or len(tut_sec_list) > 1

        menubutton = Gtk.MenuButton()
        menubutton.set_valign(Gtk.Align.CENTER)
        menubutton.add_css_class("flat")
        menubutton.set_tooltip_text("Filter by Section or Instructor")

        saved_pref = self.course_preferences.get(course_code, {"type": "Neither", "value": ""})
        saved_inst_set = set()
        if saved_pref.get("type") == "Instructor":
            val = saved_pref.get("value", [])
            saved_inst_set = set(val) if isinstance(val, list) else ({val} if val else set())

        saved_sec_set = set()
        if saved_pref.get("type") == "Section":
            val = saved_pref.get("value", [])
            saved_sec_set = set(val) if isinstance(val, list) else ({val} if val else set())

        inst_checkbox_map = {}
        sec_checkbox_map = {}

        if not has_instructors and not has_sections:
            menubutton.set_visible(False)
        else:
            popover = Gtk.Popover()
            menubutton.set_popover(popover)

            main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            popover.set_child(main_vbox)

            stack = Gtk.Stack()
            switcher = Gtk.StackSwitcher(stack=stack)
            switcher.set_margin_top(6)
            switcher.set_margin_bottom(6)
            switcher.set_margin_start(12)
            switcher.set_margin_end(12)
            switcher.set_halign(Gtk.Align.CENTER)

            main_vbox.append(switcher)
            main_vbox.append(stack)

            hidden_none_btn = Gtk.CheckButton(visible=False)
            main_vbox.append(hidden_none_btn)

            none_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            none_vbox.set_margin_top(12)
            none_vbox.set_margin_bottom(12)
            none_vbox.set_margin_start(12)
            none_vbox.set_margin_end(12)
            none_desc = Gtk.Label(label="No filters applied.\nAny section or instructor allowed.")
            none_desc.add_css_class("dim-label")
            none_desc.set_justify(Gtk.Justification.CENTER)
            none_vbox.append(none_desc)

            stack.add_titled(none_vbox, "none", "Any")
            stack.get_page(none_vbox).set_icon_name("action-unavailable-symbolic")

            def on_inst_toggled(_btn, c=course_code, mb=menubutton, stk=stack, hnb=hidden_none_btn, icm=inst_checkbox_map):
                checked = [name for name, cb in icm.items() if cb.get_active()]
                if checked:
                    hnb.set_active(True)
                    self.course_preferences[c] = {"type": "Instructor", "value": checked}
                    mb.set_icon_name("funnel-symbolic")
                else:
                    self.course_preferences[c] = {"type": "Neither", "value": ""}
                    if stk.get_visible_child_name() == "instructors":
                        mb.set_icon_name("funnel-outline-symbolic")
                self._save_courses_and_preferences()

            if has_instructors:
                inst_scroll = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=260)
                inst_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                inst_vbox.set_margin_top(6)
                inst_vbox.set_margin_bottom(12)
                inst_vbox.set_margin_start(12)
                inst_vbox.set_margin_end(12)
                inst_scroll.set_child(inst_vbox)

                stack.add_titled(inst_scroll, "instructors", "Instructors")
                stack.get_page(inst_scroll).set_icon_name("avatar-default-symbolic")

                def append_instructor_group(title, inst_list):
                    if len(inst_list) <= 1: return
                    if inst_vbox.get_first_child() is not None:
                        inst_vbox.append(Gtk.Separator(margin_top=4, margin_bottom=4))

                    lbl = Gtk.Label(label=f"<b>{title}</b>", use_markup=True, halign=Gtk.Align.START)
                    lbl.add_css_class("dim-label")
                    inst_vbox.append(lbl)

                    for inst in inst_list:
                        inst_label = Gtk.Label(label=inst, ellipsize=Pango.EllipsizeMode.END, max_width_chars=20, xalign=0)
                        btn = Gtk.CheckButton(child=inst_label)
                        inst_checkbox_map[inst] = btn
                        btn.connect("toggled", on_inst_toggled)
                        inst_vbox.append(btn)
                        if inst in saved_inst_set:
                            btn.set_active(True)

                append_instructor_group("Lecture Instructors", lec_inst_list)
                append_instructor_group("Lab Instructors", lab_inst_list)
                append_instructor_group("Tutorial Instructors", tut_inst_list)

            if has_sections:
                sec_scroll = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=260)
                sec_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                sec_vbox.set_margin_top(6)
                sec_vbox.set_margin_bottom(12)
                sec_vbox.set_margin_start(12)
                sec_vbox.set_margin_end(12)
                sec_scroll.set_child(sec_vbox)

                stack.add_titled(sec_scroll, "sections", "Sections")
                stack.get_page(sec_scroll).set_icon_name("view-list-symbolic")

                def on_sec_toggled(btn, s_val, s_type, c=course_code, mb=menubutton, stk=stack, hnb=hidden_none_btn, scm=sec_checkbox_map, lsl=lec_sec_list):
                    # Extract the prefixes currently active per category
                    lec_p = {re.match(r'^\d+', sv).group(0).lstrip("0") or "0" for (st, sv), cb in scm.items() if st == "Lecture" and cb.get_active()}
                    lab_p = {re.match(r'^\d+', sv).group(0).lstrip("0") or "0" for (st, sv), cb in scm.items() if st == "Lab" and cb.get_active()}
                    tut_p = {re.match(r'^\d+', sv).group(0).lstrip("0") or "0" for (st, sv), cb in scm.items() if st == "Tutorial" and cb.get_active()}

                    # Apply strict cross-category restrictions
                    for (st, sv), cb in scm.items():
                        prefix = re.match(r'^\d+', sv).group(0).lstrip("0") or "0"
                        is_valid = True

                        if st == "Lecture":
                            if lab_p and prefix not in lab_p: is_valid = False
                            if tut_p and prefix not in tut_p: is_valid = False
                        elif st == "Lab":
                            if lec_p and prefix not in lec_p: is_valid = False
                            if tut_p and prefix not in tut_p: is_valid = False
                        elif st == "Tutorial":
                            if lec_p and prefix not in lec_p: is_valid = False
                            if lab_p and prefix not in lab_p: is_valid = False

                        # A checked box always overrides and remains sensitive so it can be manually unchecked to escape states
                        if cb.get_active():
                            is_valid = True

                        cb.set_sensitive(is_valid)

                    checked = list({f"{sec_type}:{sec_val}" for (sec_type, sec_val), cb in scm.items() if cb.get_active()})
                    if checked:
                        hnb.set_active(True)
                        self.course_preferences[c] = {"type": "Section", "value": checked}
                        mb.set_icon_name("funnel-symbolic")
                    else:
                        self.course_preferences[c] = {"type": "Neither", "value": ""}
                        if stk.get_visible_child_name() == "sections":
                            mb.set_icon_name("funnel-outline-symbolic")
                    self._save_courses_and_preferences()

                def append_section_group(title, sec_list_group, subtype):
                    if len(sec_list_group) <= 1: return

                    if sec_vbox.get_first_child() is not None:
                        sec_vbox.append(Gtk.Separator(margin_top=4, margin_bottom=4))

                    lbl = Gtk.Label(label=f"<b>{title}</b>", use_markup=True, halign=Gtk.Align.START)
                    lbl.add_css_class("dim-label")
                    sec_vbox.append(lbl)

                    for sec in sec_list_group:
                        sec_label = Gtk.Label(label=sec, ellipsize=Pango.EllipsizeMode.END, max_width_chars=20, xalign=0)
                        btn = Gtk.CheckButton(child=sec_label)
                        sec_checkbox_map[(subtype, sec)] = btn

                        # Set active state BEFORE connecting the toggled signal to prevent partial overwrites
                        if f"{subtype}:{sec}" in saved_sec_set or sec in saved_sec_set:
                            btn.set_active(True)

                        btn.connect("toggled", on_sec_toggled, sec, subtype)
                        sec_vbox.append(btn)

                append_section_group("Lecture Sections", lec_sec_list, "Lecture")
                append_section_group("Lab Sections", lab_sec_list, "Lab")
                append_section_group("Tutorial Sections", tut_sec_list, "Tutorial")


            if saved_pref.get("type") == "Neither":
                hidden_none_btn.set_active(True)
                menubutton.set_icon_name("funnel-outline-symbolic")
                stack.set_visible_child_name("none")
            elif saved_pref.get("type") == "Instructor":
                menubutton.set_icon_name("funnel-symbolic")
                stack.set_visible_child_name("instructors")
            elif saved_pref.get("type") == "Section":
                menubutton.set_icon_name("funnel-symbolic")
                stack.set_visible_child_name("sections")

            def on_stack_page_changed(stk, _param, c=course_code, mb=menubutton, hnb=hidden_none_btn, icm=inst_checkbox_map, scm=sec_checkbox_map):
                page = stk.get_visible_child_name()
                if page == "none":
                    hnb.set_active(True)
                    for cb in icm.values():
                        cb.set_active(False)
                    for cb in scm.values():
                        cb.set_active(False)
                    self.course_preferences[c] = {"type": "Neither", "value": ""}
                    mb.set_icon_name("funnel-outline-symbolic")
                    self._save_courses_and_preferences()
                elif page == "instructors":
                    hnb.set_active(True)
                    for cb in scm.values():
                        cb.set_active(False)
                    checked = [name for name, cb in icm.items() if cb.get_active()]
                    if checked:
                        self.course_preferences[c] = {"type": "Instructor", "value": checked}
                        mb.set_icon_name("funnel-symbolic")
                    else:
                        self.course_preferences[c] = {"type": "Neither", "value": ""}
                        mb.set_icon_name("funnel-outline-symbolic")
                    self._save_courses_and_preferences()
                elif page == "sections":
                    for cb in icm.values():
                        cb.set_active(False)
                    checked = list({f"{sec_type}:{sec_val}" for (sec_type, sec_val), cb in scm.items() if cb.get_active()})
                    if checked:
                        self.course_preferences[c] = {"type": "Section", "value": checked}
                        mb.set_icon_name("funnel-symbolic")
                    else:
                        self.course_preferences[c] = {"type": "Neither", "value": ""}
                        mb.set_icon_name("funnel-outline-symbolic")
                    self._save_courses_and_preferences()

            stack.connect("notify::visible-child-name", on_stack_page_changed)

        chboxcont.append(menubutton)

        checkbox = Gtk.CheckButton(focusable=False)
        checkbox.connect("toggled", self.on_course_toggled, course_code)
        if course_code in saved_selection:
            checkbox.set_active(True)
        chboxcont.append(checkbox)

        row.set_activatable_widget(checkbox)
        self.listbox.append(row)

    def on_course_toggled(self, checkbox, course_code):
        if checkbox.get_active():
            tentative_credits = self._get_total_credits() + self._get_course_credits(course_code)
            if tentative_credits <= 21:
                self.selected_courses.add(course_code)
            else:
                checkbox.set_active(False)
                self.show_toast("Maximum credit load (21) reached")
        else:
            self.selected_courses.discard(course_code)

        self._save_courses_and_preferences()
        self.listbox.invalidate_sort()
        self._update_courses_counter()

    def on_generate_clicked(self, _button):
        if self.scheduler.is_running:
            self.scheduler.cancel()
            self.generate.set_sensitive(False)
            self.schedule_status.set_description("Stopping and sorting schedules...")
            return

        if not self.json_path or not self.selected_courses:
            self.show_error_dialog("Please select at least one course to generate schedules.")
            return

        # Format preferences
        pref_insts = []
        pref_secs = []
        for c in self.selected_courses:
            pref = self.course_preferences.get(c)
            if not pref:
                continue
            val = pref.get("value")
            if pref.get("type") == "Instructor" and val:
                inst_list = val if isinstance(val, list) else [val]
                pref_insts.extend([f"{c}:{inst}" for inst in inst_list if inst])
            elif pref.get("type") == "Section" and val:
                sec_list = val if isinstance(val, list) else [val]
                for sec in sec_list:
                    if not sec:
                        continue
                    if ":" in sec:
                        pref_secs.append(f"{c}:{sec}")
                    else:
                        pref_secs.extend([f"{c}:Lecture:{sec}", f"{c}:Lab:{sec}", f"{c}:Tutorial:{sec}"])

        options = self._build_scheduler_options(
            courses=list(self.selected_courses),
            preferred_instructors=pref_insts,
            specific_sections=pref_secs,
        )
        self._start_scheduler(options)

    # =========================================================================
    # ADAPTIVE STREAMING & BACKGROUND INGESTION ENGINE
    # =========================================================================

    def _build_scheduler_options(
        self,
        courses: list[str],
        preferred_instructors: list[str] = None,
        specific_sections: list[str] = None,
        custom_exclude_full: list[str] = None,
    ) -> SchedulerOptions:
        excluded_days = []
        if self.checksun.get_active(): excluded_days.append(1)
        if self.checkmon.get_active(): excluded_days.append(2)
        if self.checktue.get_active(): excluded_days.append(3)
        if self.checkwed.get_active(): excluded_days.append(4)
        if self.checkthu.get_active(): excluded_days.append(5)
        if self.checkfri.get_active(): excluded_days.append(6)
        if self.checksat.get_active(): excluded_days.append(7)

        start_time, end_time = None, None
        if self.time.get_enable_expansion():
            start_time = f"{self.start_hours.get_value_as_int():02d}:{self.start_minutes.get_value_as_int():02d}"
            end_time = f"{self.end_hours.get_value_as_int():02d}:{self.end_minutes.get_value_as_int():02d}"

        gap_start, gap_end, gap_day = None, None, None
        if self.gap_time.get_enable_expansion():
            gap_start = f"{self.gap_start_hours.get_value_as_int():02d}:{self.gap_start_minutes.get_value_as_int():02d}"
            gap_end = f"{self.gap_end_hours.get_value_as_int():02d}:{self.gap_end_minutes.get_value_as_int():02d}"
            gap_day = self.gap_day.get_selected()

        exclude_full = []
        if custom_exclude_full is not None:
            exclude_full = custom_exclude_full
        elif self.ls_expander.get_enable_expansion():
            exclude_full = [c for c, d in self.ls_checkboxes.items() if d['checkbox'].get_active()]

        opt_metric_map = {0: "compact", 1: "few-days", 2: "balanced-days", 3: "consistent-times"}
        sec_metric_map = {0: "none", 1: "compact", 2: "few-days", 3: "balanced-days", 4: "consistent-times"}

        return SchedulerOptions(
            json_file=self.json_path,
            courses=courses,
            preferred_instructors=preferred_instructors or [],
            specific_sections=specific_sections or [],
            excluded_days=excluded_days,
            start_time=start_time,
            end_time=end_time,
            gap_start=gap_start,
            gap_end=gap_end,
            gap_day=gap_day,
            exclude_full_courses=exclude_full,
            optimize_by=opt_metric_map.get(self.tuner.get_selected(), "compact"),
            secondary_optimize_by=sec_metric_map.get(self.sec_tuner.get_selected(), "none")
        )

    def _start_scheduler(self, options: SchedulerOptions):
        binary_path = self.scheduler.find_binary()
        if not binary_path:
            self.show_error_dialog("Error: Could not find 'scheduler' executable.")
            return

        cmd = self.scheduler.build_command(binary_path, options)

        self.schedules = []
        self.current_schedule_idx = 0
        self.favorites.clear()
        self.fav_btn.set_sensitive(False)
        self.fav_btn.set_icon_name("non-starred-2-symbolic")

        self.timetable.clear()
        self.schedule.set_visible(False)
        self.schedule_status.set_visible(True)
        self.schedule_status.set_title("Generating Schedules...")
        self.schedule_status.set_description("Searching conflict-free combinations...")
        self.schedule_status.set_icon_name("content-loading-symbolic")
        self.schedule_counter_label.set_text("Generating...")
        self.stats_btn.set_sensitive(False)
        self.stats_summary_label.set_text("")

        self.generate.set_label("Cancel")
        self.generate.remove_css_class("suggested-action")
        self.generate.add_css_class("destructive-action")
        self.generate.set_sensitive(True)

        self.scheduler.start(cmd)

    def _on_scheduler_progress(self, _runner, count: int, is_live_sorting: bool, top_changed: bool):
        if not self.scheduler.is_running:
            return

        # Keep window schedules pointing to streaming schedules
        self.schedules = self.scheduler.schedules

        if top_changed and self.current_schedule_idx == 0:
            self.draw_schedule_index(0)
        elif not self.schedule.get_visible() and count > 0:
            self.draw_schedule_index(0)

        gen_status = "" if is_live_sorting else "(Sorting Paused)"
        if self.schedule.get_visible():
            self.schedule_counter_label.set_text(
                f"Schedule {self.current_schedule_idx + 1} of {count:,} {gen_status}"
            )
        else:
            self.schedule_counter_label.set_text(f"Found {count:,} schedules...")

        self._update_navigation_buttons()

    def _on_scheduler_completed(self, _runner, ret_code: int, stderr: str, all_schedules: list, is_cancelled: bool):
        self.generate.set_label("Generate Schedules")
        self.generate.remove_css_class("destructive-action")
        self.generate.add_css_class("suggested-action")
        self.generate.set_sensitive(True)

        if ret_code != 0 and not is_cancelled:
            self.schedules = all_schedules
            self.show_error_dialog(f"Error running scheduler: {stderr}")
            self.schedule_status.set_title("Generation Failed")
            self.schedule_status.set_description("An error occurred during calculation.")
            self.schedule_status.set_icon_name("dialog-error-symbolic")
            self.schedule_counter_label.set_text("Failed")
            return

        # Reorder imported exact match to index 0 if applicable
        if all_schedules and getattr(self, 'imported_exact_match', None):
            exact_match_idx = -1
            for idx, (score, raw_data) in enumerate(all_schedules):
                try:
                    meetings = json.loads(raw_data)
                    current_pairs = {f"{m[0]}:{m[2]}" for m in meetings}
                    if self.imported_exact_match.issubset(current_pairs):
                        exact_match_idx = idx
                        break
                except Exception:
                    continue

            if exact_match_idx != -1:
                exact_item = all_schedules.pop(exact_match_idx)
                all_schedules.insert(0, exact_item)

            self.imported_exact_match = None

        self.schedules = all_schedules

        if not self.schedules:
            self.draw_schedule_index(0)
        else:
            if self.current_schedule_idx >= len(self.schedules):
                self.current_schedule_idx = 0
            self.draw_schedule_index(self.current_schedule_idx)
            self.show_toast(f"Found {len(self.schedules):,} conflict-free schedule(s)")

    def draw_schedule_index(self, index):
        # 1. Update Favorite Button
        if index in self.favorites:
            self.fav_btn.set_icon_name("starred-symbolic")
            self.fav_btn.set_tooltip_text("Unfavorite Schedule")
        else:
            self.fav_btn.set_icon_name("non-starred-2-symbolic")
            self.fav_btn.set_tooltip_text("Favorite Schedule")

        schedule_data = self._get_schedule_at(index)

        # 2. Handle Empty / No Results
        if not schedule_data or not self.schedules or index >= len(self.schedules):
            self.timetable.clear()
            self.schedule.set_visible(False)
            self.schedule_status.set_visible(True)
            self.schedule_status.set_icon_name("system-search-symbolic")
            self.schedule_counter_label.set_text("No Results")
            self.stats_btn.set_sensitive(False)
            self.stats_summary_label.set_text("")
            self._update_navigation_buttons()

            diagnostics = ScheduleDiagnostics(
                course_data=self.data,
                selected_courses=self.selected_courses,
                course_preferences=self.course_preferences,
                constraints=self._collect_constraint_config()
            )
            issues, suggestions = diagnostics.diagnose()

            self.schedule_status.set_title("No Schedules Found")
            desc_lines = ["<b>Constraint Bottlenecks Detected:</b>"]
            for issue in issues[:3]:
                desc_lines.append(f"• {issue}")

            if suggestions:
                desc_lines.append("\n<b>Suggestions:</b>")
                for sugg in suggestions[:2]:
                    desc_lines.append(f"→ {sugg}")

            self.schedule_status.set_description("\n".join(desc_lines))
            return

        # 3. Update Schedule Grid & Visibility
        self.schedule_status.set_visible(False)
        self.schedule.set_visible(True)
        gen_suffix = " (generating...)" if self.scheduler.is_running else ""
        self.schedule_counter_label.set_text(f"Schedule {index + 1} of {len(self.schedules):,}{gen_suffix}")

        # 4. Update Stats Popover
        stats = self._compute_schedule_stats(schedule_data)
        if stats:
            self.stats_btn.set_sensitive(True)
            self.stats_summary_label.set_text(f"{stats['num_days']} Days | {self._format_duration(stats['total_gap_minutes'])}")
            self._update_stats_popover(stats)
        else:
            self.stats_btn.set_sensitive(False)
            self.stats_summary_label.set_text("")

        # 5. Render Meeting Cards via Decoupled Timetable Component
        self.timetable.render(
            meetings=schedule_data.get("meetings", []),
            course_data=self.data,
            block_info_choice=self.block_info_combo.get_selected(),
            use_full_title=self.fulltitle_switch.get_active()
        )

        self._update_navigation_buttons()

    # =========================================================================
    # CONFLICT & CONSTRAINT DIAGNOSTICS
    # =========================================================================

    def _collect_constraint_config(self) -> ConstraintConfig:
        excluded_days = set()
        if self.checksun.get_active(): excluded_days.add(1)
        if self.checkmon.get_active(): excluded_days.add(2)
        if self.checktue.get_active(): excluded_days.add(3)
        if self.checkwed.get_active(): excluded_days.add(4)
        if self.checkthu.get_active(): excluded_days.add(5)
        if self.checkfri.get_active(): excluded_days.add(6)
        if self.checksat.get_active(): excluded_days.add(7)

        time_boundary = None
        if self.time.get_enable_expansion():
            start_m = self.start_hours.get_value_as_int() * 60 + self.start_minutes.get_value_as_int()
            end_m = self.end_hours.get_value_as_int() * 60 + self.end_minutes.get_value_as_int()
            time_boundary = (start_m, end_m)

        gap_window = None
        if self.gap_time.get_enable_expansion():
            g_start = self.gap_start_hours.get_value_as_int() * 60 + self.gap_start_minutes.get_value_as_int()
            g_end = self.gap_end_hours.get_value_as_int() * 60 + self.gap_end_minutes.get_value_as_int()
            gap_window = (g_start, g_end, self.gap_day.get_selected())

        exclude_full_courses = set()
        if self.ls_expander.get_enable_expansion():
            for c, data in self.ls_checkboxes.items():
                if data['checkbox'].get_active():
                    exclude_full_courses.add(c)

        return ConstraintConfig(
            excluded_days=excluded_days,
            time_boundary=time_boundary,
            gap_window=gap_window,
            exclude_full_courses=exclude_full_courses,
        )

    def _update_navigation_buttons(self):
        total = len(self.schedules)
        has_schedules = total > 0

        self.fav_btn.set_sensitive(has_schedules)
        self.copy_btn.set_sensitive(has_schedules)
        self.branch_btn.set_sensitive(has_schedules)
        self.stats_btn.set_sensitive(has_schedules)

        self.next_btn.set_tooltip_text("Next Schedule (Right Arrow)\nHold for Next Favorite (Shift+Right)")
        self.prev_btn.set_tooltip_text("Previous Schedule (Left Arrow)\nHold for Prev Favorite (Shift+Left)")

        if not has_schedules:
            self.stats_summary_label.set_text("")

        if total <= 1:
            self.prev_btn.set_sensitive(False)
            self.next_btn.set_sensitive(False)
            return

        if self.wrap_switch.get_active():
            self.prev_btn.set_sensitive(True)
            self.next_btn.set_sensitive(True)
        else:
            self.prev_btn.set_sensitive(self.current_schedule_idx > 0)
            self.next_btn.set_sensitive(self.current_schedule_idx < total - 1)

    def on_toggle_favorite_clicked(self, _btn):
        if not self.schedules or self.current_schedule_idx >= len(self.schedules):
            return

        if self.current_schedule_idx in self.favorites:
            self.favorites.remove(self.current_schedule_idx)
            self.fav_btn.set_icon_name("non-starred-2-symbolic")
            self.fav_btn.set_tooltip_text("Favorite Schedule")
            self.show_toast("Removed from favorites")
        else:
            self.favorites.add(self.current_schedule_idx)
            self.fav_btn.set_icon_name("starred-symbolic")
            self.fav_btn.set_tooltip_text("Unfavorite Schedule")
            self.show_toast(f"Schedule {self.current_schedule_idx + 1} added to favorites")

    def _on_next_btn_long_pressed(self, gesture, x, y):
        self._next_long_pressed = True
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._on_next_favorite()

    def _on_prev_btn_long_pressed(self, gesture, x, y):
        self._prev_long_pressed = True
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._on_prev_favorite()

    def _on_next_favorite(self):
        self.dismiss_toasts()
        if not self.favorites:
            self.show_toast("No favorite schedules saved")
            return

        fav_list = sorted(self.favorites)
        next_favs = [idx for idx in fav_list if idx > self.current_schedule_idx]

        if next_favs:
            target_idx = next_favs[0]
        elif self.wrap_switch.get_active() or len(fav_list) > 0:
            target_idx = fav_list[0]
        else:
            return

        if target_idx != self.current_schedule_idx:
            self.current_schedule_idx = target_idx
            self.draw_schedule_index(self.current_schedule_idx)
            self.show_toast(f"Favorite {fav_list.index(target_idx) + 1} of {len(fav_list)}")
        elif len(fav_list) == 1:
            self.show_toast("Only 1 favorite schedule saved")

    def _on_prev_favorite(self):
        self.dismiss_toasts()
        if not self.favorites:
            self.show_toast("No favorite schedules saved")
            return

        fav_list = sorted(self.favorites)
        prev_favs = [idx for idx in fav_list if idx < self.current_schedule_idx]

        if prev_favs:
            target_idx = prev_favs[-1]
        elif self.wrap_switch.get_active() or len(fav_list) > 0:
            target_idx = fav_list[-1]
        else:
            return

        if target_idx != self.current_schedule_idx:
            self.current_schedule_idx = target_idx
            self.draw_schedule_index(self.current_schedule_idx)
            self.show_toast(f"Favorite {fav_list.index(target_idx) + 1} of {len(fav_list)}")
        elif len(fav_list) == 1:
            self.show_toast("Only 1 favorite schedule saved")

    def _on_previous_clicked(self, _button):
        if self._prev_long_pressed:
            self._prev_long_pressed = False
            return

        if self.schedules and self.current_schedule_idx > 0:
            self.current_schedule_idx -= 1
            self.draw_schedule_index(self.current_schedule_idx)
        elif self.wrap_switch.get_active() and self.current_schedule_idx == 0:
            self.current_schedule_idx = len(self.schedules) - 1
            self.draw_schedule_index(self.current_schedule_idx)

    def _on_next_clicked(self, _button):
        if self._next_long_pressed:
            self._next_long_pressed = False
            return

        if self.schedules and self.current_schedule_idx < len(self.schedules) - 1:
            self.current_schedule_idx += 1
            self.draw_schedule_index(self.current_schedule_idx)
        elif self.wrap_switch.get_active() and self.current_schedule_idx == len(self.schedules) - 1:
            self.current_schedule_idx = 0
            self.draw_schedule_index(self.current_schedule_idx)

    def on_copy_schedule_clicked(self, _btn):
        sched = self._get_schedule_at(self.current_schedule_idx)
        if not sched:
            return

        days_map = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
        lines = []

        meetings = sorted(sched.get("meetings", []), key=lambda m: (m['course'], m['type'], m['id']))
        for m in meetings:
            if m['day'] == 0 or m['start'] < 0 or m['end'] < 0: continue
            course = m['course'].ljust(8)
            mtype = m['type'].ljust(11)
            mid = m['id'].ljust(6)
            day = days_map.get(m['day'], "TBD").ljust(6)
            start_h, start_m = divmod(m['start'], 60)
            end_h, end_m = divmod(m['end'], 60)
            time_str = f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}".ljust(13)
            lines.append(f"{course}{mtype}{mid}{day}{time_str}| {m['instructor']}")

        text = "\n".join(lines)
        self.get_clipboard().set(text)
        self.show_toast("Schedule copied to clipboard")
        _btn.set_icon_name("object-select-symbolic")
        GLib.timeout_add(2000, lambda: _btn.set_icon_name("edit-copy-symbolic") or False)

    # =========================================================================
    # BRANCH FROM SCHEDULE
    # =========================================================================

    def _get_clean_course_title(self, course_code):
        sections_list = self.data.get(course_code, [])
        full_title = sections_list[0].get("fullTitle", "") if sections_list else ""

        full_title = re.sub(r'\s+', ' ', full_title).strip()

        clean_title = ""
        if full_title:
            prefix_pattern = re.compile(rf"^{re.escape(course_code)}\s*[:-]?\s*", re.IGNORECASE)
            clean_title = prefix_pattern.sub("", full_title).strip()

        display_title = f"{course_code}: {clean_title}" if clean_title and clean_title.lower() != course_code.lower() else course_code
        return display_title.strip()

    def on_branch_clicked(self, _button):
        current_sched = self._get_schedule_at(self.current_schedule_idx)
        if not current_sched:
            return

        dialog = BranchDialog(
            current_sched=current_sched,
            course_data=self.data,
            clean_title_fn=self._get_clean_course_title,
            colors=COURSE_COLORS,
            toast_fn=self.show_toast
        )
        dialog.connect("reschedule-requested", lambda d, active_courses: self._execute_branch_generation(active_courses))
        dialog.present(self)

    @staticmethod
    def _parse_db_day(val):
        if not val:
            return 0
        s = str(val).strip().lower()
        day_map = {
            "sun": 1, "sunday": 1,
            "mon": 2, "monday": 2,
            "tue": 3, "tues": 3, "tuesday": 3,
            "wed": 4, "wednesday": 4,
            "thu": 5, "thur": 5, "thursday": 5,
            "fri": 6, "friday": 6,
            "sat": 7, "saturday": 7,
        }
        return day_map.get(s, 0)

    @classmethod
    def _parse_time_str(cls, val):
        if not val:
            return -1
        s = str(val).strip()
        match = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', s, re.IGNORECASE)
        if not match:
            return -1
        h, m = int(match.group(1)), int(match.group(2))
        ampm = match.group(3)
        if ampm:
            ampm = ampm.lower()
            if ampm == 'pm' and h < 12:
                h += 12
            elif ampm == 'am' and h == 12:
                h = 0
        return h * 60 + m

    @classmethod
    def _parse_time_range(cls, val):
        if not val or "n/a" in str(val).lower():
            return -1, -1
        s = str(val).strip()
        matches = list(re.finditer(r'(\d{1,2}:\d{2}\s*(?:am|pm)?)', s, re.IGNORECASE))
        if len(matches) >= 2:
            st = cls._parse_time_str(matches[0].group(1))
            en = cls._parse_time_str(matches[1].group(1))
            # Round off :29 / :59 boundary markers to full 30-minute slots
            if en % 60 in (29, 59):
                en += 1
            return st, en
        return -1, -1

    def _parse_schedule_string(self, sched_str, parent_item, course, mtype, sec_id):
        if not sched_str or "n/a" in sched_str.lower():
            return []

        results = []
        day_regex = re.compile(r'\b(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sun|Mon|Tue|Wed|Thu|Fri|Sat)\b', re.IGNORECASE)

        # In case multiple schedule intervals are joined by newline or semicolon
        for part in re.split(r'[\n;/]+', sched_str):
            part = part.strip()
            if not part:
                continue

            day_match = day_regex.search(part)
            if not day_match:
                continue

            day_num = self._parse_db_day(day_match.group(1))
            if day_num == 0:
                continue

            st, en = self._parse_time_range(part)
            if st < 0 or en < 0:
                continue

            loc = parent_item.get("location", "TBA")
            if loc == "Not specified":
                loc = "TBA"

            inst = parent_item.get("instructor", "Not Assigned")
            seats_raw = parent_item.get("seatsLeft", parent_item.get("seats", 0))
            try:
                seats = int(seats_raw)
            except Exception:
                seats = 0

            results.append({
                "course": course,
                "type": mtype,
                "id": sec_id,
                "day": day_num,
                "start": st,
                "end": en,
                "location": loc,
                "instructor": inst,
                "seats": seats
            })
        return results

    def _parse_schedules_list(self, schedules_list, parent_item, course, mtype, sec_id):
        results = []
        for sub in schedules_list:
            day_num = self._parse_db_day(sub.get("day", ""))
            if day_num == 0:
                continue

            time_str = sub.get("time") or sub.get("schedule") or ""
            st, en = self._parse_time_range(time_str)
            if st < 0 or en < 0:
                continue

            loc = sub.get("location") or parent_item.get("location", "TBA")
            if loc == "Not specified":
                loc = "TBA"

            inst = parent_item.get("instructor", "Not Assigned")
            seats_raw = parent_item.get("seatsLeft", parent_item.get("seats", 0))
            try:
                seats = int(seats_raw)
            except Exception:
                seats = 0

            results.append({
                "course": course,
                "type": mtype,
                "id": sec_id,
                "day": day_num,
                "start": st,
                "end": en,
                "location": loc,
                "instructor": inst,
                "seats": seats
            })
        return results

    def _extract_section_meetings(self, raw_items, course="", mtype="", sec_id=""):
        meetings = []
        for item in raw_items:
            if "schedules" in item and isinstance(item["schedules"], list):
                meetings.extend(self._parse_schedules_list(item["schedules"], item, course, mtype, sec_id))
            elif "schedule" in item and isinstance(item["schedule"], str):
                meetings.extend(self._parse_schedule_string(item["schedule"], item, course, mtype, sec_id))
            elif "meetings" in item and isinstance(item["meetings"], list):
                meetings.extend(self._parse_schedules_list(item["meetings"], item, course, mtype, sec_id))
        return meetings

    @staticmethod
    def _get_section_prefix(sec_id):
        if not sec_id:
            return ""
        m = re.match(r'^\d+', str(sec_id).strip())
        if m:
            return m.group(0).lstrip("0") or "0"
        return str(sec_id).strip()

    def _on_right_click_block(self, card, meeting):
        course = meeting['course']
        mtype = meeting['type']
        curr_id = meeting['id']

        current_sched = self._get_schedule_at(self.current_schedule_idx)
        if not current_sched:
            return

        all_meetings = current_sched.get("meetings", [])
        # All meetings of the schedule excluding the ones for this course and subtype
        kept_meetings = [m for m in all_meetings if not (m['course'] == course and m['type'] == mtype)]

        # When strict mode is active, only show sections matching the current lecture group
        allow_cross = self.settings.get_boolean("allow-cross-section")
        required_prefixes = set()
        if not allow_cross:
            for m in kept_meetings:
                if m.get('course') == course and m.get('id'):
                    p = self._get_section_prefix(m.get('id'))
                    if p:
                        required_prefixes.add(p)

        candidate_sections = {}
        for item in self.data.get(course, []):
            if item.get("subtype") == mtype or item.get("type") == mtype:
                sec_id = item.get("section") or item.get("id")
                if sec_id:
                    candidate_sections.setdefault(sec_id, []).append(item)

        popover = Gtk.Popover()
        popover.set_size_request(340, -1)
        popover.set_parent(card)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        vbox.set_margin_top(16)
        vbox.set_margin_bottom(16)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        popover.set_child(vbox)

        lbl = Gtk.Label(label=f"<b>Replace {mtype} {curr_id}</b>", use_markup=True)
        #lbl.add_css_class("heading")
        vbox.append(lbl)

        scroll = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=360)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vbox.append(scroll)

        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        listbox.set_margin_end(5)
        listbox.set_margin_start(5)
        listbox.set_margin_top(5)
        listbox.set_margin_bottom(5)
        scroll.set_child(listbox)

        def _on_swap_row_activated(lb, row):
            if hasattr(row, 'parsed_meetings') and hasattr(row, 'sec_id'):
                self._replace_schedule_block(popover, kept_meetings, row.parsed_meetings, course, mtype, row.sec_id)

        listbox.connect("row-activated", _on_swap_row_activated)

        def check_conflict(candidate_meetings, active_meetings):
            for m1 in candidate_meetings:
                d1 = m1.get("day", 0)
                st1 = m1.get("start", -1)
                en1 = m1.get("end", -1)
                if d1 <= 0 or st1 < 0 or en1 < 0:
                    continue

                for m2 in active_meetings:
                    d2 = m2.get("day", 0)
                    st2 = m2.get("start", -1)
                    en2 = m2.get("end", -1)
                    if d2 <= 0 or st2 < 0 or en2 < 0:
                        continue

                    # Direct collision on the same day
                    if d1 == d2:
                        if st1 < en2 and en1 > st2:
                            return True
            return False

        has_options = False
        days_map = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
        sorted_sec_ids = sorted(candidate_sections.keys())

        for sec_id in sorted_sec_ids:
            if sec_id == curr_id:
                continue

            # Skip sections outside the enrolled lecture group if cross-section is disabled
            if required_prefixes:
                sec_prefix = self._get_section_prefix(sec_id)
                if sec_prefix not in required_prefixes:
                    continue

            raw_items = candidate_sections[sec_id]
            parsed_meetings = self._extract_section_meetings(
                raw_items, course=course, mtype=mtype, sec_id=sec_id
            )

            if not parsed_meetings:
                continue

            # Strict overlap checking against other schedule blocks (ignoring preset constraints)
            if not check_conflict(parsed_meetings, kept_meetings):
                inst = parsed_meetings[0]["instructor"]
                seats = parsed_meetings[0]["seats"]
                seats_str = f" • {seats} seats" if seats > 0 else (" • Full" if seats == 0 else "")

                time_strs = []
                for m in parsed_meetings:
                    d = days_map.get(m.get("day"), "")
                    st = m.get("start", -1)
                    en = m.get("end", -1)
                    if d and st >= 0 and en >= 0:
                        time_strs.append(f"{d} {st//60:02d}:{st%60:02d} - {en//60:02d}:{en%60:02d}")

                time_summary = ", ".join(time_strs) if time_strs else "TBA"

                row = Adw.ActionRow(title=f"Section {sec_id}")
                row.set_use_markup(True)
                row.set_subtitle(f"{inst}{seats_str}\n{time_summary}")
                row.set_subtitle_lines(2)
                row.set_activatable(True)

                row.sec_id = sec_id
                row.parsed_meetings = parsed_meetings

                listbox.append(row)
                has_options = True

        if not has_options:
            none_lbl = Gtk.Label(label="No conflict-free alternatives")
            none_lbl.add_css_class("dim-label")
            none_lbl.set_margin_top(12)
            none_lbl.set_margin_bottom(12)
            listbox.append(none_lbl)

        popover.connect("closed", lambda p: p.unparent() if p.get_parent() else None)
        popover.popup()

    def _replace_schedule_block(self, popover, kept_meetings, new_meetings_to_add, course, mtype, sec_id):
        popover.popdown()
        if popover.get_parent():
            popover.unparent()

        new_meetings = list(kept_meetings)
        for m in new_meetings_to_add:
            new_meetings.append({
                "course": course,
                "type": mtype,
                "id": sec_id,
                "location": m.get("location", "TBA"),
                "instructor": m.get("instructor", "Not Assigned"),
                "day": m.get("day", 0),
                "start": m.get("start", -1),
                "end": m.get("end", -1),
                "seats": m.get("seats", 0)
            })

        old_sched = self._get_schedule_at(self.current_schedule_idx)
        new_score = old_sched.get("score", 0.0) if old_sched else 0.0

        new_schedule_dict = {"score": new_score, "meetings": new_meetings}
        self.schedules[self.current_schedule_idx] = new_schedule_dict

        self.draw_schedule_index(self.current_schedule_idx)
        self.show_toast(f"Replaced {mtype} with Section {sec_id}")

    def _execute_branch_generation(self, active_courses):
        if not active_courses:
            self.show_error_dialog("Please select at least one course.")
            return

        temp_selected = list(active_courses.keys())
        pref_secs = []

        for course, data in active_courses.items():
            state = data.get("lock_state", "none")
            if state == "all" and data.get("all_sections"):
                pref_secs.extend([f"{course}:{sec}" for sec in data["all_sections"]])
            elif state == "lecture":
                lec_secs = data.get("lecture_sections") or data.get("all_sections", [])
                pref_secs.extend([f"{course}:{sec}" for sec in lec_secs])

        full_courses = []
        if self.ls_expander.get_enable_expansion():
            for c in temp_selected:
                if c not in self.ls_checkboxes or self.ls_checkboxes[c]['checkbox'].get_active():
                    full_courses.append(c)

        options = self._build_scheduler_options(
            courses=temp_selected,
            specific_sections=pref_secs,
            custom_exclude_full=full_courses,
        )
        self._start_scheduler(options)

    # =========================================================================
    # IMPORT SCHEDULE (MODERN REDESIGN)
    # =========================================================================

    def _parse_schedule_text(self, text):
        """Extracts valid course codes, exact meetings, and lecture section locks from schedule text."""
        new_selected = set()
        new_prefs = {}
        exact_imported = set()

        if not text:
            return new_selected, new_prefs, exact_imported, None

        course_sections = {}

        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or "|" not in line:
                continue
            tokens = line.split("|", 1)[0].strip().split()
            if not tokens:
                continue
            course = tokens[0]
            new_selected.add(course)
            if len(tokens) > 2:
                mtype = tokens[1]
                sec_id = tokens[2]
                exact_imported.add(f"{course}:{sec_id}")
                course_sections.setdefault(course, set()).add((mtype, sec_id))

                if mtype == "Lecture":
                    if course not in new_prefs:
                        new_prefs[course] = {"type": "Section", "value": []}
                    if f"Lecture:{sec_id}" not in new_prefs[course]["value"]:
                        new_prefs[course]["value"].append(f"Lecture:{sec_id}")

        # Validate against tampered cross-sections or duplicate sections
        for course, sec_set in course_sections.items():
            # 1. Reject multiple different section IDs for the same subtype (e.g. Tutorial 01A and 01B)
            subtypes = {}
            for mtype, sec_id in sec_set:
                subtypes.setdefault(mtype, set()).add(sec_id)
            for mtype, sids in subtypes.items():
                if len(sids) > 1:
                    sids_str = ", ".join(sorted(sids))
                    return set(), {}, set(), f"Tampered schedule: {course} contains multiple {mtype} sections ({sids_str})."

            # 2. Reject cross-sections (sections with different lecture group prefixes)
            prefixes = {self._get_section_prefix(sec_id) for _, sec_id in sec_set}
            if len(prefixes) > 1:
                sec_list = ", ".join(sorted({f"{mtype} {sec_id}" for mtype, sec_id in sec_set}))
                return set(), {}, set(), f"Cross-section detected in {course}: incompatible sections ({sec_list})."

        return new_selected, new_prefs, exact_imported, None

    def on_import_clicked(self, _button):
        dialog = ImportDialog(parse_preview_fn=self._parse_schedule_text)
        dialog.connect("imported", lambda d, text: self._parse_and_import_schedule(text))
        dialog.present(self)

    def _parse_and_import_schedule(self, text):
        res = self._parse_schedule_text(text)
        error_msg = None
        if len(res) == 4:
            new_selected, new_prefs, exact_imported, error_msg = res
        else:
            new_selected, new_prefs, exact_imported = res

        if error_msg:
            self.show_error_dialog(error_msg)
            return False

        if not new_selected:
            self.show_error_dialog("Could not parse any valid courses from text.")
            return False

        self.selected_courses = valid_selected
        self.course_preferences = {c: p for c, p in new_prefs.items() if c in valid_selected}
        self.imported_exact_match = {pair for pair in exact_imported if pair.split(":")[0] in valid_selected}

        self._save_courses_and_preferences()
        self.populate_listbox()
        self._update_courses_counter()
        self.on_generate_clicked(None)

        if missing:
            missing_str = ", ".join(sorted(missing))
            self.show_toast(f"Imported {len(valid_selected)} course(s). Skipped missing: {missing_str}")
        else:
            self.show_toast(f"Imported {len(valid_selected)} course(s) successfully")

        return True

    def on_key_pressed(self, controller, keyval, keycode, state):
        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_g, Gdk.KEY_G):
                if not self.scheduler.is_running:
                    self.on_generate_clicked(None)
                return True
            elif keyval in (Gdk.KEY_c, Gdk.KEY_C) and self.schedules:
                self.on_copy_schedule_clicked(self.copy_btn)
                return True
            elif keyval in (Gdk.KEY_s, Gdk.KEY_S):
                self.show_sidebar_btn.set_active(not self.show_sidebar_btn.get_active())
                return True
            elif keyval in (Gdk.KEY_i, Gdk.KEY_I):
                model = self.block_info_combo.get_model()
                if model:
                    num_items = model.get_n_items()
                    if num_items > 0:
                        current = self.block_info_combo.get_selected()
                        self.block_info_combo.set_selected((current + 1) % num_items)
                return True

        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if keyval == Gdk.KEY_Right:
            if is_shift:
                self._on_next_favorite()
                return True
            elif self.next_btn.get_sensitive():
                self._on_next_clicked(None)
                return True
        elif keyval == Gdk.KEY_Left:
            if is_shift:
                self._on_prev_favorite()
                return True
            elif self.prev_btn.get_sensitive():
                self._on_previous_clicked(None)
                return True

        return False

    def open_json(self, _button):
        file_dialog = Gtk.FileDialog()
        json_filter = Gtk.FileFilter(name="JSON Database")
        json_filter.add_mime_type("application/json")
        json_filter.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(json_filter)
        file_dialog.set_default_filter(json_filter)
        file_dialog.open(self, None, self.on_json_opened)

    def on_json_opened(self, file_dialog, result):
        try:
            file = file_dialog.open_finish(result)
            if file and file.get_path():
                self.db_service.load_local_file_async(file.get_path())
        except GLib.Error as e:
            print(f"File open error: {e.message}")

    def _on_local_json_loaded(self, _service, data, path):
        self.placeholder_label.set_text("No courses match your search")
        self.data = data
        self.json_path = path
        self.populate_listbox()
        self.show_toast("Loaded local database")

    def on_close_request(self, *args):
        self.scheduler.cancel()
        self._save_courses_and_preferences()
        return False

    def _on_delete_save_clicked(self, _button):
        self.scheduler.cancel()
        self.generate.set_label("Generate Schedules")
        self.generate.remove_css_class("destructive-action")
        self.generate.add_css_class("suggested-action")
        self.generate.set_sensitive(True)

        # 2. Reset all persistent GSettings to defaults
        for key in self.settings.list_keys():
            self.settings.reset(key)

        # 3. Clear in-memory courses, preferences, and import/branch data
        self.selected_courses.clear()
        self.course_preferences.clear()
        self._saved_selected_courses.clear()
        self.imported_exact_match = None
        self._save_courses_and_preferences()

        # 4. Reset curriculum preset dropdowns
        if hasattr(self, 'major_combo') and self.major_combo:
            self.major_combo.set_selected(0)

        # 5. Clear course search entry
        if hasattr(self, 'searchentry') and self.searchentry:
            self.searchentry.set_text("")

        # 6. Reset schedule storage, navigation, and favorites
        self.schedules = []
        self.current_schedule_idx = 0
        self.favorites.clear()
        self.fav_btn.set_sensitive(False)
        self.fav_btn.set_icon_name("non-starred-2-symbolic")

        # 7. Reset block information preference
        if hasattr(self, 'block_info_combo') and self.block_info_combo:
            self.block_info_combo.set_selected(0)

        # 8. Collapse expander rows
        if hasattr(self, 'time') and self.time:
            self.time.set_expanded(False)
        if hasattr(self, 'gap_time') and self.gap_time:
            self.gap_time.set_expanded(False)
        if hasattr(self, 'ls_expander') and self.ls_expander:
            self.ls_expander.set_expanded(False)

        # 9. Dismiss popovers and active toasts
        if hasattr(self, 'stats_popover') and self.stats_popover:
            self.stats_popover.popdown()
        self.dismiss_toasts()

        # 10. Re-render UI back to initial state
        self.populate_listbox()
        self.timetable.clear()
        self.schedule.set_visible(False)
        self.schedule_status.set_visible(True)
        self.schedule_status.set_title("No Schedules Yet")
        self.schedule_status.set_description("Select your courses and constraints, then click Generate Schedules.")
        self.schedule_status.set_icon_name("work-week-symbolic")
        self.schedule_counter_label.set_text("No schedules generated")
        self.stats_btn.set_sensitive(False)
        self.stats_summary_label.set_text("")
        self._update_navigation_buttons()

        self.show_toast("Preferences reset to default")

    def show_message_dialog(self, heading, body):
        dialog = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.connect("response", lambda d, r: d.close())
        dialog.present()

    def show_error_dialog(self, message):
        self.show_message_dialog("Error", message)
