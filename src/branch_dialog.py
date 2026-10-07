import re
from gi.repository import Adw, Gtk, GLib, GObject

@Gtk.Template(resource_path='/io/github/Epoch5427/Commodus/branch_dialog.ui')
class BranchDialog(Adw.Dialog):
    __gtype_name__ = 'CommodusBranchDialog'

    __gsignals__ = {
        'reschedule-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    cancel_btn = Gtk.Template.Child()
    generate_btn = Gtk.Template.Child()
    current_listbox = Gtk.Template.Child()
    catalog_search = Gtk.Template.Child()
    catalog_listbox = Gtk.Template.Child()

    def __init__(self, current_sched, course_data, clean_title_fn, colors, toast_fn, **kwargs):
        super().__init__(**kwargs)
        self.course_data = course_data
        self.clean_title_fn = clean_title_fn
        self.colors = colors
        self.toast_fn = toast_fn

        self.active_courses = {}
        self.catalog_rows_dict = {}

        # 1. Parse current schedule course metadata
        self.current_courses_data = {}
        for m in current_sched.get('meetings', []):
            c = m['course']
            if c not in self.current_courses_data:
                self.current_courses_data[c] = {
                    "all_sections": set(),
                    "lecture_sections": set(),
                    "instructors": set(),
                }

            m_type = m.get('type', '')
            m_id = str(m.get('id', '')).strip()
            inst = m.get('instructor', '').strip()

            if m_id:
                sec_tag = f"{m_type}:{m_id}"
                self.current_courses_data[c]["all_sections"].add(sec_tag)
                if m_type == "Lecture":
                    self.current_courses_data[c]["lecture_sections"].add(sec_tag)
            if inst and inst != "Not Assigned":
                self.current_courses_data[c]["instructors"].add(inst)

        unique_courses = sorted(list(self.current_courses_data.keys()))
        self.course_color_idx_map = {c: i % len(self.colors) for i, c in enumerate(unique_courses)}

        # 2. Populate "In This Schedule" listbox
        for c in unique_courses:
            self._create_active_course_row(c, is_current=True, initial_lock="all")

        # 3. Populate "Add Courses" catalog listbox
        self.catalog_rows = []
        for course_code in sorted(self.course_data.keys()):
            c_title = self.clean_title_fn(course_code)
            cat_row = Adw.ActionRow(title=GLib.markup_escape_text(c_title))
            cat_row.set_title_lines(1)
            cat_row.set_tooltip_text(c_title)

            add_btn = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"])
            add_btn.set_tooltip_text(f"Add {course_code} to schedule")
            cat_row.add_suffix(add_btn)

            if course_code in self.active_courses:
                add_btn.set_icon_name("object-select-symbolic")
                add_btn.set_sensitive(False)

            add_btn.connect("clicked", self._on_add_clicked, course_code, add_btn)
            self.catalog_listbox.append(cat_row)

            self.catalog_rows_dict[course_code] = {"row": cat_row, "btn": add_btn}
            self.catalog_rows.append((cat_row, course_code, c_title))

        # 4. Wire controls
        self.catalog_search.connect("search-changed", self._on_catalog_search_changed)
        self.cancel_btn.connect("clicked", lambda *_: self.close())
        self.generate_btn.connect("clicked", self._on_submit_clicked)

    def _create_active_course_row(self, course_code, is_current=True, initial_lock="all"):
        display_title = self.clean_title_fn(course_code)
        row = Adw.ActionRow(title=GLib.markup_escape_text(display_title))
        row.set_title_lines(1)
        row.set_subtitle_lines(1)

        color_idx = self.course_color_idx_map.get(course_code, len(self.active_courses) % len(self.colors))
        color_hex = self.colors[color_idx]
        dot = Gtk.Label(use_markup=True)
        dot.set_markup(f"<span foreground='{color_hex}'>●</span>")
        dot.set_margin_start(4)
        dot.set_margin_end(6)
        row.add_prefix(dot)

        sec_info = self.current_courses_data.get(course_code, {})
        all_secs = {s.split(":", 1)[1] if ":" in s else s for s in sec_info.get("all_sections", [])}
        all_secs_str = ", ".join(sorted(all_secs)) if all_secs else ""

        lec_secs = {s.split(":", 1)[1] if ":" in s else s for s in sec_info.get("lecture_sections", [])}
        lec_secs_str = ", ".join(sorted(lec_secs)) if lec_secs else all_secs_str

        inst_str = ", ".join(sorted(sec_info.get("instructors", []))) if sec_info.get("instructors") else ""
        inst_part = f" • {inst_str}" if inst_str else ""

        self.active_courses[course_code] = {
            "lock_state": initial_lock if is_current else "none",
            "all_sections": sec_info.get("all_sections", set()),
            "lecture_sections": sec_info.get("lecture_sections", set()),
            "is_current": is_current,
            "row": row
        }

        suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)

        if is_current:
            lock_btn = Gtk.Button(valign=Gtk.Align.CENTER, css_classes=["flat"])

            def update_display():
                state = self.active_courses[course_code]["lock_state"]
                tooltip_lines = [display_title]

                if state == "all":
                    lock_btn.set_icon_name("changes-prevent-symbolic")
                    lock_btn.set_tooltip_text("Locked: All sections (Lecture, Lab, Tutorial)\nClick to lock Lecture only")
                    desc = f"Section {all_secs_str}" if all_secs_str else ""
                    row.set_subtitle(f"Locked: {desc}{inst_part}" if desc else f"Locked{inst_part}")
                    tooltip_lines.append("Lock: All Sections (Lecture, Lab, Tutorial)")
                    if all_secs_str:
                        tooltip_lines.append(f"Sections: {all_secs_str}")
                elif state == "lecture":
                    lock_btn.set_icon_name("changes-semi-prevent-symbolic")
                    lock_btn.set_tooltip_text("Locked: Lecture only (Lab/Tutorial flexible)\nClick to make flexible")
                    desc = f"Section {lec_secs_str}" if lec_secs_str else ""
                    row.set_subtitle(f"Locked (Lecture): {desc}{inst_part}" if desc else f"Locked (Lecture){inst_part}")
                    tooltip_lines.append("Lock: Lecture Only (Lab and Tutorial flexible)")
                    if lec_secs_str:
                        tooltip_lines.append(f"Lecture Section: {lec_secs_str}")
                else:
                    lock_btn.set_icon_name("changes-semi-allow-symbolic")
                    lock_btn.set_tooltip_text("Flexible: Any section allowed\nClick to lock all sections")
                    row.set_subtitle("Flexible (Any section)")
                    tooltip_lines.append("Lock: Flexible (Any section allowed)")

                if inst_str:
                    tooltip_lines.append(f"Instructor(s): {inst_str}")

                row.set_tooltip_text("\n".join(tooltip_lines))
                self.generate_btn.set_sensitive(len(self.active_courses) > 0)

            def on_lock_clicked(_b):
                curr = self.active_courses[course_code]["lock_state"]
                self.active_courses[course_code]["lock_state"] = "lecture" if curr == "all" else ("none" if curr == "lecture" else "all")
                update_display()

            lock_btn.connect("clicked", on_lock_clicked)
            update_display()
            suffix_box.append(lock_btn)
        else:
            row.set_subtitle("Flexible (Any section)")
            row.set_tooltip_text(f"{display_title}\nLock: Flexible (Any section allowed)")

        remove_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat", "destructive-action"])
        remove_btn.set_tooltip_text(f"Remove {course_code}")

        def on_remove_clicked(_b):
            self.current_listbox.remove(row)
            self.active_courses.pop(course_code, None)
            self.generate_btn.set_sensitive(len(self.active_courses) > 0)
            if course_code in self.catalog_rows_dict:
                btn = self.catalog_rows_dict[course_code]["btn"]
                btn.set_icon_name("list-add-symbolic")
                btn.set_sensitive(True)

        remove_btn.connect("clicked", on_remove_clicked)
        suffix_box.append(remove_btn)
        row.add_suffix(suffix_box)
        self.current_listbox.append(row)
        self.generate_btn.set_sensitive(len(self.active_courses) > 0)

    def _get_course_credits(self, course_code):
        c_info = self.course_data.get(course_code, [])
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

    def _on_add_clicked(self, _b, code, btn):
        if code not in self.active_courses:
            total_credits = sum(self._get_course_credits(c) for c in self.active_courses)
            tentative_credits = total_credits + self._get_course_credits(code)

            if tentative_credits > 21:
                self.toast_fn("Maximum credit load (21) reached")
                return

            is_sched = code in self.current_courses_data
            self._create_active_course_row(code, is_current=is_sched, initial_lock="none")
            btn.set_icon_name("object-select-symbolic")
            btn.set_sensitive(False)

    def _on_catalog_search_changed(self, entry):
        q = entry.get_text().strip().lower()
        for r, code, full_name in self.catalog_rows:
            r.set_visible(not q or q in code.lower() or q in full_name.lower())

    def _on_submit_clicked(self, _btn):
        self.close()
        self.emit('reschedule-requested', self.active_courses)
