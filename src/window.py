from gi.repository import Adw, Gtk, Gio, GLib, Gdk, Pango, GObject
import json
import re
import subprocess
import os
import shutil
import urllib.request
import threading
import time

COURSE_COLORS = [
    "#3584e4",  # Blue
    "#2ec27e",  # Green
    "#e66100",  # Orange
    "#9141ac",  # Purple
    "#e01b24",  # Red
    "#00a3c4",  # Cyan
    "#f66151",  # Coral
    "#c061cb",  # Magenta
]

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

    ls_switch = Gtk.Template.Child()
    tuner = Gtk.Template.Child()
    sec_tuner = Gtk.Template.Child()
    generate = Gtk.Template.Child()

    prev_btn = Gtk.Template.Child()
    next_btn = Gtk.Template.Child()
    schedule_counter_label = Gtk.Template.Child()
    fav_btn = Gtk.Template.Child()
    copy_btn = Gtk.Template.Child()
    compare_btn = Gtk.Template.Child()
    import_btn = Gtk.Template.Child()

    stats_btn = Gtk.Template.Child()
    stats_summary_label = Gtk.Template.Child()

    schedule_scroll = Gtk.Template.Child()
    schedule_status = Gtk.Template.Child()
    schedule = Gtk.Template.Child()

    prefs_dialog = Gtk.Template.Child()
    dm_switch = Gtk.Template.Child()
    wrap_switch = Gtk.Template.Child()
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
        self.schedules = []
        self.current_schedule_idx = 0
        self.generation_process = None
        self.json_path = None

        self.major_keys = []
        self.semester_keys = []

        self.favorites = set()  # In-memory session favorites
        self._next_long_pressed = False
        self._prev_long_pressed = False

        # Setup ListBox Empty Placeholder
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        placeholder.set_margin_top(16)
        placeholder.set_margin_bottom(16)
        placeholder.set_margin_start(12)
        placeholder.set_margin_end(12)
        placeholder_label = Gtk.Label(label="No courses match your search")
        placeholder_label.add_css_class("dim-label")
        placeholder.append(placeholder_label)
        self.listbox.set_placeholder(placeholder)

        self.major_combo.connect("notify::selected", self._on_major_changed)
        self.semester_combo.connect("notify::selected", self._on_semester_changed)
        self.clear_sec.connect("clicked", self.on_clear_sec_clicked)
        self.searchentry.connect("search-changed", self._on_search_changed)

        self.network_banner.connect("button-clicked", self._on_banner_retry)

        self.generate.connect("clicked", self.on_generate_clicked)
        self.prev_btn.connect("clicked", self._on_previous_clicked)
        self.next_btn.connect("clicked", self._on_next_clicked)
        self.copy_btn.connect("clicked", self.on_copy_schedule_clicked)
        self.compare_btn.connect("clicked", self.on_compare_clicked)
        self.import_btn.connect("clicked", self.on_import_clicked)

        self.wrap_switch.connect("notify::active", lambda *_: self._update_navigation_buttons())
        self.delete_save.connect("activated", self._on_delete_save_clicked)
        self.fpickerbutton.connect("clicked", self.open_json)
        self.local_load_switch.connect("notify::active", lambda sw, *_: self.fpickerbutton.set_sensitive(sw.get_active()))

        self.fav_btn.connect("clicked", self.on_toggle_favorite_clicked)

        # Attach Long Press Gestures to navigation buttons
        next_gesture = Gtk.GestureLongPress.new()
        next_gesture.connect("pressed", self._on_next_btn_long_pressed)
        self.next_btn.add_controller(next_gesture)

        prev_gesture = Gtk.GestureLongPress.new()
        prev_gesture.connect("pressed", self._on_prev_btn_long_pressed)
        self.prev_btn.add_controller(prev_gesture)

        style_manager = Adw.StyleManager.get_default()
        self.dm_switch.connect(
            "notify::active",
            lambda *_: style_manager.set_color_scheme(
                Adw.ColorScheme.FORCE_DARK if self.dm_switch.get_active() else Adw.ColorScheme.FORCE_LIGHT
            ),
        )

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_ctrl)

        self.listbox.set_filter_func(self._filter_courses)
        self.listbox.set_sort_func(self._sort_courses)

        self.connect("close-request", self.on_close_request)

        self._init_course_styles()
        self._init_stats_popover()
        self._setup_settings_bindings()
        self._load_saved_courses_and_preferences()

        self._load_cached_database()
        self._fetch_database_async()

        GLib.timeout_add(650, lambda: self.show_sidebar_btn.set_active(True))

    def _init_course_styles(self):
        css_rules = [
            f".course-color-{i} {{ border-left: 2px solid {color}; }}"
            for i, color in enumerate(COURSE_COLORS)
        ]
        provider = Gtk.CssProvider()
        provider.load_from_data("\n".join(css_rules).encode('utf-8'))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _setup_settings_bindings(self):
        """Bind UI widgets directly to GSettings for automatic 2-way sync."""
        b = self.settings.bind
        flags = Gio.SettingsBindFlags.DEFAULT

        # Time Boundary
        b("time-enabled", self.time, "enable-expansion", flags)
        b("start-hours", self.start_hours, "value", flags)
        b("start-minutes", self.start_minutes, "value", flags)
        b("end-hours", self.end_hours, "value", flags)
        b("end-minutes", self.end_minutes, "value", flags)

        # Gap Specification
        b("gap-enabled", self.gap_time, "enable-expansion", flags)
        b("gap-day", self.gap_day, "selected", flags)
        b("gap-start-hours", self.gap_start_hours, "value", flags)
        b("gap-start-minutes", self.gap_start_minutes, "value", flags)
        b("gap-end-hours", self.gap_end_hours, "value", flags)
        b("gap-end-minutes", self.gap_end_minutes, "value", flags)

        # Excluded Days
        b("checksun", self.checksun, "active", flags)
        b("checkmon", self.checkmon, "active", flags)
        b("checktue", self.checktue, "active", flags)
        b("checkwed", self.checkwed, "active", flags)
        b("checkthu", self.checkthu, "active", flags)
        b("checkfri", self.checkfri, "active", flags)
        b("checksat", self.checksat, "active", flags)

        # Optimization & Filters
        b("exclude-full", self.ls_switch, "active", flags)
        b("tuner", self.tuner, "selected", flags)
        b("sec-tuner", self.sec_tuner, "selected", flags)

        # Preferences
        b("dark-mode", self.dm_switch, "active", flags)
        b("wrap-mode", self.wrap_switch, "active", flags)
        b("local-load", self.local_load_switch, "active", flags)

        # Initialize button sensitivity
        self.fpickerbutton.set_sensitive(self.local_load_switch.get_active())

    def _load_saved_courses_and_preferences(self):
        self._saved_selected_courses = set(self.settings.get_strv("selected-courses"))
        try:
            raw_pref = self.settings.get_string("course-preferences")
            self.course_preferences = json.loads(raw_pref) if raw_pref else {}
        except Exception:
            self.course_preferences = {}

    def _save_courses_and_preferences(self):
        self.settings.set_strv("selected-courses", list(self.selected_courses))
        self.settings.set_string("course-preferences", json.dumps(self.course_preferences))

    # --- Stats Popover ---
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
                if duration % 30 == 29:
                    duration += 1
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

    def show_toast(self, text, timeout=3):
        toast = Adw.Toast.new(text)
        toast.set_timeout(timeout)
        self.toast_overlay.add_toast(toast)

    def _on_banner_retry(self, _banner):
        self.network_banner.set_revealed(False)
        self.show_toast("Connecting to database...")
        self._fetch_database_async()

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

    def _load_cached_database(self):
        cache_dir = os.path.join(GLib.get_user_cache_dir(), "commodus")
        local_db_path = os.path.join(cache_dir, "database.json")
        local_spec_path = os.path.join(cache_dir, "curriculum_spec.json")

        if os.path.exists(local_db_path):
            try:
                with open(local_db_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                self.json_path = local_db_path
                self.populate_listbox()
            except Exception as e:
                print(f"Error loading cached database: {e}")

        if os.path.exists(local_spec_path):
            try:
                with open(local_spec_path, 'r', encoding='utf-8') as f:
                    self.curriculum_data = json.load(f)
                self._populate_curriculum_dropdowns()
            except Exception as e:
                print(f"Error loading cached curriculum specs: {e}")

    def _fetch_database_async(self):
        def fetch_task():
            db_url = "https://raw.githubusercontent.com/Epoch5427/Commodus/app-data/NU_course_data.json"
            spec_url = "https://raw.githubusercontent.com/Epoch5427/Commodus/app-data/curriculum_spec.json"

            cache_dir = os.path.join(GLib.get_user_cache_dir(), "commodus")
            os.makedirs(cache_dir, exist_ok=True)
            local_db_path = os.path.join(cache_dir, "database.json")
            local_spec_path = os.path.join(cache_dir, "curriculum_spec.json")

            parsed_db = None
            parsed_spec = None

            context = None
            if os.name == 'nt':
                import ssl
                context = ssl._create_unverified_context()

            try:
                req_db = urllib.request.Request(db_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_db, context=context, timeout=8) as response:
                    db_content = response.read().decode('utf-8')
                parsed_db = json.loads(db_content)
                with open(local_db_path, 'w', encoding='utf-8') as f:
                    f.write(db_content)
            except Exception as e:
                print(f"Silent fetch note (DB): {e}")

            try:
                req_spec = urllib.request.Request(spec_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_spec, context=context, timeout=8) as response:
                    spec_content = response.read().decode('utf-8')
                parsed_spec = json.loads(spec_content)
                with open(local_spec_path, 'w', encoding='utf-8') as f:
                    f.write(spec_content)
            except Exception as e:
                print(f"Silent fetch note (Spec): {e}")

            GLib.idle_add(self._on_fetch_complete, local_db_path, parsed_db, parsed_spec)

        threading.Thread(target=fetch_task, daemon=True).start()

    def _on_fetch_complete(self, local_db_path, parsed_db, parsed_spec):
        if parsed_db:
            had_prior_data = bool(self.data)
            self.data = parsed_db
            self.json_path = local_db_path
            self.populate_listbox()
            if had_prior_data:
                self.show_toast("Course database updated")

        if parsed_spec:
            self.curriculum_data = parsed_spec
            self._populate_curriculum_dropdowns()

        if not parsed_db:
            if self.data:
                self.network_banner.set_title("Offline: Using cached database.")
                self.network_banner.set_button_label("Retry")
                self.network_banner.set_revealed(True)
                self.show_toast("Loaded cached database")
            else:
                self.network_banner.set_title("Cannot reach database. Check internet connection.")
                self.network_banner.set_button_label("Retry")
                self.network_banner.set_revealed(True)
        else:
            self.network_banner.set_revealed(False)

        return False

    def _populate_curriculum_dropdowns(self):
        if not self.curriculum_data or "majors" not in self.curriculum_data:
            return

        self.major_keys = ["none"]
        major_names = ["—"]

        for key in self.curriculum_data["majors"].keys():
            self.major_keys.append(key)
            major_names.append(key)

        self.major_combo.set_model(Gtk.StringList.new(major_names))
        self.semester_combo.set_model(Gtk.StringList.new(["—"]))
        self.semester_combo.set_sensitive(False)

    def _on_major_changed(self, combo, pspec):
        idx = combo.get_selected()
        if idx <= 0 or idx >= len(self.major_keys):
            self.semester_combo.set_model(Gtk.StringList.new(["—"]))
            self.semester_combo.set_sensitive(False)
            return

        major_key = self.major_keys[idx]
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

    def _update_courses_counter(self):
        num = len(self.selected_courses)
        oldnum = self.numcourses.get_fraction()

        target = Adw.PropertyAnimationTarget.new(self.numcourses, "fraction")

        animation = Adw.TimedAnimation(
            widget=self.numcourses,
            value_from=oldnum,
            value_to=num/7,
            duration=500,
            easing=Adw.Easing.EASE,
            target=target,
        )

        self.numcourses.set_text(f"{num}/7")
        self.numcourses.set_fraction(min(num / 7.0, 1.0))
        animation.play()

    def populate_listbox(self):
        child = self.listbox.get_first_child()
        while child:
            self.listbox.remove(child)
            child = self.listbox.get_first_child()

        saved_selection = self._saved_selected_courses if hasattr(self, '_saved_selected_courses') and self._saved_selected_courses else set(self.selected_courses)
        self.selected_courses = set(saved_selection)

        sorted_keys = sorted(self.data.keys())

        for course_code in sorted_keys:
            sections_list = self.data[course_code]
            full_title = sections_list[0].get("fullTitle", "") if sections_list else ""

            clean_title = ""
            if full_title:
                prefix_pattern = re.compile(rf"^{re.escape(course_code)}\s*[:-]?\s*", re.IGNORECASE)
                clean_title = prefix_pattern.sub("", full_title)

            display_title = f"{course_code}: {clean_title}" if clean_title and clean_title.lower() != course_code.lower() else course_code
            escaped_title = GLib.markup_escape_text(display_title)

            row = Adw.ActionRow(title=escaped_title)
            row.course_code = course_code
            row.clean_title = clean_title
            row.set_title_lines(2)

            chboxcont = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
            row.add_suffix(chboxcont)

            lec_instructors = set()
            lab_instructors = set()
            tut_instructors = set()
            sections = set()

            for sec in sections_list:
                inst = sec.get("instructor")
                subtype = sec.get("subtype")
                s_id = sec.get("section")

                if inst and inst != "Not Assigned":
                    if subtype == "Lecture": lec_instructors.add(inst)
                    elif subtype == "Lab": lab_instructors.add(inst)
                    elif subtype == "Tutorial": tut_instructors.add(inst)

                if subtype == "Lecture" and s_id:
                    sections.add(s_id)

            lec_inst_list = sorted(list(lec_instructors))
            lab_inst_list = sorted(list(lab_instructors))
            tut_inst_list = sorted(list(tut_instructors))
            sec_list = sorted(list(sections))

            has_instructors = len(lec_inst_list) > 1 or len(lab_inst_list) > 1 or len(tut_inst_list) > 1
            has_sections = len(sec_list) > 1

            menubutton = Gtk.MenuButton()
            menubutton.set_valign(Gtk.Align.CENTER)
            menubutton.add_css_class("flat")
            menubutton.set_tooltip_text("Filter by Section or Instructor")

            saved_pref = self.course_preferences.get(course_code, {"type": "Neither", "value": ""})
            saved_inst_set = set()
            if saved_pref.get("type") == "Instructor":
                val = saved_pref.get("value", [])
                saved_inst_set = set(val) if isinstance(val, list) else ({val} if val else set())

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

                inst_checkbox_map = {}

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

                    lbl = Gtk.Label(label="<b>Sections</b>", use_markup=True, halign=Gtk.Align.START)
                    lbl.add_css_class("dim-label")
                    sec_vbox.append(lbl)

                    def on_sec_toggled(btn, s_val, c=course_code, mb=menubutton, icm=inst_checkbox_map):
                        if btn.get_active():
                            for cb in icm.values():
                                cb.set_active(False)
                            self.course_preferences[c] = {"type": "Section", "value": s_val}
                            mb.set_icon_name("funnel-symbolic")
                            self._save_courses_and_preferences()

                    for sec in sec_list:
                        sec_label = Gtk.Label(label=sec, ellipsize=Pango.EllipsizeMode.END, max_width_chars=20, xalign=0)
                        btn = Gtk.CheckButton(child=sec_label, group=hidden_none_btn)
                        btn.connect("toggled", on_sec_toggled, sec)
                        sec_vbox.append(btn)
                        if saved_pref.get("type") == "Section" and saved_pref.get("value") == sec:
                            btn.set_active(True)

                # Initialize active page state (correctly nested inside else)
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

                def on_stack_page_changed(stk, _param, c=course_code, mb=menubutton, hnb=hidden_none_btn, icm=inst_checkbox_map):
                    page = stk.get_visible_child_name()
                    if page == "none":
                        hnb.set_active(True)
                        for cb in icm.values():
                            cb.set_active(False)
                        self.course_preferences[c] = {"type": "Neither", "value": ""}
                        mb.set_icon_name("funnel-outline-symbolic")
                        self._save_courses_and_preferences()
                    elif page == "instructors":
                        hnb.set_active(True)
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
                        pref = self.course_preferences.get(c, {})
                        if pref.get("type") != "Section" or not pref.get("value"):
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

        self._saved_selected_courses = set()
        self._update_courses_counter()

    def on_course_toggled(self, checkbox, course_code):
        if checkbox.get_active():
            if len(self.selected_courses) < 7:
                self.selected_courses.add(course_code)
            else:
                checkbox.set_active(False)
                self.show_toast("Maximum of 7 courses reached")
        else:
            self.selected_courses.discard(course_code)

        self._save_courses_and_preferences()
        self.listbox.invalidate_sort()
        self._update_courses_counter()

    def on_generate_clicked(self, _button):
        if not self.json_path or not self.selected_courses:
            self.show_error_dialog("Please select at least one course to generate schedules.")
            return

        scheduler_path = shutil.which('scheduler')
        if not scheduler_path:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            exe_name = 'scheduler.exe' if os.name == 'nt' else 'scheduler'
            scheduler_path = os.path.join(project_root, 'build', 'c++', exe_name)
            if not os.path.exists(scheduler_path):
                self.show_error_dialog(f"Error: Could not find 'scheduler' executable at {scheduler_path}.")
                return

        cmd = [
            scheduler_path,
            '--json-file', self.json_path,
            '--courses', ",".join(self.selected_courses)
        ]

        pref_insts = []
        pref_secs = []
        for c in self.selected_courses:
            pref = self.course_preferences.get(c)
            if pref and pref.get("type") == "Instructor" and pref.get("value"):
                val = pref["value"]
                # Unpack list items individually without brackets/quotes
                if isinstance(val, list):
                    for inst in val:
                        if inst:
                            pref_insts.append(f"{c}:{inst}")
                elif isinstance(val, str) and val:
                    pref_insts.append(f"{c}:{val}")
            elif pref and pref.get("type") == "Section" and pref.get("value"):
                pref_secs.append(f"{c}:{pref['value']}")

        if pref_insts: cmd.extend(['--preferred-instructors', "|".join(pref_insts)])
        if pref_secs: cmd.extend(['--specific-sections', "|".join(pref_secs)])

        excluded_days = []
        if self.checksun.get_active(): excluded_days.append("1")
        if self.checkmon.get_active(): excluded_days.append("2")
        if self.checktue.get_active(): excluded_days.append("3")
        if self.checkwed.get_active(): excluded_days.append("4")
        if self.checkthu.get_active(): excluded_days.append("5")
        if self.checkfri.get_active(): excluded_days.append("6")
        if self.checksat.get_active(): excluded_days.append("7")
        if excluded_days:
            cmd.extend(['--exclude-days', ",".join(excluded_days)])

        if self.time.get_enable_expansion():
            start_h = self.start_hours.get_value_as_int()
            start_m = self.start_minutes.get_value_as_int()
            cmd.extend(['--start-time', f"{start_h:02d}:{start_m:02d}"])

            end_h = self.end_hours.get_value_as_int()
            end_m = self.end_minutes.get_value_as_int()
            cmd.extend(['--end-time', f"{end_h:02d}:{end_m:02d}"])

        if self.gap_time.get_enable_expansion():
            g_start_h = self.gap_start_hours.get_value_as_int()
            g_start_m = self.gap_start_minutes.get_value_as_int()
            cmd.extend(['--gap-start', f"{g_start_h:02d}:{g_start_m:02d}"])

            g_end_h = self.gap_end_hours.get_value_as_int()
            g_end_m = self.gap_end_minutes.get_value_as_int()
            cmd.extend(['--gap-end', f"{g_end_h:02d}:{g_end_m:02d}"])
            cmd.extend(['--gap-day', str(self.gap_day.get_selected())])

        if self.ls_switch.get_active():
            cmd.extend(['--exclude-full', 'true'])

        opt_metric_map = {0: "compact", 1: "few-days", 2: "balanced-days", 3: "consistent-times"}
        cmd.extend(['--optimize-by', opt_metric_map.get(self.tuner.get_selected(), "compact")])

        sec_metric_map = {0: "none", 1: "compact", 2: "few-days", 3: "balanced-days", 4: "consistent-times"}
        sec_metric = sec_metric_map.get(self.sec_tuner.get_selected(), "none")
        if sec_metric != "none":
            cmd.extend(['--secondary-optimize-by', sec_metric])

        self.start_scheduler_thread(cmd)

    def start_scheduler_thread(self, cmd):
        self.schedules = []
        self.current_schedule_idx = 0
        self.favorites.clear()
        self.fav_btn.set_sensitive(False)
        self.fav_btn.set_icon_name("non-starred-symbolic")

        if self.generation_process:
            try:
                self.generation_process.terminate()
            except Exception:
                pass

        self._clear_schedule_grid()
        self.schedule.set_visible(False)
        self.schedule_status.set_visible(True)
        self.schedule_status.set_title("Generating Schedules...")
        self.schedule_status.set_description("Searching conflict-free combinations...")
        self.schedule_status.set_icon_name("content-loading-symbolic")
        self.schedule_counter_label.set_text("Generating...")
        self.stats_btn.set_sensitive(False)
        self.stats_summary_label.set_text("")

        threading.Thread(target=self._run_scheduler_async, args=(cmd,), daemon=True).start()

    def _run_scheduler_async(self, cmd):
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        self.generation_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs
        )

        batch = []
        last_update = time.time()

        for line in self.generation_process.stdout:
            line = line.strip()
            if not line: continue
            try:
                parsed = json.loads(line)
                batch.append(parsed)
                now = time.time()
                if now - last_update > 0.1:
                    GLib.idle_add(self._on_schedules_batch_received, list(batch))
                    batch.clear()
                    last_update = now
            except json.JSONDecodeError:
                pass

        if batch:
            GLib.idle_add(self._on_schedules_batch_received, list(batch))

        self.generation_process.wait()
        ret_code = self.generation_process.returncode
        stderr = self.generation_process.stderr.read()

        GLib.idle_add(self._on_generation_complete, ret_code, stderr)

    def _on_schedules_batch_received(self, batch):
        if not batch: return
        old_top = self.schedules[0] if self.schedules else None
        self.schedules.extend(batch)
        self.schedules.sort(key=lambda s: s.get('score', 0))

        if self.current_schedule_idx == 0 and (old_top != self.schedules[0] or len(self.schedules) == len(batch)):
            self.draw_schedule_index(0)

        self.schedule_counter_label.set_text(f"Schedule {self.current_schedule_idx + 1} of {len(self.schedules)}")
        self._update_navigation_buttons()

    def _on_generation_complete(self, ret_code, stderr):
        if ret_code != 0:
            self.show_error_dialog(f"Error running scheduler: {stderr}")
            self.schedule_status.set_title("Generation Failed")
            self.schedule_status.set_description("An error occurred during calculation.")
            self.schedule_status.set_icon_name("dialog-error-symbolic")
            self.schedule_counter_label.set_text("Failed")
            return

        if not self.schedules:
            self.draw_schedule_index(0)
        else:
            self.draw_schedule_index(self.current_schedule_idx)
            self.show_toast(f"Found {len(self.schedules)} conflict-free schedule(s)")

        self.generation_process = None

    def _clear_schedule_grid(self):
        child = self.schedule.get_first_child()
        while child:
            self.schedule.remove(child)
            child = self.schedule.get_first_child()

    def draw_schedule_index(self, index):
        self._clear_schedule_grid()
        # Update Favorite Button Icon
        if index in self.favorites:
            self.fav_btn.set_icon_name("starred-symbolic")
            self.fav_btn.set_tooltip_text("Unfavorite Schedule")
        else:
            self.fav_btn.set_icon_name("non-starred-symbolic")
            self.fav_btn.set_tooltip_text("Favorite Schedule")

        if not self.schedules or index >= len(self.schedules):
            self.schedule.set_visible(False)
            self.schedule_status.set_visible(True)
            self.schedule_status.set_icon_name("system-search-symbolic")
            self.schedule_counter_label.set_text("No Results")
            self.stats_btn.set_sensitive(False)
            self.stats_summary_label.set_text("")
            self._update_navigation_buttons()

            # Run Conflict & Constraint Diagnostic Engine
            issues, suggestions = self._diagnose_constraints()
            self.schedule_status.set_title("No Schedules Found")

            desc_lines = ["<b>Constraint Bottlenecks Detected:</b>"]
            for issue in issues[:3]:  # Display top 3 issues
                desc_lines.append(f"• {issue}")

            if suggestions:
                desc_lines.append("\n<b>Suggestions:</b>")
                for sugg in suggestions[:2]:
                    desc_lines.append(f"→ {sugg}")

            self.schedule_status.set_description("\n".join(desc_lines))
            return

        self.schedule_status.set_visible(False)
        self.schedule.set_visible(True)
        self.schedule_counter_label.set_text(f"Schedule {index + 1} of {len(self.schedules)}")

        schedule_data = self.schedules[index]

        stats = self._compute_schedule_stats(schedule_data)
        if stats:
            self.stats_btn.set_sensitive(True)
            self.stats_summary_label.set_text(f"{stats['num_days']} Days | {self._format_duration(stats['total_gap_minutes'])}")
            self._update_stats_popover(stats)
        else:
            self.stats_btn.set_sensitive(False)
            self.stats_summary_label.set_text("")

        self.schedule.set_row_spacing(0)
        self.schedule.set_column_spacing(10)
        self.schedule.set_valign(Gtk.Align.START)
        self.schedule.set_hexpand(True)
        self.schedule.set_halign(Gtk.Align.FILL)

        # Time markers (8:30 to 20:30)
        for i in range(13):
            hour = 8 + i
            label = Gtk.Label(label=f"{hour:02d}:30")
            label.add_css_class("dim-label")
            label.set_halign(Gtk.Align.END)
            label.set_valign(Gtk.Align.START)
            label.set_margin_end(6)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_valign(Gtk.Align.START)
            box.set_size_request(55, 1 if i == 12 else 60)
            box.append(label)
            self.schedule.attach(box, 0, i + 1, 1, 1)

        # Days columns
        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        day_overlays = {}

        for col_idx, day in enumerate(days, start=1):
            day_label = Gtk.Label(label=f"<b>{day}</b>", use_markup=True)
            day_label.set_margin_bottom(8)
            day_label.set_halign(Gtk.Align.CENTER)
            self.schedule.attach(day_label, col_idx, 0, 1, 1)

            overlay = Gtk.Overlay()
            dummy = Gtk.Box()
            dummy.set_size_request(120, 12 * 60)
            overlay.set_child(dummy)
            overlay.set_hexpand(True)
            overlay.set_halign(Gtk.Align.FILL)
            overlay.set_valign(Gtk.Align.START)

            self.schedule.attach(overlay, col_idx, 1, 1, 12)
            day_overlays[col_idx] = overlay

        START_MINUTES = 8 * 60 + 30
        PX_PER_MINUTE = 1.0

        unique_courses = sorted(list({m['course'] for m in schedule_data.get("meetings", [])}))
        course_color_idx_map = {c: i % len(COURSE_COLORS) for i, c in enumerate(unique_courses)}

        for meeting in schedule_data.get("meetings", []):
            if meeting["day"] == 0 or meeting["start"] < 0 or meeting["end"] < 0:
                continue

            day_idx = meeting["day"]
            if day_idx not in day_overlays:
                continue

            overlay = day_overlays[day_idx]
            start_y = int((meeting["start"] - START_MINUTES) * PX_PER_MINUTE)
            height = int((meeting["end"] - meeting["start"]) * PX_PER_MINUTE)

            if start_y < 0:
                height += start_y
                start_y = 0
            if height <= 0:
                continue

            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            card.add_css_class("card")
            color_idx = course_color_idx_map.get(meeting['course'], 0)
            card.add_css_class(f"course-color-{color_idx}")

            card.set_size_request(-1, height)
            card.set_halign(Gtk.Align.FILL)
            card.set_valign(Gtk.Align.START)
            card.set_margin_top(start_y)

            full_title = meeting['course']
            course_data = self.data.get(meeting['course'], [])
            if course_data:
                full_title = course_data[0].get("fullTitle", meeting['course'])

            card.set_tooltip_text(
                f"{full_title} ({meeting['id']})\n"
                f"Type: {meeting['type']}\n"
                f"Time: {meeting['start']//60:02d}:{meeting['start']%60:02d} - {meeting['end']//60:02d}:{meeting['end']%60:02d}\n"
                f"Instructor: {meeting['instructor']}\n"
                f"Location: {meeting['location']}\n"
                f"Seats: {meeting['seats']}"
            )

            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            inner.set_margin_top(4)
            inner.set_margin_bottom(4)
            inner.set_margin_start(6)
            inner.set_margin_end(6)
            card.append(inner)

            title = Gtk.Label(label=f"<b>{meeting['course']}</b>", use_markup=True, halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
            title.add_css_class("caption")
            inner.append(title)

            if height >= 40:
                sub = Gtk.Label(label=f"{meeting['type']} ({meeting['id']})", halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
                sub.add_css_class("dim-label")
                sub.add_css_class("caption")
                inner.append(sub)

            if height >= 65:
                loc = meeting['location'].split(',')[-1].strip() if ',' in meeting['location'] else meeting['location']
                loc_lbl = Gtk.Label(label=loc, halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
                loc_lbl.add_css_class("caption")
                inner.append(loc_lbl)

            overlay.add_overlay(card)

        self._update_navigation_buttons()

    # =========================================================================
    # CONFLICT & CONSTRAINT DIAGNOSTICS
    # =========================================================================

    def _parse_single_time_str(self, t_str):
        if not t_str or ":" not in t_str:
            return -1
        cleaned = t_str.upper().strip()
        has_pm = "PM" in cleaned
        has_am = "AM" in cleaned
        cleaned = cleaned.replace("AM", "").replace("PM", "").strip()
        try:
            h, m = map(int, cleaned.split(":"))
            if has_pm and h != 12: h += 12
            if has_am and h == 12: h = 0
            return h * 60 + m
        except Exception:
            return -1

    def _parse_time_range_str(self, time_str):
        if not time_str or "-" not in time_str:
            return -1, -1
        parts = time_str.split("-")
        return self._parse_single_time_str(parts[0]), self._parse_single_time_str(parts[1])

    def _get_course_packs(self, course_code):
        sections_list = self.data.get(course_code, [])
        if not sections_list:
            return []

        day_map = {"SUNDAY": 1, "MONDAY": 2, "TUESDAY": 3, "WEDNESDAY": 4, "THURSDAY": 5, "FRIDAY": 6, "SATURDAY": 7}
        lectures = {}
        labs = {}
        tutorials = {}

        for sec in sections_list:
            subtype = sec.get("subtype", "Lecture")
            sec_id = sec.get("section", "")
            inst = sec.get("instructor", "Not Assigned")
            seats = -1
            try:
                seats = int(sec.get("seatsLeft", -1))
            except (ValueError, TypeError):
                pass

            meetings = []
            schedules = sec.get("schedules", [])
            if schedules and isinstance(schedules, list):
                for s in schedules:
                    d_int = day_map.get(s.get("day", "").upper().strip(), 0)
                    s_min, e_min = self._parse_time_range_str(s.get("time", ""))
                    meetings.append({
                        "course": course_code, "type": subtype, "id": sec_id,
                        "day": d_int, "start": s_min, "end": e_min,
                        "instructor": inst, "seats": seats
                    })
            else:
                sched_str = sec.get("schedule", "")
                if "," in sched_str:
                    d_str, t_str = sched_str.split(",", 1)
                    d_int = day_map.get(d_str.upper().strip(), 0)
                    s_min, e_min = self._parse_time_range_str(t_str.strip())
                else:
                    d_int, s_min, e_min = 0, -1, -1

                meetings.append({
                    "course": course_code, "type": subtype, "id": sec_id,
                    "day": d_int, "start": s_min, "end": e_min,
                    "instructor": inst, "seats": seats
                })

            if subtype == "Lecture":
                lectures[sec_id] = meetings
            elif subtype == "Lab":
                p_match = re.match(r'^\d+', sec_id)
                p_key = p_match.group(0) if p_match else sec_id
                labs.setdefault(p_key, []).append(meetings)
            elif subtype == "Tutorial":
                p_match = re.match(r'^\d+', sec_id)
                p_key = p_match.group(0) if p_match else sec_id
                tutorials.setdefault(p_key, []).append(meetings)

        packs = []
        for lec_id, lec_meetings in lectures.items():
            avail_labs = labs.get(lec_id, [[]])
            avail_tuts = tutorials.get(lec_id, [[]])
            for lab_m in avail_labs:
                for tut_m in avail_tuts:
                    packs.append(list(lec_meetings) + list(lab_m) + list(tut_m))

        return packs

    def _packs_have_conflict(self, pack1, pack2):
        for m1 in pack1:
            for m2 in pack2:
                if m1.get("day", 0) > 0 and m1.get("day") == m2.get("day"):
                    if not (m1.get("end", 0) <= m2.get("start", 0) or m2.get("end", 0) <= m1.get("start", 0)):
                        return True, m1
        return False, None

    def _all_packs_conflict(self, packs1, packs2):
        sample_conflict = None
        for p1 in packs1:
            for p2 in packs2:
                has_conf, m = self._packs_have_conflict(p1, p2)
                if not has_conf:
                    return False, None
                if not sample_conflict and m:
                    sample_conflict = m
        return True, sample_conflict

    # =========================================================================
    # ADVANCED CONSTRAINT & SENSITIVITY DIAGNOSTIC ENGINE
    # =========================================================================

    def _find_one_valid_combination(self, packs_by_course_list):
        """Ultra-fast mini-backtracker (0.05ms) to test if a combination is possible."""
        num_courses = len(packs_by_course_list)
        if num_courses == 0:
            return True

        # Sort courses by fewest available options first (MRV heuristic for instant pruning)
        sorted_courses = sorted(packs_by_course_list, key=lambda packs: len(packs))
        if any(len(packs) == 0 for packs in sorted_courses):
            return False

        def backtrack_check(course_idx, chosen_meetings):
            if course_idx == num_courses:
                return True

            for pack in sorted_courses[course_idx]:
                has_conflict = False
                for m_new in pack:
                    if m_new.get("day", 0) == 0 or m_new.get("start", -1) < 0:
                        continue
                    for m_old in chosen_meetings:
                        if m_old.get("day", 0) > 0 and m_new.get("day") == m_old.get("day"):
                            if not (m_new.get("end", 0) <= m_old.get("start", 0) or m_old.get("end", 0) <= m_new.get("start", 0)):
                                has_conflict = True
                                break
                    if has_conflict:
                        break

                if not has_conflict:
                    chosen_meetings.extend(pack)
                    if backtrack_check(course_idx + 1, chosen_meetings):
                        return True
                    del chosen_meetings[-len(pack):]

            return False

        return backtrack_check(0, [])

    def _filter_packs(self, course_code, raw_packs, ignore_prefs=False, ignore_time=False, ignore_gap=False, ignore_days=False, ignore_full=False):
        excluded_days = set()
        if not ignore_days:
            if self.checksun.get_active(): excluded_days.add(1)
            if self.checkmon.get_active(): excluded_days.add(2)
            if self.checktue.get_active(): excluded_days.add(3)
            if self.checkwed.get_active(): excluded_days.add(4)
            if self.checkthu.get_active(): excluded_days.add(5)
            if self.checkfri.get_active(): excluded_days.add(6)
            if self.checksat.get_active(): excluded_days.add(7)

        time_enabled = self.time.get_enable_expansion() and not ignore_time
        min_start = self.start_hours.get_value_as_int() * 60 + self.start_minutes.get_value_as_int() if time_enabled else 0
        max_end = self.end_hours.get_value_as_int() * 60 + self.end_minutes.get_value_as_int() if time_enabled else 24 * 60

        gap_enabled = self.gap_time.get_enable_expansion() and not ignore_gap
        gap_start = self.gap_start_hours.get_value_as_int() * 60 + self.gap_start_minutes.get_value_as_int() if gap_enabled else -1
        gap_end = self.gap_end_hours.get_value_as_int() * 60 + self.gap_end_minutes.get_value_as_int() if gap_enabled else -1
        gap_day = self.gap_day.get_selected() if gap_enabled else 0

        exclude_full = self.ls_switch.get_active() and not ignore_full

        pref = self.course_preferences.get(course_code, {})
        pref_type = pref.get("type", "Neither")
        pref_val = pref.get("value", [])
        if isinstance(pref_val, str) and pref_val:
            pref_val = [pref_val]

        valid_packs = []
        for pack in raw_packs:
            # Check Preferences
            if not ignore_prefs:
                if pref_type == "Instructor" and pref_val:
                    if not any(any(p_inst.lower() in m.get("instructor", "").lower() for p_inst in pref_val) for m in pack):
                        continue
                elif pref_type == "Section" and pref_val:
                    if not any(m.get("type") == "Lecture" and m.get("id") in pref_val for m in pack):
                        continue

            # Check Full
            if exclude_full and any(m.get("seats", -1) == 0 for m in pack):
                continue
            # Check Excluded Days
            if any(m.get("day", 0) in excluded_days for m in pack):
                continue
            # Check Time
            if time_enabled and any(m.get("start", -1) < min_start or m.get("end", -1) > max_end for m in pack if m.get("day", 0) > 0):
                continue
            # Check Gap
            if gap_enabled and gap_start != -1 and gap_end != -1:
                if any(m.get("day", 0) > 0 and (gap_day == 0 or m.get("day") == gap_day) and (m.get("start", -1) < gap_end and m.get("end", -1) > gap_start) for m in pack):
                    continue

            valid_packs.append(pack)

        return valid_packs

    def _get_pref_description(self, course_code):
        pref = self.course_preferences.get(course_code, {})
        ptype = pref.get("type", "Neither")
        pval = pref.get("value", "")
        if ptype == "Instructor" and pval:
            if isinstance(pval, list): return f"Instructor: {', '.join(pval)}"
            return f"Instructor: {pval}"
        elif ptype == "Section" and pval:
            return f"Section {pval}"
        return "Any"

    def _find_pref_blocker_reason(self, course_code, raw_packs):
        """Identifies which active global constraint eliminated the user's preferred section/instructor."""
        pref_packs = self._filter_packs(
            course_code, raw_packs, ignore_prefs=False,
            ignore_time=True, ignore_gap=True, ignore_days=True, ignore_full=True
        )
        if not pref_packs:
            return "is not available in the database", None

        # 1. Did Gap eliminate the preference?
        if self.gap_time.get_enable_expansion():
            if not self._filter_packs(course_code, pref_packs, ignore_prefs=False, ignore_gap=False):
                g_str = f"{self.gap_start_hours.get_value_as_int():02d}:{self.gap_start_minutes.get_value_as_int():02d}–{self.gap_end_hours.get_value_as_int():02d}:{self.gap_end_minutes.get_value_as_int():02d}"
                return f"collides with your Specified Gap (<b>{g_str}</b>)", ("gap", g_str)

        # 2. Did Time Boundary eliminate the preference?
        if self.time.get_enable_expansion():
            if not self._filter_packs(course_code, pref_packs, ignore_prefs=False, ignore_time=False):
                t_str = f"{self.start_hours.get_value_as_int():02d}:{self.start_minutes.get_value_as_int():02d}–{self.end_hours.get_value_as_int():02d}:{self.end_minutes.get_value_as_int():02d}"
                return f"falls outside your Time Boundary (<b>{t_str}</b>)", ("time", t_str)

        # 3. Did Excluded Days eliminate the preference?
        excluded_days = set()
        if self.checksun.get_active(): excluded_days.add(1)
        if self.checkmon.get_active(): excluded_days.add(2)
        if self.checktue.get_active(): excluded_days.add(3)
        if self.checkwed.get_active(): excluded_days.add(4)
        if self.checkthu.get_active(): excluded_days.add(5)
        if self.checkfri.get_active(): excluded_days.add(6)
        if self.checksat.get_active(): excluded_days.add(7)
        if excluded_days:
            day_names = {1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday", 5: "Thursday", 6: "Friday", 7: "Saturday"}
            if not self._filter_packs(course_code, pref_packs, ignore_prefs=False, ignore_days=False):
                days_hit = {day_names.get(m["day"]) for pack in pref_packs for m in pack if m.get("day", 0) in excluded_days}
                d_str = ", ".join(filter(None, days_hit))
                return f"requires attending on an Excluded Day (<b>{d_str}</b>)", ("day", d_str)

        # 4. Did Full Classes eliminate the preference?
        if self.ls_switch.get_active():
            if not self._filter_packs(course_code, pref_packs, ignore_prefs=False, ignore_full=False):
                return "is completely full (0 seats remaining)", ("full", "")

        return "violates active constraints", None

    def _diagnose_constraints(self):
        """Prioritized diagnostic engine using 'Unlock' terminology matching the Compare dialog."""
        issues = []
        suggestions_dict = {}
        selected_list = sorted(list(self.selected_courses))
        if not selected_list:
            return issues, []

        day_names = {1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday", 5: "Thursday", 6: "Friday", 7: "Saturday"}

        time_enabled = self.time.get_enable_expansion()
        gap_enabled = self.gap_time.get_enable_expansion()
        exclude_full = self.ls_switch.get_active()

        excluded_days = set()
        if self.checksun.get_active(): excluded_days.add(1)
        if self.checkmon.get_active(): excluded_days.add(2)
        if self.checktue.get_active(): excluded_days.add(3)
        if self.checkwed.get_active(): excluded_days.add(4)
        if self.checkthu.get_active(): excluded_days.add(5)
        if self.checkfri.get_active(): excluded_days.add(6)
        if self.checksat.get_active(): excluded_days.add(7)
        has_excluded_days = len(excluded_days) > 0

        # Collect raw and filtered packs
        raw_packs_by_course = {c: self._get_course_packs(c) for c in selected_list}
        unfiltered_packs = {c: self._filter_packs(c, raw_packs_by_course[c], ignore_prefs=True) for c in selected_list}
        filtered_packs = {c: self._filter_packs(c, raw_packs_by_course[c], ignore_prefs=False) for c in selected_list}

        # ---------------------------------------------------------------------
        # PHASE 1: Hard Showstoppers (Courses with 0 sections globally)
        # ---------------------------------------------------------------------
        time_blocked = []
        gap_blocked = []
        day_blocked = {}
        full_blocked = []

        for c in selected_list:
            raw_p = raw_packs_by_course[c]
            glob_p = unfiltered_packs[c]

            if not raw_p:
                issues.append(f"<b>{c}</b>: No class sections found in database.")
                continue

            if not glob_p:
                if time_enabled and self._filter_packs(c, raw_p, ignore_prefs=True, ignore_time=True):
                    time_blocked.append(c)
                elif gap_enabled and self._filter_packs(c, raw_p, ignore_prefs=True, ignore_gap=True):
                    gap_blocked.append(c)
                elif has_excluded_days and self._filter_packs(c, raw_p, ignore_prefs=True, ignore_days=True):
                    days_hit = {day_names.get(m["day"]) for pack in raw_p for m in pack if m.get("day", 0) in excluded_days}
                    d_str = ", ".join(filter(None, days_hit))
                    day_blocked.setdefault(d_str, []).append(c)
                elif exclude_full and self._filter_packs(c, raw_p, ignore_prefs=True, ignore_full=True):
                    full_blocked.append(c)
                else:
                    issues.append(f"<b>{c}</b>: All sections violate active time, day, or capacity constraints.")

        if time_blocked or gap_blocked or day_blocked or full_blocked:
            if time_blocked:
                c_str = ", ".join(f"<b>{c}</b>" for c in time_blocked)
                t_str = f"{self.start_hours.get_value_as_int():02d}:{self.start_minutes.get_value_as_int():02d}–{self.end_hours.get_value_as_int():02d}:{self.end_minutes.get_value_as_int():02d}"
                issues.append(f"<b>Time Boundary ({t_str}):</b> All sections of {c_str} fall outside allowed hours.")
                suggestions_dict["time"] = f"Widen or disable your Start / End time boundary ({t_str})."

            if gap_blocked and gap_enabled:
                c_str = ", ".join(f"<b>{c}</b>" for c in gap_blocked)
                g_str = f"{self.gap_start_hours.get_value_as_int():02d}:{self.gap_start_minutes.get_value_as_int():02d}–{self.gap_end_hours.get_value_as_int():02d}:{self.gap_end_minutes.get_value_as_int():02d}"
                issues.append(f"<b>Specified Gap ({g_str}):</b> All sections of {c_str} collide with your gap window.")
                suggestions_dict["gap"] = f"Adjust or disable your specified gap ({g_str})."

            for d_str, courses in day_blocked.items():
                c_str = ", ".join(f"<b>{c}</b>" for c in courses)
                issues.append(f"<b>Excluded Day ({d_str}):</b> Every section of {c_str} requires attending on {d_str}.")
                suggestions_dict[f"day_{d_str}"] = f"Un-exclude {d_str} in Constraints."

            if full_blocked:
                c_str = ", ".join(f"<b>{c}</b>" for c in full_blocked)
                issues.append(f"<b>Full Classes:</b> All sections of {c_str} have 0 seats remaining.")
                suggestions_dict["full"] = "Turn off 'Exclude Full Classes'."

            return issues, list(suggestions_dict.values())

        # ---------------------------------------------------------------------
        # PHASE 2: Single-Course Preference Elimination
        # ---------------------------------------------------------------------
        pref_self_blocked = []
        for c in selected_list:
            glob_p = unfiltered_packs[c]
            filt_p = filtered_packs[c]
            if not filt_p and glob_p:
                pref_self_blocked.append((c, self._get_pref_description(c), len(glob_p)))

        if pref_self_blocked:
            for c, p_desc, alt_count in pref_self_blocked:
                reason_text, blocker_tuple = self._find_pref_blocker_reason(c, raw_packs_by_course[c])
                issues.append(f"<b>Filter Conflict on {c}:</b> Selected <i>{p_desc}</i> {reason_text}. <b>{alt_count}</b> other section(s) exist if unlocked.")

                if blocker_tuple:
                    b_type, b_val = blocker_tuple
                    if b_type == "gap":
                        suggestions_dict["gap"] = f"Adjust or disable your specified gap ({b_val}) to allow {p_desc}."
                    elif b_type == "time":
                        suggestions_dict["time"] = f"Widen or disable your Time Boundary ({b_val}) to allow {p_desc}."
                    elif b_type == "day":
                        suggestions_dict[f"day_{b_val}"] = f"Un-exclude {b_val} to allow {p_desc}."
                    elif b_type == "full":
                        suggestions_dict["full"] = f"Turn off 'Exclude Full Classes' to allow {p_desc}."

                suggestions_dict[f"pref_{c}"] = f"Or unlock {c} to use an alternative section."

            return issues, list(suggestions_dict.values())

        # ---------------------------------------------------------------------
        # PHASE 3: Sensitivity Analysis (Multi-Course Combinations)
        # ---------------------------------------------------------------------
        can_fit_all_any = self._find_one_valid_combination([unfiltered_packs[c] for c in selected_list])

        if can_fit_all_any:
            filtered_courses = [c for c in selected_list if self.course_preferences.get(c, {}).get("type") != "Neither"]
            culprit_found = False

            for c_test in filtered_courses:
                test_set = [unfiltered_packs[c] if c == c_test else filtered_packs[c] for c in selected_list]
                if self._find_one_valid_combination(test_set):
                    p_desc = self._get_pref_description(c_test)
                    issues.append(f"<b>Filter Bottleneck on {c_test}:</b> Filter (<i>{p_desc}</i>) blocks all combinations with other courses. Unlocking <b>{c_test}</b> yields valid schedules.")
                    suggestions_dict[f"pref_{c_test}"] = f"Unlock {c_test} (allow any section/instructor)."
                    culprit_found = True

            if not culprit_found and len(filtered_courses) >= 2:
                for i in range(len(filtered_courses)):
                    for j in range(i + 1, len(filtered_courses)):
                        c1, c2 = filtered_courses[i], filtered_courses[j]
                        test_set = [unfiltered_packs[c] if c in (c1, c2) else filtered_packs[c] for c in selected_list]
                        if self._find_one_valid_combination(test_set):
                            p1_desc = self._get_pref_description(c1)
                            p2_desc = self._get_pref_description(c2)
                            issues.append(f"<b>Combined Filter Conflict:</b> Filters on <b>{c1}</b> (<i>{p1_desc}</i>) and <b>{c2}</b> (<i>{p2_desc}</i>) prevent fitting all courses together.")
                            suggestions_dict[f"pref_{c1}_{c2}"] = f"Unlock {c1} or {c2} (allow any section/instructor)."
                            culprit_found = True
                            break
                    if culprit_found: break

            if not culprit_found:
                issues.append(f"<b>Course Filters:</b> Locked sections/instructors across multiple courses leave no open slots for all {len(selected_list)} courses.")
                suggestions_dict["reset_all_prefs"] = "Unlock course filters to allow flexible combinations."

        else:
            if time_enabled:
                no_time_packs = [self._filter_packs(c, raw_packs_by_course[c], ignore_prefs=True, ignore_time=True) for c in selected_list]
                if self._find_one_valid_combination(no_time_packs):
                    t_str = f"{self.start_hours.get_value_as_int():02d}:{self.start_minutes.get_value_as_int():02d}–{self.end_hours.get_value_as_int():02d}:{self.end_minutes.get_value_as_int():02d}"
                    issues.append(f"<b>Time Boundary Too Strict ({t_str}):</b> Allowed hours cannot accommodate all {len(selected_list)} courses.")
                    suggestions_dict["time"] = f"Widen or disable your Start / End time boundary ({t_str})."

            if gap_enabled:
                no_gap_packs = [self._filter_packs(c, raw_packs_by_course[c], ignore_prefs=True, ignore_gap=True) for c in selected_list]
                if self._find_one_valid_combination(no_gap_packs):
                    g_str = f"{self.gap_start_hours.get_value_as_int():02d}:{self.gap_start_minutes.get_value_as_int():02d}–{self.gap_end_hours.get_value_as_int():02d}:{self.gap_end_minutes.get_value_as_int():02d}"
                    issues.append(f"<b>Gap Constraint Conflict ({g_str}):</b> Specified gap leaves too little remaining time for all courses.")
                    suggestions_dict["gap"] = f"Adjust or disable your specified gap ({g_str})."

            if has_excluded_days:
                no_days_packs = [self._filter_packs(c, raw_packs_by_course[c], ignore_prefs=True, ignore_days=True) for c in selected_list]
                if self._find_one_valid_combination(no_days_packs):
                    issues.append(f"<b>Too Many Excluded Days:</b> Excluded days leave too few available days for all courses.")
                    suggestions_dict["days"] = "Allow classes on one or more excluded days."

            if not issues:
                issues.append(f"<b>Schedule Overlap:</b> No conflict-free combination exists containing all <b>{len(selected_list)}</b> selected courses.")
                suggestions_dict["remove_course"] = "Try deselecting 1 course or loosening time constraints."

        return issues, list(suggestions_dict.values())

    def _update_navigation_buttons(self):
        total = len(self.schedules)
        has_schedules = total > 0

        self.fav_btn.set_sensitive(has_schedules)
        self.copy_btn.set_sensitive(has_schedules)
        self.compare_btn.set_sensitive(has_schedules)
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
            self.fav_btn.set_icon_name("non-starred-symbolic")
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
        if not self.schedules or self.current_schedule_idx >= len(self.schedules):
            return

        sched = self.schedules[self.current_schedule_idx]
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

    def on_compare_clicked(self, _button):
        if not self.schedules or self.current_schedule_idx >= len(self.schedules):
            return

        current_sched = self.schedules[self.current_schedule_idx]
        current_courses = {}
        for m in current_sched.get('meetings', []):
            c = m['course']
            if c not in current_courses:
                current_courses[c] = set()
            current_courses[c].add(m['id'])

        dialog = Adw.Dialog(title="Compare & Reschedule")
        dialog.set_content_width(450)
        dialog.set_content_height(500)

        toolbar = Adw.ToolbarView()
        dialog.set_child(toolbar)
        toolbar.add_top_bar(Adw.HeaderBar())

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(18)
        vbox.set_margin_start(18)
        vbox.set_margin_end(18)
        toolbar.set_content(vbox)

        search_entry = Gtk.SearchEntry(placeholder_text="Filter courses...")
        vbox.append(search_entry)

        list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(list_box)
        vbox.append(scrolled)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True, margin_top=8)
        vbox.append(btn_box)

        cancel_btn = Gtk.Button(label="Cancel", css_classes=["pill"])
        generate_btn = Gtk.Button(label="Generate", css_classes=["suggested-action", "pill"])
        btn_box.append(cancel_btn)
        btn_box.append(generate_btn)

        widgets_dict = {}
        rows = []

        for course_code in sorted(self.data.keys(), key=lambda c: (c not in current_courses, c)):
            row = Adw.ActionRow(title=course_code)
            suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)

            lock_btn = Gtk.ToggleButton(valign=Gtk.Align.CENTER, css_classes=["flat"])
            def update_lock(btn, *args):
                btn.set_icon_name("changes-prevent-symbolic" if btn.get_active() else "changes-allow-symbolic")
                btn.set_tooltip_text("Locked: Keep exact section" if btn.get_active() else "Unlocked: Any section")
            update_lock(lock_btn)
            lock_btn.connect("notify::active", update_lock)

            checkbox = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            row.checkbox = checkbox

            suffix_box.append(lock_btn)
            suffix_box.append(checkbox)
            row.add_suffix(suffix_box)
            row.set_activatable_widget(checkbox)

            is_current = course_code in current_courses
            checkbox.set_active(is_current)
            lock_btn.set_active(is_current)
            lock_btn.set_visible(is_current)

            def on_cb_toggled(cb, *_, btn=lock_btn, curr=is_current):
                btn.set_visible(cb.get_active() if curr else False)

            checkbox.connect("notify::active", on_cb_toggled)

            list_box.append(row)
            widgets_dict[course_code] = {"checkbox": checkbox, "lock_btn": lock_btn}
            rows.append((row, course_code))

        search_entry.connect("search-changed", lambda entry: [
            r.set_visible(not entry.get_text() or entry.get_text().lower() in c.lower()) for r, c in rows
        ])

        cancel_btn.connect("clicked", lambda *_: dialog.close())
        def on_gen(*_):
            dialog.close()
            self._execute_compare_generation(widgets_dict, current_courses)
        generate_btn.connect("clicked", on_gen)

        dialog.present(self)

    def _execute_compare_generation(self, widgets_dict, current_courses):
        temp_selected = set()
        temp_section_locks = {}

        for course, widgets in widgets_dict.items():
            if widgets["checkbox"].get_active():
                temp_selected.add(course)
                if course in current_courses and widgets["lock_btn"].get_active():
                    temp_section_locks[course] = current_courses[course]

        if not temp_selected:
            self.show_error_dialog("Please select at least one course.")
            return

        scheduler_path = shutil.which('scheduler')
        if not scheduler_path:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            exe_name = 'scheduler.exe' if os.name == 'nt' else 'scheduler'
            scheduler_path = os.path.join(project_root, 'build', 'c++', exe_name)

        cmd = [scheduler_path, '--json-file', self.json_path, '--courses', ",".join(temp_selected)]
        pref_secs = [f"{c}:{sec}" for c, secs in temp_section_locks.items() for sec in secs]
        if pref_secs: cmd.extend(['--specific-sections', "|".join(pref_secs)])

        excluded_days = []
        if self.checksun.get_active(): excluded_days.append("1")
        if self.checkmon.get_active(): excluded_days.append("2")
        if self.checktue.get_active(): excluded_days.append("3")
        if self.checkwed.get_active(): excluded_days.append("4")
        if self.checkthu.get_active(): excluded_days.append("5")
        if self.checkfri.get_active(): excluded_days.append("6")
        if self.checksat.get_active(): excluded_days.append("7")
        if excluded_days: cmd.extend(['--exclude-days', ",".join(excluded_days)])

        if self.time.get_enable_expansion():
            cmd.extend([
                '--start-time', f"{self.start_hours.get_value_as_int():02d}:{self.start_minutes.get_value_as_int():02d}",
                '--end-time', f"{self.end_hours.get_value_as_int():02d}:{self.end_minutes.get_value_as_int():02d}"
            ])

        if self.ls_switch.get_active(): cmd.extend(['--exclude-full', 'true'])
        opt_map = {0: "compact", 1: "few-days", 2: "balanced-days", 3: "consistent-times"}
        cmd.extend(['--optimize-by', opt_map.get(self.tuner.get_selected(), "compact")])

        self.start_scheduler_thread(cmd)

    def on_import_clicked(self, _button):
        dialog = Adw.Dialog(title="Import Schedule")
        dialog.set_content_width(450)
        dialog.set_content_height(380)

        toolbar = Adw.ToolbarView()
        dialog.set_child(toolbar)
        toolbar.add_top_bar(Adw.HeaderBar())

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)
        toolbar.set_content(vbox)

        vbox.append(Gtk.Label(label="Paste your exported schedule text below:", halign=Gtk.Align.START))
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        textview = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, css_classes=["card"])
        scrolled.set_child(textview)
        vbox.append(scrolled)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True, margin_top=8)
        vbox.append(btn_box)

        cancel_btn = Gtk.Button(label="Cancel", css_classes=["pill"])
        import_action_btn = Gtk.Button(label="Import", css_classes=["suggested-action", "pill"])
        btn_box.append(cancel_btn)
        btn_box.append(import_action_btn)

        cancel_btn.connect("clicked", lambda *_: dialog.close())
        def on_imp(*_):
            buf = textview.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            if self._parse_and_import_schedule(text):
                dialog.close()
        import_action_btn.connect("clicked", on_imp)

        dialog.present(self)

    def _parse_and_import_schedule(self, text):
        new_selected = set()
        new_prefs = {}

        for line in text.strip().split("\n"):
            if "|" not in line: continue
            tokens = line.split("|", 1)[0].strip().split()
            if not tokens: continue
            course = tokens[0]
            new_selected.add(course)
            if len(tokens) > 2 and tokens[1] == "Lecture":
                new_prefs[course] = {"type": "Section", "value": tokens[2]}

        if not new_selected:
            self.show_error_dialog("Could not parse any valid courses from text.")
            return False

        self.selected_courses = new_selected
        self.course_preferences = new_prefs
        self._save_courses_and_preferences()
        self.on_generate_clicked(None)
        self.populate_listbox()
        self._update_courses_counter()
        self.show_toast("Schedule imported successfully")
        return True

    def on_key_pressed(self, controller, keyval, keycode, state):
        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_g, Gdk.KEY_G):
                self.on_generate_clicked(None)
                return True
            elif keyval in (Gdk.KEY_c, Gdk.KEY_C) and self.schedules:
                self.on_copy_schedule_clicked(self.copy_btn)
                return True
            elif keyval in (Gdk.KEY_s, Gdk.KEY_S):
                self.show_sidebar_btn.set_active(not self.show_sidebar_btn.get_active())
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
                with open(file.get_path(), 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                self.json_path = file.get_path()
                self.populate_listbox()
                self.show_toast("Loaded local database")
        except GLib.Error as e:
            print(f"File open error: {e.message}")

    def on_close_request(self, *args):
        if hasattr(self, 'generation_process') and self.generation_process:
            try: self.generation_process.terminate()
            except Exception: pass
        self._save_courses_and_preferences()
        return False

    def _on_delete_save_clicked(self, _button):
        for key in self.settings.list_keys():
            self.settings.reset(key)

        self.selected_courses.clear()
        self.course_preferences.clear()
        self._save_courses_and_preferences()
        self.schedules = []
        self.current_schedule_idx = 0
        self.favorites.clear()
        self.fav_btn.set_sensitive(False)
        self.fav_btn.set_icon_name("non-starred-symbolic")

        self.populate_listbox()
        self._clear_schedule_grid()
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

