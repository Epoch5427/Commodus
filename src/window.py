from gi.repository import Adw, Gtk, Gio, GLib, Gdk, Pango, GObject
import json
import re
import subprocess
import os
import shutil
import urllib.request
import threading
import time

@Gtk.Template(resource_path='/io/github/Epoch5427/Commodus/window.ui')
class CommodusWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'CommodusWindow'

    root_box = Gtk.Template.Child()
    carousel = Gtk.Template.Child()
    show_sidebar_button = Gtk.Template.Child()
    back_button = Gtk.Template.Child()
    network_banner = Gtk.Template.Child()
    split_view = Gtk.Template.Child()
    search_toggle = Gtk.Template.Child()
    ls_switch = Gtk.Template.Child()
    constraints = Gtk.Template.Child()
    revealer_slide = Gtk.Template.Child()
    searchbar = Gtk.Template.Child()
    searchentry = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    courses_page = Gtk.Template.Child()
    main_page = Gtk.Template.Child()
    search_page = Gtk.Template.Child()
    status_page = Gtk.Template.Child()
    listbox = Gtk.Template.Child()
    filters_page = Gtk.Template.Child()
    numcourses = Gtk.Template.Child()
    data_page = Gtk.Template.Child()

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

    prefs_dialog = Gtk.Template.Child()
    dm_switch = Gtk.Template.Child()
    wrap_switch = Gtk.Template.Child()
    delete_save = Gtk.Template.Child()
    local_load_switch = Gtk.Template.Child()
    fpickerbutton = Gtk.Template.Child()
    generate = Gtk.Template.Child()
    action_bar = Gtk.Template.Child()
    clear_sec = Gtk.Template.Child()
    tuning_page = Gtk.Template.Child()
    tuner = Gtk.Template.Child()
    sec_tuner = Gtk.Template.Child()

    major_combo = Gtk.Template.Child()
    semester_combo = Gtk.Template.Child()

    checksun = Gtk.Template.Child()
    checkmon = Gtk.Template.Child()
    checktue = Gtk.Template.Child()
    checkwed = Gtk.Template.Child()
    checkthu = Gtk.Template.Child()
    checkfri = Gtk.Template.Child()
    checksat = Gtk.Template.Child()
    schedule_view = Gtk.Template.Child()
    schedule_view_inner = Gtk.Template.Child()
    schedule = Gtk.Template.Child()
    nav_view = Gtk.Template.Child()
    network_status = Gtk.Template.Child()

    schedule_sidebar_content = Gtk.Template.Child()
    schedule_sidebar_buttons = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.results_count = 0
        self.selected_courses = set()
        self.json_path = None
        self.schedules = []
        self.current_schedule_idx = 0
        self._saved_selected_courses = set()
        self.course_preferences = {}
        self._sidebar_course_rows = []
        self.generation_process = None

        self.major_keys = []
        self.semester_keys = []
        self.curriculum_data = {}

        self.searchbar.set_visible(False)
        self.show_sidebar_button.set_visible(False)
        self.search_toggle.set_visible(False)

        self.start_hours.set_value(0)
        self.start_minutes.set_value(0)
        self.end_hours.set_value(0)
        self.end_minutes.set_value(0)

        self.gap_start_hours.set_value(0)
        self.gap_start_minutes.set_value(0)
        self.gap_end_hours.set_value(0)
        self.gap_end_minutes.set_value(0)

        self.delete_save.connect("activated", self._on_delete_save_clicked)
        self.nav_view.connect("popped", self._on_nav_popped)
        self.back_button.connect("clicked", lambda *_: self.nav_view.pop())

        self.search_toggle.connect("toggled", lambda btn: self.searchbar.set_search_mode(btn.get_active()))
        self.searchbar.connect("notify::search-mode-enabled", lambda sb, *_: self.search_toggle.set_active(sb.get_search_mode()))
        self.wrap_switch.connect("notify::active", lambda *_: self._update_navigation_buttons())

        self.major_combo.connect("notify::selected", self._on_major_changed)
        self.semester_combo.connect("notify::selected", self._on_semester_changed)

        self.data={}

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_ctrl)

        def filter(row):
            query = self.searchentry.get_text()
            if query == "*":
                self.results_count += 1
                return True
            try:
                match = re.search(query, row.get_title(), re.IGNORECASE)
            except re.error:
                match = None

            if match:
                self.results_count += 1
            return bool(match)

        self.listbox.set_filter_func(filter)

        def sort_courses(row1, row2):
            c1 = getattr(row1, 'course_code', '')
            c2 = getattr(row2, 'course_code', '')
            s1 = c1 in self.selected_courses
            s2 = c2 in self.selected_courses
            if s1 != s2:
                return -1 if s1 else 1
            if c1 < c2: return -1
            if c1 > c2: return 1
            return 0

        self.listbox.set_sort_func(sort_courses)

        def on_search_changed(_search_widget):
            text = self.searchentry.get_text()

            if not text:
                self.stack.set_visible_child(self.main_page)
                self.listbox.set_opacity(0.0)
                return

            self.results_count = -1
            self.listbox.invalidate_filter()
            if self.results_count == -1:
                self.stack.set_visible_child(self.status_page)
                self.listbox.set_opacity(0.0)
            elif self.searchbar.get_search_mode():
                self.stack.set_visible_child(self.search_page)
                self.listbox.set_opacity(1.0)

        style_manager = Adw.StyleManager.get_default()
        self.dm_switch.set_active(style_manager.get_dark())
        self.dm_switch.connect(
            "notify::active",
            lambda *_: style_manager.set_color_scheme(
                Adw.ColorScheme.FORCE_DARK
                if self.dm_switch.get_active()
                else Adw.ColorScheme.FORCE_LIGHT
            ),
        )

        self.fpickerbutton.connect("clicked", self.open_json)
        self.generate.connect("activated", self.on_generate_clicked)
        self.clear_sec.connect("clicked", self.on_clear_sec_clicked)

        self.searchentry.connect("search-changed", on_search_changed)
        self.carousel.connect("page-changed", self.on_page_changed)
        self.search_page.connect("edge-overshot", self.on_edge_overshot)

        self.connect("close-request", self.on_close_request)

        self.load_settings()
        if self.local_load_switch.get_active():
            self.fpickerbutton.set_visible(True)

        self._build_sidebar_controls()
        self._fetch_database_async()

    def _on_nav_popped(self, *args):
        self.show_sidebar_button.set_visible(False)
        self.show_sidebar_button.set_active(False)
        self.back_button.set_visible(False)

    def _ensure_check_icon(self):
        if not hasattr(self, "check_icon"):
            self.check_icon = Gtk.Image()
            self.check_icon.set_pixel_size(24)
            self.check_icon.set_margin_top(18)
            self.network_status.get_parent().append(self.check_icon)

    def _fetch_database_async(self):
        self.network_banner.set_revealed(False)
        self.network_status.set_opacity(1)
        self.network_status.set_visible(True)

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
                with urllib.request.urlopen(req_db, context=context, timeout=10) as response:
                    db_content = response.read().decode('utf-8')
                parsed_db = json.loads(db_content)
                with open(local_db_path, 'w', encoding='utf-8') as f:
                    f.write(db_content)
            except Exception as e:
                print(f"Failed to download course database: {e}")

            try:
                req_spec = urllib.request.Request(spec_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_spec, context=context, timeout=10) as response:
                    spec_content = response.read().decode('utf-8')
                parsed_spec = json.loads(spec_content)
                with open(local_spec_path, 'w', encoding='utf-8') as f:
                    f.write(spec_content)
            except Exception as e:
                print(f"Failed to download curriculum spec: {e}")

            GLib.idle_add(self._on_fetch_complete, local_db_path, parsed_db, local_spec_path, parsed_spec)

        threading.Thread(target=fetch_task, daemon=True).start()

    def _on_fetch_complete(self, local_db_path, parsed_db, local_spec_path, parsed_spec):
        self.network_status.set_visible(False)
        self.fpickerbutton.set_sensitive(True)
        self._ensure_check_icon()

        if not parsed_db and os.path.exists(local_db_path):
            try:
                with open(local_db_path, 'r', encoding='utf-8') as f:
                    parsed_db = json.load(f)
            except Exception:
                pass

        if not parsed_spec and os.path.exists(local_spec_path):
            try:
                with open(local_spec_path, 'r', encoding='utf-8') as f:
                    parsed_spec = json.load(f)
            except Exception:
                pass

        if parsed_db:
            self.data = parsed_db
            self.json_path = local_db_path
            self.populate_listbox()

        if parsed_spec:
            self.curriculum_data = parsed_spec
            self._populate_curriculum_dropdowns()

        if parsed_db and parsed_spec:
            self.check_icon.set_from_icon_name("circle-checkmark-symbolic")
            self.check_icon.set_tooltip_text("Database and Curriculum Specs Loaded Successfully")
            self.check_icon.remove_css_class("error")
            self.check_icon.remove_css_class("warning")
            self.check_icon.add_css_class("success")
            self.check_icon.set_visible(True)

            def transition_to_courses():
                self.carousel.scroll_to(self.courses_page, True)
                return False

            GLib.timeout_add(1000, transition_to_courses)
        else:
            self.network_banner.set_revealed(True)
            self.check_icon.remove_css_class("success")

            if not parsed_db:
                self.check_icon.set_from_icon_name("circle-x-symbolic")
                self.check_icon.set_tooltip_text("Failed To Retrieve Online Database")
                self.check_icon.remove_css_class("warning")
                self.check_icon.add_css_class("error")
                self.network_banner.set_title("Failed to retrieve online database")
            else:
                self.check_icon.set_from_icon_name("circle-checkmark-symbolic")
                self.check_icon.set_tooltip_text("Failed online sync. Using local cache.")
                self.check_icon.remove_css_class("error")
                self.check_icon.add_css_class("warning")
                self.network_banner.set_title("Failed to retrieve online database. Using Cached Version")

                def transition_to_courses():
                    self.carousel.scroll_to(self.courses_page, True)
                    return False

                GLib.timeout_add(1000, transition_to_courses)

        self.check_icon.set_visible(True)
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
                self.numcourses.set_text("0/7")
                self.numcourses.set_fraction(0.0)
                self.show_message_dialog(
                    heading="No Courses Selected",
                    body="No courses are listed for the selected semester (e.g. Summer semester)."
                )
                return

            missing_courses = []
            for course_code in preset_courses:
                if course_code in self.data:
                    self.selected_courses.add(course_code)
                else:
                    missing_courses.append(course_code)

            self.populate_listbox()

            num = len(self.selected_courses)
            self.numcourses.set_text(f"{num}/7")
            self.numcourses.set_fraction(min(num / 7, 1.0))

            if len(self.selected_courses) == 0:
                missing_str = "\n".join(f"• {c}" for c in missing_courses)
                self.show_message_dialog(
                    heading="No Courses Selected",
                    body=f"None of the required courses could be selected because they were not found in the database:\n\n{missing_str}"
                )
            elif missing_courses:
                missing_str = "\n".join(f"• {c}" for c in missing_courses)
                self.show_message_dialog(
                    heading="Missing Courses",
                    body=f"The following required course(s) could not be selected because they were not found in the database:\n\n{missing_str}"
                )

        except Exception as e:
            print(f"Error executing curriculum spec preset: {e}")

    def on_clear_sec_clicked(self, btn):
        self.selected_courses.clear()
        self.course_preferences.clear()
        self.numcourses.set_text("0/7")
        self.numcourses.set_fraction(0.0)
        self.populate_listbox()

    def _on_previous_clicked(self, _button):
        if self.schedules and self.current_schedule_idx > 0:
            self.current_schedule_idx -= 1
            self.draw_schedule_index(self.current_schedule_idx)
        elif self.wrap_switch.get_active() and self.current_schedule_idx == 0:
            self.current_schedule_idx = len(self.schedules) - 1
            self.draw_schedule_index(self.current_schedule_idx)

    def _on_next_clicked(self, _button):
        if self.schedules and self.current_schedule_idx < len(self.schedules) - 1:
            self.current_schedule_idx += 1
            self.draw_schedule_index(self.current_schedule_idx)
        elif self.wrap_switch.get_active() and self.current_schedule_idx == len(self.schedules) - 1:
            self.current_schedule_idx = 0
            self.draw_schedule_index(self.current_schedule_idx)

    def _build_sidebar_controls(self):
        self.prev_btn = Gtk.Button(icon_name="go-previous-symbolic")
        self.prev_btn.set_tooltip_text("Go To Previous Schedule (Left Arrow Key)")
        self.prev_btn.add_css_class("circular")
        self.prev_btn.connect("clicked", self._on_previous_clicked)
        self.schedule_sidebar_buttons.append(self.prev_btn)

        copy_btn = Gtk.Button(icon_name="clipboard-symbolic")
        copy_btn.add_css_class("linked")
        copy_btn.set_tooltip_text("Copy Schedule To Clipboard")
        copy_btn.connect("clicked", self.on_copy_schedule_clicked)
        self.schedule_sidebar_buttons.append(copy_btn)

        compare_btn = Gtk.Button(icon_name="loop-arrow-symbolic")
        compare_btn.set_tooltip_text("Compare and Reschedule.")
        compare_btn.add_css_class("linked")
        compare_btn.connect("clicked", self.on_compare_clicked)
        self.schedule_sidebar_buttons.append(compare_btn)

        import_btn = Gtk.Button(icon_name="folder-download-symbolic")
        import_btn.set_tooltip_text("Import Schedule")
        import_btn.add_css_class("linked")
        import_btn.connect("clicked", self.on_import_clicked)
        self.schedule_sidebar_buttons.append(import_btn)

        self.next_btn = Gtk.Button(icon_name="go-next-symbolic")
        self.next_btn.set_tooltip_text("Go To Next Schedule (Right Arrow Key)")
        self.next_btn.add_css_class("circular")
        self.next_btn.connect("clicked", self._on_next_clicked)
        self.schedule_sidebar_buttons.append(self.next_btn)

        self._update_navigation_buttons()

        self.sidebar_courses_group = Adw.PreferencesGroup(title="Course Filters")
        self.sidebar_courses_group.set_margin_top(0)
        self.sidebar_courses_group.set_margin_start(12)
        self.sidebar_courses_group.set_margin_end(12)
        self.schedule_sidebar_content.append(self.sidebar_courses_group)

        pref_group = Adw.PreferencesGroup(title="Filters and Tuning")
        pref_group.set_margin_top(12)
        pref_group.set_margin_start(12)
        pref_group.set_margin_end(12)
        self.schedule_sidebar_content.append(pref_group)

        days_exp = Adw.ExpanderRow(title="Exclude Days")
        days_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        days_box.set_margin_top(6)
        days_box.set_margin_bottom(6)
        days_box.set_margin_start(12)
        days_box.set_margin_end(12)

        days_mapping = [
            ("Sunday", self.checksun),
            ("Monday", self.checkmon),
            ("Tuesday", self.checktue),
            ("Wednesday", self.checkwed),
            ("Thursday", self.checkthu),
            ("Friday", self.checkfri),
            ("Saturday", self.checksat),
        ]

        for day_name, source_check in days_mapping:
            check = Gtk.CheckButton(label=day_name)
            source_check.bind_property("active", check, "active", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
            days_box.append(check)

        days_exp.add_row(days_box)
        pref_group.add(days_exp)

        sb_time_exp = Adw.ExpanderRow(title="Time Boundary", show_enable_switch=True)
        self.time.bind_property("enable-expansion", sb_time_exp, "enable-expansion", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        start_row = Adw.ActionRow(title="Start Time")
        start_h_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=23, step_increment=1))
        start_h_spin.set_valign(Gtk.Align.CENTER)
        self.start_hours.bind_property("value", start_h_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        start_m_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=59, step_increment=15))
        start_m_spin.set_valign(Gtk.Align.CENTER)
        self.start_minutes.bind_property("value", start_m_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        start_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        start_box.append(start_h_spin)
        start_box.append(Gtk.Label(label=":"))
        start_box.append(start_m_spin)
        start_row.add_suffix(start_box)
        sb_time_exp.add_row(start_row)

        end_row = Adw.ActionRow(title="End Time")
        end_h_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=23, step_increment=1))
        end_h_spin.set_valign(Gtk.Align.CENTER)
        self.end_hours.bind_property("value", end_h_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        end_m_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=59, step_increment=15))
        end_m_spin.set_valign(Gtk.Align.CENTER)
        self.end_minutes.bind_property("value", end_m_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        end_box.append(end_h_spin)
        end_box.append(Gtk.Label(label=":"))
        end_box.append(end_m_spin)
        end_row.add_suffix(end_box)
        sb_time_exp.add_row(end_row)

        pref_group.add(sb_time_exp)

        sb_gap_exp = Adw.ExpanderRow(title="Specify Gap", show_enable_switch=True)
        self.gap_time.bind_property("enable-expansion", sb_gap_exp, "enable-expansion", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        sb_gap_day = Adw.ComboRow(title="Day")
        sb_gap_day.set_model(Gtk.StringList.new(["All Days", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]))
        self.gap_day.bind_property("selected", sb_gap_day, "selected", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        sb_gap_exp.add_row(sb_gap_day)

        gap_start_row = Adw.ActionRow(title="Start Time")
        gap_start_h_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=23, step_increment=1))
        gap_start_h_spin.set_valign(Gtk.Align.CENTER)
        self.gap_start_hours.bind_property("value", gap_start_h_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        gap_start_m_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=59, step_increment=15))
        gap_start_m_spin.set_valign(Gtk.Align.CENTER)
        self.gap_start_minutes.bind_property("value", gap_start_m_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        gap_start_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        gap_start_box.append(gap_start_h_spin)
        gap_start_box.append(Gtk.Label(label=":"))
        gap_start_box.append(gap_start_m_spin)
        gap_start_row.add_suffix(gap_start_box)
        sb_gap_exp.add_row(gap_start_row)

        gap_end_row = Adw.ActionRow(title="End Time")
        gap_end_h_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=23, step_increment=1))
        gap_end_h_spin.set_valign(Gtk.Align.CENTER)
        self.gap_end_hours.bind_property("value", gap_end_h_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        gap_end_m_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=59, step_increment=15))
        gap_end_m_spin.set_valign(Gtk.Align.CENTER)
        self.gap_end_minutes.bind_property("value", gap_end_m_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)

        gap_end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        gap_end_box.append(gap_end_h_spin)
        gap_end_box.append(Gtk.Label(label=":"))
        gap_end_box.append(gap_end_m_spin)
        gap_end_row.add_suffix(gap_end_box)
        sb_gap_exp.add_row(gap_end_row)

        pref_group.add(sb_gap_exp)

        self.sb_ls_switch = Adw.SwitchRow(title="Exclude Full Classes")
        self.ls_switch.bind_property("active", self.sb_ls_switch, "active", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        pref_group.add(self.sb_ls_switch)

        self.sb_tuner = Adw.ComboRow(title="Prioritize")
        self.sb_tuner.set_model(Gtk.StringList.new(["Compact Days", "Fewer Days", "Shorter Days", "Consistent Days"]))
        self.tuner.bind_property("selected", self.sb_tuner, "selected", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        pref_group.add(self.sb_tuner)

        self.sb_sec_tuner = Adw.ComboRow(title="Tie-Breaker")
        self.sb_sec_tuner.set_model(Gtk.StringList.new(["None", "Compact Days", "Fewer Days", "Shorter Days", "Consistent Days"]))
        self.sec_tuner.bind_property("selected", self.sb_sec_tuner, "selected", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        pref_group.add(self.sb_sec_tuner)

        sb_gen_btn = Gtk.Button(label="Generate Schedules")
        sb_gen_btn.add_css_class("suggested-action")
        sb_gen_btn.add_css_class("pill")
        sb_gen_btn.set_margin_top(12)
        sb_gen_btn.set_margin_start(12)
        sb_gen_btn.set_margin_end(12)
        sb_gen_btn.connect("clicked", self.on_generate_clicked)
        self.schedule_sidebar_content.append(sb_gen_btn)

    def _update_navigation_buttons(self):
        if not hasattr(self, 'prev_btn') or not hasattr(self, 'next_btn'):
            return

        total_schedules = len(self.schedules) if self.schedules else 0

        if total_schedules <= 1:
            self.prev_btn.set_sensitive(False)
            self.next_btn.set_sensitive(False)
            return

        if self.wrap_switch.get_active():
            self.prev_btn.set_sensitive(True)
            self.next_btn.set_sensitive(True)
        else:
            self.prev_btn.set_sensitive(self.current_schedule_idx > 0)
            self.next_btn.set_sensitive(self.current_schedule_idx < total_schedules - 1)

    def _update_sidebar_course_filters(self):
        for row in self._sidebar_course_rows:
            self.sidebar_courses_group.remove(row)
        self._sidebar_course_rows.clear()

        for course_code in sorted(self.selected_courses):
            sections_list = self.data.get(course_code, [])

            lec_instructors = set()
            lab_instructors = set()
            tut_instructors = set()
            sections = set()

            for sec in sections_list:
                inst = sec.get("instructor")
                subtype = sec.get("subtype")
                s_id = sec.get("section")

                if inst and inst != "Not Assigned":
                    if subtype == "Lecture":
                        lec_instructors.add(inst)
                    elif subtype == "Lab":
                        lab_instructors.add(inst)
                    elif subtype == "Tutorial":
                        tut_instructors.add(inst)

                if subtype == "Lecture" and s_id:
                    sections.add(s_id)

            lec_inst_list = sorted(list(lec_instructors))
            lab_inst_list = sorted(list(lab_instructors))
            tut_inst_list = sorted(list(tut_instructors))
            sec_list = sorted(list(sections))

            has_instructors = len(lec_inst_list) > 1 or len(lab_inst_list) > 1 or len(tut_inst_list) > 1
            has_sections = len(sec_list) > 1

            if not has_instructors and not has_sections:
                continue

            saved_pref = self.course_preferences.get(course_code, {"type": "Neither", "value": ""})

            if saved_pref["type"] == "Instructor":
                valid = False
                if len(lec_inst_list) > 1 and saved_pref["value"] in lec_inst_list: valid = True
                if len(lab_inst_list) > 1 and saved_pref["value"] in lab_inst_list: valid = True
                if len(tut_inst_list) > 1 and saved_pref["value"] in tut_inst_list: valid = True
                if not valid:
                    saved_pref = {"type": "Neither", "value": ""}
                    self.course_preferences[course_code] = saved_pref
            elif saved_pref["type"] == "Section":
                if not has_sections or saved_pref["value"] not in sec_list:
                    saved_pref = {"type": "Neither", "value": ""}
                    self.course_preferences[course_code] = saved_pref

            expander = Adw.ExpanderRow(title=course_code)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            vbox.set_margin_top(12)
            vbox.set_margin_bottom(12)
            vbox.set_margin_start(12)
            vbox.set_margin_end(12)
            expander.add_row(vbox)

            none_btn = Gtk.CheckButton(label="Any")
            vbox.append(none_btn)

            def on_btn_toggled(btn, pref_type, val, c=course_code):
                if btn.get_active():
                    self.course_preferences[c] = {"type": pref_type, "value": val}

            none_btn.connect("toggled", on_btn_toggled, "Neither", "")

            if saved_pref["type"] == "Neither":
                none_btn.set_active(True)

            has_activated_instructor = False

            def append_instructor_group(title, inst_list):
                nonlocal has_activated_instructor

                if len(inst_list) <= 1:
                    return

                vbox.append(Gtk.Separator(margin_top=4, margin_bottom=4))
                lbl = Gtk.Label(label=f"<b>{title}</b>", use_markup=True)
                lbl.set_halign(Gtk.Align.START)
                lbl.add_css_class("dim-label")
                vbox.append(lbl)

                for inst in inst_list:
                    inst_label = Gtk.Label(label=inst)
                    inst_label.set_ellipsize(Pango.EllipsizeMode.END)
                    inst_label.set_lines(1)
                    inst_label.set_max_width_chars(25)
                    inst_label.set_xalign(0)
                    inst_label.set_tooltip_text(inst)

                    btn = Gtk.CheckButton()
                    btn.set_child(inst_label)
                    btn.set_group(none_btn)
                    btn.connect("toggled", on_btn_toggled, "Instructor", inst)
                    vbox.append(btn)

                    if not has_activated_instructor and saved_pref["type"] == "Instructor" and saved_pref["value"] == inst:
                        btn.set_active(True)
                        has_activated_instructor = True

            append_instructor_group("Lecture Instructors", lec_inst_list)
            append_instructor_group("Lab Instructors", lab_inst_list)
            append_instructor_group("Tutorial Instructors", tut_inst_list)

            if has_sections:
                vbox.append(Gtk.Separator(margin_top=4, margin_bottom=4))
                lbl = Gtk.Label(label="<b>Sections</b>", use_markup=True)
                lbl.set_halign(Gtk.Align.START)
                lbl.add_css_class("dim-label")
                vbox.append(lbl)

                for sec in sec_list:
                    sec_label = Gtk.Label(label=sec)
                    sec_label.set_ellipsize(Pango.EllipsizeMode.END)
                    sec_label.set_lines(1)
                    sec_label.set_max_width_chars(25)
                    sec_label.set_xalign(0)
                    sec_label.set_tooltip_text(sec)

                    btn = Gtk.CheckButton()
                    btn.set_child(sec_label)
                    btn.set_group(none_btn)
                    btn.connect("toggled", on_btn_toggled, "Section", sec)
                    vbox.append(btn)

                    if saved_pref["type"] == "Section" and saved_pref["value"] == sec:
                        btn.set_active(True)

            self.sidebar_courses_group.add(expander)
            self._sidebar_course_rows.append(expander)

        has_rows = len(self._sidebar_course_rows) > 0
        self.sidebar_courses_group.set_visible(has_rows)

    def on_copy_schedule_clicked(self, btn):
        if not self.schedules or self.current_schedule_idx >= len(self.schedules):
            return

        sched = self.schedules[self.current_schedule_idx]

        days_map = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
        lines = []

        meetings = sorted(sched["meetings"], key=lambda m: (m['course'], m['type'], m['id']))
        for m in meetings:
            if m['day'] == 0 or m['start'] < 0 or m['end'] < 0:
                continue

            course = m['course'].ljust(8)
            mtype = m['type'].ljust(11)
            mid = m['id'].ljust(6)
            day = days_map.get(m['day'], "TBD").ljust(6)

            start_h, start_m = divmod(m['start'], 60)
            end_h, end_m = divmod(m['end'], 60)
            time_str = f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}".ljust(13)

            inst = m['instructor']

            lines.append(f"{course}{mtype}{mid}{day}{time_str}| {inst}")

        text = "\n".join(lines)
        clipboard = self.get_clipboard()
        clipboard.set(text)

        btn.set_icon_name("checkmark-symbolic")
        GLib.timeout_add(2000, lambda: btn.set_icon_name("clipboard-symbolic") or False)

    def on_import_clicked(self, _button):
        dialog = Adw.Dialog(title="Import Schedule")
        dialog.set_content_width(450)
        dialog.set_content_height(400)

        toolbar = Adw.ToolbarView()
        dialog.set_child(toolbar)

        header = Adw.HeaderBar()
        header.add_css_class("flat")
        toolbar.add_top_bar(header)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(18)
        vbox.set_margin_start(18)
        vbox.set_margin_end(18)

        lbl = Gtk.Label(label="Paste your copied schedule text below:")
        lbl.set_halign(Gtk.Align.START)
        vbox.append(lbl)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        textview = Gtk.TextView()
        textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        textview.add_css_class("card")
        scrolled.set_child(textview)
        vbox.append(scrolled)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_homogeneous(True)
        btn_box.set_margin_top(10)
        vbox.append(btn_box)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("pill")
        btn_box.append(cancel_btn)

        import_action_btn = Gtk.Button(label="Import")
        import_action_btn.add_css_class("suggested-action")
        import_action_btn.add_css_class("pill")
        btn_box.append(import_action_btn)

        toolbar.set_content(vbox)

        def on_cancel(btn):
            dialog.close()

        def on_import(btn):
            buf = textview.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            if self._parse_and_import_schedule(text):
                dialog.close()

        cancel_btn.connect("clicked", on_cancel)
        import_action_btn.connect("clicked", on_import)

        dialog.present()

    def _parse_and_import_schedule(self, text):
        lines = text.strip().split("\n")
        new_selected = set()
        new_prefs = {}

        for line in lines:
            if "|" not in line:
                continue

            left, right = line.split("|", 1)
            tokens = left.strip().split()

            if not tokens:
                continue

            course = tokens[0]
            new_selected.add(course)

            if len(tokens) > 2 and tokens[1] == "Lecture":
                section = tokens[2]
                new_prefs[course] = {"type": "Section", "value": section}

        if not new_selected:
            self.show_error_dialog("Could not parse any courses from the provided text.")
            return False

        self.selected_courses = new_selected
        self.course_preferences = new_prefs

        self.on_generate_clicked(None)
        self.course_preferences.clear()
        self.populate_listbox()
        self._update_sidebar_course_filters()
        num = len(self.selected_courses)
        self.numcourses.set_text(f"{num}/7")
        self.numcourses.set_fraction(num/7)
        return True

    def on_close_request(self, *args):
        if hasattr(self, 'generation_process') and self.generation_process:
            try:
                self.generation_process.terminate()
            except Exception:
                pass
        self.save_settings()
        return False

    def save_settings(self):
        settings = {
            "json_path": self.json_path,
            "selected_courses": list(self.selected_courses),
            "course_preferences": self.course_preferences,
            "time_enabled": self.time.get_enable_expansion(),
            "start_hours": self.start_hours.get_value_as_int(),
            "start_minutes": self.start_minutes.get_value_as_int(),
            "end_hours": self.end_hours.get_value_as_int(),
            "end_minutes": self.end_minutes.get_value_as_int(),
            "gap_enabled": self.gap_time.get_enable_expansion(),
            "gap_day": self.gap_day.get_selected(),
            "gap_start_hours": self.gap_start_hours.get_value_as_int(),
            "gap_start_minutes": self.gap_start_minutes.get_value_as_int(),
            "gap_end_hours": self.gap_end_hours.get_value_as_int(),
            "gap_end_minutes": self.gap_end_minutes.get_value_as_int(),
            "exclude_full": self.ls_switch.get_active(),
            "tuner": self.tuner.get_selected(),
            "sec_tuner": self.sec_tuner.get_selected(),
            "dark_mode": self.dm_switch.get_active(),
            "wrap_mode": self.wrap_switch.get_active(),
            "local_load": self.local_load_switch.get_active(),
            "checksun": self.checksun.get_active(),
            "checkmon": self.checkmon.get_active(),
            "checktue": self.checktue.get_active(),
            "checkwed": self.checkwed.get_active(),
            "checkthu": self.checkthu.get_active(),
            "checkfri": self.checkfri.get_active(),
            "checksat": self.checksat.get_active()
        }
        config_dir = os.path.join(GLib.get_user_config_dir(), "commodus")
        os.makedirs(config_dir, exist_ok=True)
        path = os.path.join(config_dir, "settings.json")
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def load_settings(self):
        path = os.path.join(GLib.get_user_config_dir(), "commodus", "settings.json")
        if not os.path.exists(path):
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            self.time.set_enable_expansion(settings.get("time_enabled", False))
            self.start_hours.set_value(settings.get("start_hours", 0))
            self.start_minutes.set_value(settings.get("start_minutes", 0))
            self.end_hours.set_value(settings.get("end_hours", 0))
            self.end_minutes.set_value(settings.get("end_minutes", 0))

            self.gap_time.set_enable_expansion(settings.get("gap_enabled", False))
            self.gap_day.set_selected(settings.get("gap_day", 0))
            self.gap_start_hours.set_value(settings.get("gap_start_hours", 0))
            self.gap_start_minutes.set_value(settings.get("gap_start_minutes", 0))
            self.gap_end_hours.set_value(settings.get("gap_end_hours", 0))
            self.gap_end_minutes.set_value(settings.get("gap_end_minutes", 0))

            self.ls_switch.set_active(settings.get("exclude_full", True))
            self.tuner.set_selected(settings.get("tuner", 0))
            self.sec_tuner.set_selected(settings.get("sec_tuner", 0))
            self.dm_switch.set_active(settings.get("dark_mode", False))
            self.wrap_switch.set_active(settings.get("wrap_mode", False))
            self.local_load_switch.set_active(settings.get("local_load", False))

            self.checksun.set_active(settings.get("checksun", False))
            self.checkmon.set_active(settings.get("checkmon", False))
            self.checktue.set_active(settings.get("checktue", False))
            self.checkwed.set_active(settings.get("checkwed", False))
            self.checkthu.set_active(settings.get("checkthu", False))
            self.checkfri.set_active(settings.get("checkfri", False))
            self.checksat.set_active(settings.get("checksat", False))

            self._saved_selected_courses = set(settings.get("selected_courses", []))
            self.course_preferences = settings.get("course_preferences", {})

            saved_json = settings.get("json_path")
            if saved_json and os.path.exists(saved_json):
                self.load_database_from_path(saved_json)

        except Exception as e:
            print(f"Error loading settings: {e}")

    def _on_delete_save_clicked(self, _button):
        path = os.path.join(GLib.get_user_config_dir(), "commodus", "settings.json")
        if os.path.exists(path):
            try:
                os.remove(path)

                dialog = Adw.MessageDialog(
                    transient_for=self,
                    heading="Save Deleted",
                    body="Your saved preferences and selected courses have been successfully deleted."
                )
                dialog.add_response("ok", "OK")
                dialog.set_default_response("ok")
                dialog.connect("response", lambda d, r: d.close())
                dialog.present()

            except Exception as e:
                self.show_error_dialog(f"Error removing save file: {e}")
                return

        self.selected_courses.clear()
        self.course_preferences.clear()
        self._saved_selected_courses.clear()
        self.json_path = None
        self.data = {}
        self.schedules = []
        self.current_schedule_idx = 0

        self.time.set_enable_expansion(False)
        self.start_hours.set_value(0)
        self.start_minutes.set_value(0)
        self.end_hours.set_value(23)
        self.end_minutes.set_value(59)

        self.gap_time.set_enable_expansion(False)
        self.gap_day.set_selected(0)
        self.gap_start_hours.set_value(0)
        self.gap_start_minutes.set_value(0)
        self.gap_end_hours.set_value(0)
        self.gap_end_minutes.set_value(0)

        self.ls_switch.set_active(False)
        self.tuner.set_selected(0)
        self.sec_tuner.set_selected(0)
        self.dm_switch.set_active(False)
        self.wrap_switch.set_active(False)

        self.checksun.set_active(False)
        self.checkmon.set_active(False)
        self.checktue.set_active(False)
        self.checkwed.set_active(False)
        self.checkthu.set_active(False)
        self.checkfri.set_active(False)
        self.checksat.set_active(False)

        self.numcourses.set_text("0/7")
        self.numcourses.set_fraction(0.0)

        self.populate_listbox()
        child = self.schedule.get_first_child()
        while child:
            self.schedule.remove(child)
            child = self.schedule.get_first_child()

        self._update_navigation_buttons()

    def load_database_from_path(self, path):
        print(f"Loading JSON Database: {path}")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
            self.json_path = path
            self.populate_listbox()
        except Exception as e:
            print(f"Failed to load database {path}: {e}")
            self.data = {}

    def show_message_dialog(self, heading, body):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=heading,
            body=body
        )
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.connect("response", lambda d, r: d.close())
        dialog.present()

    def show_error_dialog(self, message):
        self.show_message_dialog("Error", message)

    def on_key_pressed(self, controller, keyval, keycode, state):
        is_schedule_view = False
        try:
            is_schedule_view = (self.nav_view.get_visible_page() == self.schedule_view)
        except AttributeError:
            pass

        if state & Gdk.ModifierType.CONTROL_MASK:
            pages_map = {
                Gdk.KEY_1: getattr(self, "data_page", None),
                Gdk.KEY_2: getattr(self, "courses_page", None),
                Gdk.KEY_3: getattr(self, "filters_page", None),
                Gdk.KEY_4: getattr(self, "tuning_page", None),
            }

            if keyval in pages_map and pages_map[keyval] is not None:
                if is_schedule_view:
                    self.nav_view.pop()
                self.carousel.scroll_to(pages_map[keyval], True)
                return True

        if not is_schedule_view:
            if keyval in (Gdk.KEY_g, Gdk.KEY_G):
                if hasattr(self, "check_icon"):
                    self.on_generate_clicked(self)
                return True
            return False

        if keyval in (Gdk.KEY_s, Gdk.KEY_S):
            is_active = self.show_sidebar_button.get_active()
            self.show_sidebar_button.set_active(not is_active)
            return True

        elif keyval == Gdk.KEY_Right:
            if self.schedules and len(self.schedules) > 1:
                if self.current_schedule_idx < len(self.schedules) - 1:
                    self.current_schedule_idx += 1
                    self.draw_schedule_index(self.current_schedule_idx)
                    return True
                elif self.wrap_switch.get_active() and self.current_schedule_idx == len(self.schedules) - 1:
                    self.current_schedule_idx = 0
                    self.draw_schedule_index(self.current_schedule_idx)
                    return True

        elif keyval == Gdk.KEY_Left:
            if self.schedules and len(self.schedules) > 1:
                if self.current_schedule_idx > 0:
                    self.current_schedule_idx -= 1
                    self.draw_schedule_index(self.current_schedule_idx)
                    return True
                elif self.wrap_switch.get_active() and self.current_schedule_idx == 0:
                    self.current_schedule_idx = len(self.schedules) - 1
                    self.draw_schedule_index(self.current_schedule_idx)
                    return True

        elif keyval in (Gdk.KEY_c, Gdk.KEY_C) and (state & Gdk.ModifierType.CONTROL_MASK):
            self.on_copy_schedule_clicked(self)
            return True

        return False

    def on_page_changed(self, carousel, index):
        if index==2:
            self.revealer_slide.set_reveal_child(True)
            self.searchbar.set_visible(False)
            self.search_toggle.set_visible(False)
            self.searchbar.set_key_capture_widget(None)
            self.show_sidebar_button.set_visible(False)
            self.action_bar.set_revealed(False)
        elif index==1:
            is_schedule_view = (self.nav_view.get_visible_page() == self.schedule_view)
            self.revealer_slide.set_reveal_child(False)
            if not is_schedule_view:
                self.searchbar.set_visible(True)
                self.search_toggle.set_visible(True)
                self.search_toggle.set_active(True)
                self.searchbar.set_key_capture_widget(self)
                self.show_sidebar_button.set_visible(False)
                self.action_bar.set_revealed(True)
        elif index==0:
            self.revealer_slide.set_reveal_child(False)
            self.searchbar.set_visible(False)
            self.search_toggle.set_visible(False)
            self.searchbar.set_key_capture_widget(None)
            self.show_sidebar_button.set_visible(False)
            self.action_bar.set_revealed(False)
        else:
            self.revealer_slide.set_reveal_child(False)
            self.searchbar.set_visible(False)
            self.search_toggle.set_visible(False)
            self.searchbar.set_key_capture_widget(None)
            self.show_sidebar_button.set_visible(False)
            self.action_bar.set_revealed(False)

    def on_edge_overshot(self, search_page, pos):
        if pos == 3:
            self.carousel.scroll_to(self.filters_page, True)
            self.searchbar.set_search_mode(False)
        elif pos == 2:
            self.carousel.scroll_to(self.data_page, True)
            self.searchbar.set_search_mode(False)

    def open_json(self, button):
        file_dialog = Gtk.FileDialog()
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON")
        json_filter.add_mime_type("application/json")
        json_filter.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter())
        filters.append(json_filter)
        file_dialog.set_default_filter(json_filter)
        file_dialog.open(self, None, self.on_json_opened)

    def on_json_opened(self, file_dialog, result):
        try:
            file = file_dialog.open_finish(result)
            path = file.get_path()
            if path:
                self.load_database_from_path(path)
        except GLib.Error as e:
            print(f"An error occurred while reading the file: {e.message}")

    def get_file_name(self, file):
            return file.get_path()

    def populate_listbox(self):
        child = self.listbox.get_first_child()
        while child:
            self.listbox.remove(child)
            child = self.listbox.get_first_child()

        saved_selection = self._saved_selected_courses if hasattr(self, '_saved_selected_courses') and self._saved_selected_courses else set(self.selected_courses)
        self.selected_courses.clear()

        sorted_keys = sorted(self.data.keys(), key=lambda c: (c not in saved_selection, c))

        for course_code in sorted_keys:
            sections_list = self.data[course_code]
            full_title = sections_list[0].get("fullTitle", "") if sections_list else ""

            if full_title:
                prefix_pattern = re.compile(rf"^{re.escape(course_code)}\s*[:-]?\s*", re.IGNORECASE)
                clean_title = prefix_pattern.sub("", full_title)
            else:
                clean_title = ""

            if clean_title and clean_title.lower() != course_code.lower():
                display_title = f"{course_code}: {clean_title}"
            else:
                display_title = course_code

            escaped_title = GLib.markup_escape_text(display_title)

            row = Adw.ActionRow(title=escaped_title)
            row.course_code = course_code
            row.set_title_lines(2)

            self.listbox.append(row)
            chboxcont = Gtk.Box(spacing=10, valign="center")
            row.add_suffix(chboxcont)

            # Extract instructors and section numbers
            lec_instructors = set()
            lab_instructors = set()
            tut_instructors = set()
            sections = set()

            for sec in sections_list:
                inst = sec.get("instructor")
                subtype = sec.get("subtype")
                s_id = sec.get("section")

                if inst and inst != "Not Assigned":
                    if subtype == "Lecture":
                        lec_instructors.add(inst)
                    elif subtype == "Lab":
                        lab_instructors.add(inst)
                    elif subtype == "Tutorial":
                        tut_instructors.add(inst)

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
            menubutton.set_tooltip_text("Filter By Section Or Instructor")

            saved_pref = self.course_preferences.get(course_code, {"type": "Neither", "value": ""})

            if saved_pref["type"] == "Instructor":
                valid = False
                if len(lec_inst_list) > 1 and saved_pref["value"] in lec_inst_list: valid = True
                if len(lab_inst_list) > 1 and saved_pref["value"] in lab_inst_list: valid = True
                if len(tut_inst_list) > 1 and saved_pref["value"] in tut_inst_list: valid = True
                if not valid:
                    saved_pref = {"type": "Neither", "value": ""}
                    self.course_preferences[course_code] = saved_pref
            elif saved_pref["type"] == "Section":
                if not has_sections or saved_pref["value"] not in sec_list:
                    saved_pref = {"type": "Neither", "value": ""}
                    self.course_preferences[course_code] = saved_pref

            if not has_instructors and not has_sections:
                menubutton.set_visible(False)
            else:
                popover = Gtk.Popover()
                menubutton.set_popover(popover)

                main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                popover.set_child(main_vbox)

                stack = Gtk.Stack()
                stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

                switcher = Gtk.StackSwitcher()
                switcher.set_stack(stack)
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
                none_vbox.set_margin_top(18)
                none_vbox.set_margin_bottom(18)
                none_vbox.set_margin_start(18)
                none_vbox.set_margin_end(18)

                none_desc = Gtk.Label(label="No filters applied.\nAny section or instructor can be used.")
                none_desc.add_css_class("dim-label")
                none_desc.set_halign(Gtk.Align.CENTER)
                none_desc.set_justify(Gtk.Justification.CENTER)
                none_desc.set_wrap(True)
                none_desc.set_max_width_chars(5)
                none_vbox.append(none_desc)

                stack.add_titled(none_vbox, "none", "Clear Filters")
                stack.get_page(none_vbox).set_icon_name("action-unavailable-symbolic")

                def on_btn_toggled(btn, pref_type, val, c=course_code, mb=menubutton):
                    if btn.get_active():
                        self.course_preferences[c] = {"type": pref_type, "value": val}
                        if pref_type != "Neither":
                            mb.set_icon_name("funnel-symbolic")

                if has_instructors:
                    inst_scroll = Gtk.ScrolledWindow()
                    inst_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
                    inst_scroll.set_propagate_natural_height(True)
                    inst_scroll.set_max_content_height(300)

                    inst_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    inst_vbox.set_margin_top(6)
                    inst_vbox.set_margin_bottom(12)
                    inst_vbox.set_margin_start(12)
                    inst_vbox.set_margin_end(12)
                    inst_scroll.set_child(inst_vbox)

                    stack.add_titled(inst_scroll, "instructors", "Instructors")
                    stack.get_page(inst_scroll).set_icon_name("avatar-default-symbolic")

                    has_activated_instructor = False

                    def append_instructor_group(title, inst_list):
                        nonlocal has_activated_instructor

                        if len(inst_list) <= 1:
                            return

                        if inst_vbox.get_first_child() is not None:
                            inst_vbox.append(Gtk.Separator(margin_top=4, margin_bottom=4))

                        lbl = Gtk.Label(label=f"<b>{title}</b>", use_markup=True)
                        lbl.set_halign(Gtk.Align.START)
                        lbl.add_css_class("dim-label")
                        inst_vbox.append(lbl)

                        for inst in inst_list:
                            inst_label = Gtk.Label(label=inst)
                            inst_label.set_ellipsize(Pango.EllipsizeMode.END)
                            inst_label.set_lines(1)
                            inst_label.set_max_width_chars(20)
                            inst_label.set_xalign(0)
                            inst_label.set_tooltip_text(inst)

                            btn = Gtk.CheckButton()
                            btn.set_child(inst_label)
                            btn.set_group(hidden_none_btn)
                            btn.connect("toggled", on_btn_toggled, "Instructor", inst)
                            inst_vbox.append(btn)

                            if not has_activated_instructor and saved_pref["type"] == "Instructor" and saved_pref["value"] == inst:
                                btn.set_active(True)
                                has_activated_instructor = True

                    append_instructor_group("Lecture Instructors", lec_inst_list)
                    append_instructor_group("Lab Instructors", lab_inst_list)
                    append_instructor_group("Tutorial Instructors", tut_inst_list)

                if has_sections:
                    sec_scroll = Gtk.ScrolledWindow()
                    sec_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
                    sec_scroll.set_propagate_natural_height(True)
                    sec_scroll.set_max_content_height(300)

                    sec_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    sec_vbox.set_margin_top(6)
                    sec_vbox.set_margin_bottom(12)
                    sec_vbox.set_margin_start(12)
                    sec_vbox.set_margin_end(12)
                    sec_scroll.set_child(sec_vbox)

                    stack.add_titled(sec_scroll, "sections", "Sections")
                    stack.get_page(sec_scroll).set_icon_name("view-list-symbolic")

                    lbl = Gtk.Label(label="<b>Sections</b>", use_markup=True)
                    lbl.set_halign(Gtk.Align.START)
                    lbl.add_css_class("dim-label")
                    sec_vbox.append(lbl)

                    for sec in sec_list:
                        sec_label = Gtk.Label(label=sec)
                        sec_label.set_ellipsize(Pango.EllipsizeMode.END)
                        sec_label.set_lines(1)
                        sec_label.set_max_width_chars(20)
                        sec_label.set_xalign(0)
                        sec_label.set_tooltip_text(sec)

                        btn = Gtk.CheckButton()
                        btn.set_child(sec_label)
                        btn.set_group(hidden_none_btn)
                        btn.connect("toggled", on_btn_toggled, "Section", sec)
                        sec_vbox.append(btn)

                        if saved_pref["type"] == "Section" and saved_pref["value"] == sec:
                            btn.set_active(True)

                if saved_pref["type"] == "Neither":
                    hidden_none_btn.set_active(True)
                    menubutton.set_icon_name("funnel-outline-symbolic")
                    stack.set_visible_child_name("none")
                else:
                    menubutton.set_icon_name("funnel-symbolic")
                    if saved_pref["type"] == "Instructor":
                        stack.set_visible_child_name("instructors")
                    elif saved_pref["type"] == "Section":
                        stack.set_visible_child_name("sections")

                def on_stack_page_changed(stk, param, c=course_code, mb=menubutton, hnb=hidden_none_btn):
                    if stk.get_visible_child_name() == "none":
                        hnb.set_active(True)
                        self.course_preferences[c] = {"type": "Neither", "value": ""}
                        mb.set_icon_name("funnel-outline-symbolic")

                stack.connect("notify::visible-child-name", on_stack_page_changed)

            chboxcont.append(menubutton)
            checkbox = Gtk.CheckButton(focusable=False)
            checkbox.connect("toggled", self.on_course_toggled, course_code)

            if course_code in saved_selection:
                checkbox.set_active(True)

            chboxcont.append(checkbox)

        self._saved_selected_courses = set()

    def on_course_toggled(self, checkbox, course_code):
        if checkbox.get_active():
            if len(self.selected_courses) < 9:
                self.selected_courses.add(course_code)
            else:
                checkbox.set_active(False)
                self.show_error_dialog("You Can't Select More Than 7 Courses")
        else:
            self.selected_courses.discard(course_code)

        self.listbox.invalidate_sort()

        print("Selected courses:", self.selected_courses)

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
        self.numcourses.set_fraction(num/7)
        animation.play()

    def on_generate_clicked(self, _button):
        if not self.json_path or not self.selected_courses:
            self.show_error_dialog("Please Restart The App To Refetch The Courses Or Make Sure You Have At Least One Course Selected.")
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
            if pref and pref["type"] == "Instructor" and pref["value"]:
                pref_insts.append(f"{c}:{pref['value']}")
            elif pref and pref["type"] == "Section" and pref["value"]:
                pref_secs.append(f"{c}:{pref['value']}")

        if pref_insts:
            cmd.extend(['--preferred-instructors', "|".join(pref_insts)])
        if pref_secs:
            cmd.extend(['--specific-sections', "|".join(pref_secs)])

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

        opt_metric_map = {
            0: "compact",
            1: "few-days",
            2: "balanced-days",
            3: "consistent-times"
        }
        opt_metric = opt_metric_map.get(self.tuner.get_selected(), "compact")
        cmd.extend(['--optimize-by', opt_metric])

        sec_metric_map = {
            0: "none",
            1: "compact",
            2: "few-days",
            3: "balanced-days",
            4: "consistent-times"
        }
        sec_metric = sec_metric_map.get(self.sec_tuner.get_selected(), "none")
        if sec_metric != "none":
            cmd.extend(['--secondary-optimize-by', sec_metric])

        print(f"Running command: {' '.join(cmd)}")

        target_width = max(self.get_width(), 1175)
        target_height = max(self.get_height(), 750)
        self.set_default_size(target_width, target_height)

        self.start_scheduler_thread(cmd)

    def on_compare_clicked(self, _button):
        if not self.schedules or self.current_schedule_idx >= len(self.schedules):
            return

        current_sched = self.schedules[self.current_schedule_idx]

        current_courses = {}
        for m in current_sched['meetings']:
            c = m['course']
            if c not in current_courses:
                current_courses[c] = set()
            current_courses[c].add(m['id'])

        dialog = Adw.Dialog(title="Compare & Reschedule")
        dialog.set_content_width(450)
        dialog.set_content_height(500)

        toolbar = Adw.ToolbarView()
        dialog.set_child(toolbar)

        header = Adw.HeaderBar()
        header.add_css_class("flat")
        toolbar.add_top_bar(header)

        search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic")
        search_btn.set_tooltip_text("Search Courses")
        header.pack_start(search_btn)

        search_bar = Gtk.SearchBar()
        search_entry = Gtk.SearchEntry(placeholder_text="Filter courses...")
        search_bar.set_child(search_entry)
        search_bar.set_key_capture_widget(dialog)
        search_bar.connect_entry(search_entry)
        toolbar.add_top_bar(search_bar)

        search_btn.connect("toggled", lambda btn: search_bar.set_search_mode(btn.get_active()))
        search_bar.connect("notify::search-mode-enabled", lambda sb, *_: search_btn.set_active(sb.get_search_mode()))

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(18)
        vbox.set_margin_start(45)
        vbox.set_margin_end(45)

        toolbar.set_content(vbox)

        def sort_compare_courses(row1, row2):
            c1 = getattr(row1, 'course_code', '')
            c2 = getattr(row2, 'course_code', '')
            cb1 = getattr(row1, 'checkbox', None)
            cb2 = getattr(row2, 'checkbox', None)
            s1 = cb1.get_active() if cb1 else False
            s2 = cb2.get_active() if cb2 else False
            if s1 != s2:
                return -1 if s1 else 1
            if c1 < c2: return -1
            if c1 > c2: return 1
            return 0

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        list_box.set_margin_top(5)
        list_box.set_margin_bottom(5)
        list_box.set_margin_start(5)
        list_box.set_margin_end(5)
        list_box.set_sort_func(sort_compare_courses)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(list_box)
        vbox.append(scrolled)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_homogeneous(True)
        btn_box.set_margin_top(10)
        vbox.append(btn_box)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.add_css_class("pill")
        btn_box.append(cancel_btn)

        generate_btn = Gtk.Button(label="Generate")
        generate_btn.add_css_class("suggested-action")
        generate_btn.add_css_class("pill")
        btn_box.append(generate_btn)

        widgets_dict = {}
        rows = []

        sorted_keys = sorted(self.data.keys(), key=lambda c: (c not in current_courses, c))

        for course_code in sorted_keys:
            row = Adw.ActionRow(title=course_code)
            row.course_code = course_code

            suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            suffix_box.set_valign(Gtk.Align.CENTER)

            lock_btn = Gtk.ToggleButton()
            lock_btn.add_css_class("flat")
            lock_btn.set_valign(Gtk.Align.CENTER)

            def update_lock_icon(btn, *args):
                if btn.get_active():
                    btn.set_icon_name("changes-prevent-symbolic")
                    btn.set_tooltip_text("Locked: Keep this exact section.")
                else:
                    btn.set_icon_name("changes-allow-symbolic")
                    btn.set_tooltip_text("Unlocked: Allow other sections.")

            update_lock_icon(lock_btn)
            lock_btn.connect("notify::active", update_lock_icon)

            checkbox = Gtk.CheckButton()
            checkbox.set_valign(Gtk.Align.CENTER)
            row.checkbox = checkbox

            suffix_box.append(lock_btn)
            suffix_box.append(checkbox)
            row.add_suffix(suffix_box)
            row.set_activatable_widget(checkbox)

            is_current = course_code in current_courses

            if is_current:
                checkbox.set_active(True)
                lock_btn.set_active(True)
                lock_btn.set_visible(True)
            else:
                checkbox.set_active(False)
                lock_btn.set_active(False)
                lock_btn.set_visible(False)

            def on_checkbox_toggled(cb, *args, btn=lock_btn, curr=is_current):
                if curr:
                    btn.set_visible(cb.get_active())
                else:
                    btn.set_visible(False)
                list_box.invalidate_sort()

            checkbox.connect("notify::active", on_checkbox_toggled)

            list_box.append(row)
            widgets_dict[course_code] = {"checkbox": checkbox, "lock_btn": lock_btn}
            rows.append((row, course_code))

        def on_search_changed(entry):
            text = entry.get_text().casefold()
            for row, course in rows:
                if not text or text in course.casefold():
                    row.set_visible(True)
                else:
                    row.set_visible(False)

        search_entry.connect("search-changed", on_search_changed)

        def on_cancel(btn):
            dialog.close()

        def on_generate(btn):
            dialog.close()
            self.execute_compare_generation(widgets_dict, current_courses)

        cancel_btn.connect("clicked", on_cancel)
        generate_btn.connect("clicked", on_generate)

        dialog.present()

    def execute_compare_generation(self, widgets_dict, current_courses):
        temp_selected = set()
        temp_section_locks = {}

        for course, widgets in widgets_dict.items():
            checkbox = widgets["checkbox"]
            lock_btn = widgets["lock_btn"]

            if not checkbox.get_active():
                continue

            temp_selected.add(course)
            if course in current_courses and lock_btn.get_active():
                temp_section_locks[course] = current_courses[course]

        if not temp_selected:
            self.show_error_dialog("Please Select At Least One Course.")
            return

        scheduler_path = shutil.which('scheduler')
        if not scheduler_path:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            exe_name = 'scheduler.exe' if os.name == 'nt' else 'scheduler'
            scheduler_path = os.path.join(project_root, 'build', 'c++', exe_name)

        cmd = [
            scheduler_path,
            '--json-file', self.json_path,
            '--courses', ",".join(temp_selected)
        ]

        pref_secs = []
        for c in temp_selected:
            if c in temp_section_locks:
                for sec_id in temp_section_locks[c]:
                    pref_secs.append(f"{c}:{sec_id}")

        if pref_secs:
            cmd.extend(['--specific-sections', "|".join(pref_secs)])

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

        opt_metric_map = {
            0: "compact",
            1: "few-days",
            2: "balanced-days",
            3: "consistent-times"
        }
        opt_metric = opt_metric_map.get(self.tuner.get_selected(), "compact")
        cmd.extend(['--optimize-by', opt_metric])

        sec_metric_map = {
            0: "none",
            1: "compact",
            2: "few-days",
            3: "balanced-days",
            4: "consistent-times"
        }
        sec_metric = sec_metric_map.get(self.sec_tuner.get_selected(), "none")
        if sec_metric != "none":
            cmd.extend(['--secondary-optimize-by', sec_metric])

        print(f"Running command: {' '.join(cmd)}")
        self.start_scheduler_thread(cmd)

    def start_scheduler_thread(self, cmd):
        self.schedules = []
        self.current_schedule_idx = 0

        if self.generation_process:
            try:
                self.generation_process.terminate()
                self.generation_process.wait(timeout=1.0)
            except Exception:
                pass

        child = self.schedule.get_first_child()
        while child:
            self.schedule.remove(child)
            child = self.schedule.get_first_child()

        spinner = Gtk.Spinner(spinning=True)
        spinner.set_size_request(48, 48)
        spinner.set_halign(Gtk.Align.CENTER)
        spinner.set_valign(Gtk.Align.CENTER)
        spinner.set_hexpand(True)
        spinner.set_vexpand(True)
        self.schedule.attach(spinner, 0, 0, 1, 1)

        self.schedule_view_inner.set_title("Generating Schedules...")

        try:
            if self.nav_view.get_visible_page() != self.schedule_view:
                self.nav_view.push(self.schedule_view)
        except AttributeError:
            self.nav_view.push(self.schedule_view)

        self.show_sidebar_button.set_visible(True)
        self.back_button.set_visible(True)

        self._update_sidebar_course_filters()
        self._update_navigation_buttons()

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
            if not line:
                continue
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

        new_top = self.schedules[0]

        if self.current_schedule_idx == 0 and old_top != new_top:
            self.draw_schedule_index(0)

        self.schedule_view_inner.set_title(f"Found {len(self.schedules)} Schedules...")
        self._update_navigation_buttons()

    def _on_generation_complete(self, ret_code, stderr):
        if ret_code != 0:
            self.show_error_dialog(f"Error running scheduler: {stderr}")
            self.schedule_view_inner.set_title("Generation Failed")
            return

        if not self.schedules:
            self.draw_schedule_index(0)
        else:
            self.schedule_view_inner.set_title(f"Schedule {self.current_schedule_idx + 1} of {len(self.schedules)}")

        self.generation_process = None

    def draw_schedule_index(self, index):
        child = self.schedule.get_first_child()
        while child:
            self.schedule.remove(child)
            child = self.schedule.get_first_child()

        if not self.schedules or index >= len(self.schedules):
            self.schedule_view_inner.set_title("")
            self.schedule.set_margin_top(0)
            self.schedule.set_margin_bottom(0)
            self.schedule.set_margin_start(0)
            self.schedule.set_margin_end(0)
            self.schedule.set_valign(Gtk.Align.FILL)

            status = Adw.StatusPage()
            status.set_title("No Schedules Found")
            status.set_description("Could not find any conflict-free schedule matching your current constraints. Try removing some filters or constraints.")
            status.set_icon_name("system-search-symbolic")
            status.set_hexpand(True)
            status.set_vexpand(True)
            status.set_size_request(-1,330)

            self.schedule.attach(status, 0, 0, 1, 1)
            self._update_navigation_buttons()
            return

        self.schedule_view_inner.set_title(f"Schedule {index + 1} of {len(self.schedules)}")
        schedule_data = self.schedules[index]

        self.schedule.set_row_spacing(0)
        self.schedule.set_column_spacing(10)
        self.schedule.set_margin_top(12)
        self.schedule.set_margin_bottom(12)
        self.schedule.set_margin_start(12)
        self.schedule.set_margin_end(12)

        self.schedule.set_valign(Gtk.Align.START)
        self.schedule.set_hexpand(True)
        self.schedule.set_halign(Gtk.Align.FILL)

        for i in range(13):
            hour = 8 + i
            time_str = f"{hour:02d}:30"
            label = Gtk.Label(label=time_str)
            label.add_css_class("dim-label")
            label.set_halign(Gtk.Align.END)
            label.set_valign(Gtk.Align.START)
            label.set_margin_end(6)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_valign(Gtk.Align.START)
            if i == 12:
                box.set_size_request(60, 1)
            else:
                box.set_size_request(60, 60)

            box.append(label)
            self.schedule.attach(box, 0, i + 1, 1, 1)

        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        day_overlays = {}

        for col_idx, day in enumerate(days, start=1):
            day_label = Gtk.Label()
            day_label.set_markup(f"<b>{day}</b>")
            day_label.set_margin_bottom(12)
            day_label.set_halign(Gtk.Align.CENTER)
            self.schedule.attach(day_label, col_idx, 0, 1, 1)

            overlay = Gtk.Overlay()
            dummy = Gtk.Box()
            dummy.set_size_request(140, 12 * 60)
            overlay.set_child(dummy)

            overlay.set_hexpand(True)
            overlay.set_halign(Gtk.Align.FILL)
            overlay.set_valign(Gtk.Align.START)

            self.schedule.attach(overlay, col_idx, 1, 1, 12)
            day_overlays[col_idx] = overlay

        START_MINUTES = 8 * 60 + 30
        PX_PER_MINUTE = 1.0

        for meeting in schedule_data["meetings"]:
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
            card.set_size_request(-1, height)

            card.set_halign(Gtk.Align.FILL)
            card.set_valign(Gtk.Align.START)
            card.set_margin_top(start_y)

            full_title = meeting['course']
            course_data = self.data.get(meeting['course'], [])
            if course_data:
                full_title = course_data[0].get("fullTitle", meeting['course'])

            tooltip_text = f"{full_title} ({meeting['id']})\n" \
                           f"Type: {meeting['type']}\n" \
                           f"Time: {meeting['start']//60:02d}:{meeting['start']%60:02d} - {meeting['end']//60:02d}:{meeting['end']%60:02d}\n" \
                           f"Instructor: {meeting['instructor']}\n" \
                           f"Location: {meeting['location']}\n" \
                           f"Seats Left: {meeting['seats']}"
            card.set_tooltip_text(tooltip_text)

            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            inner.set_homogeneous(True)
            inner.set_valign(Gtk.Align.CENTER)
            inner.set_margin_top(4)
            inner.set_margin_bottom(4)
            inner.set_margin_start(6)
            inner.set_margin_end(6)
            card.append(inner)

            left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            left_col.set_hexpand(True)
            left_col.set_halign(Gtk.Align.FILL)
            inner.append(left_col)

            right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            right_col.set_hexpand(True)
            right_col.set_halign(Gtk.Align.FILL)
            inner.append(right_col)

            title = Gtk.Label()
            title.set_markup(f"<b>{meeting['course']}</b>")
            title.set_ellipsize(3)
            title.set_halign(Gtk.Align.START)
            title.add_css_class("caption")
            left_col.append(title)

            subtitle = Gtk.Label(label=f"{meeting['type']} ({meeting['id']})")
            subtitle.set_ellipsize(2)
            subtitle.add_css_class("dim-label")
            subtitle.add_css_class("caption")
            subtitle.set_halign(Gtk.Align.START)
            left_col.append(subtitle)

            if height < 40:
                subtitle.set_visible(False)

            raw_location = meeting['location']
            short_location = raw_location.split(',')[-1].strip() if ',' in raw_location else raw_location
            if "Room" not in short_location:
                short_location = "Room " + short_location

            room = Gtk.Label(label=short_location)
            room.set_halign(Gtk.Align.START)
            room.add_css_class("caption")

            if height > 80:
                room.set_wrap(True)
                room.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                room.set_lines(2)

            room.set_ellipsize(3)
            left_col.append(room)

            if height < 60:
                room.set_visible(False)

            instructor = Gtk.Label(label=meeting['instructor'])
            instructor.set_halign(Gtk.Align.START)
            instructor.set_valign(Gtk.Align.START)
            instructor.add_css_class("caption")
            instructor.set_wrap(True)
            instructor.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            if height > 110:
                instructor.set_lines(4)
            else:
                instructor.set_lines(2)
            instructor.set_ellipsize(3)
            right_col.append(instructor)

            overlay.add_overlay(card)

        self._update_navigation_buttons()
