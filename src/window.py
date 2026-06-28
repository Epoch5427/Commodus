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
    search_toggle = Gtk.Template.Child() # Mapped Search Toggle
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
    start_hours = Gtk.Template.Child()
    start_minutes = Gtk.Template.Child()
    end_hours = Gtk.Template.Child()
    end_minutes = Gtk.Template.Child()
    prefs_dialog = Gtk.Template.Child()
    dm_switch = Gtk.Template.Child()
    wrap_switch = Gtk.Template.Child()
    global_generate = Gtk.Template.Child()
    delete_save = Gtk.Template.Child()
    local_load_switch = Gtk.Template.Child()
    fpickerbutton = Gtk.Template.Child()
    generate = Gtk.Template.Child()
    action_bar = Gtk.Template.Child()
    alt_gen = Gtk.Template.Child()
    tuner = Gtk.Template.Child()
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
    network_status = Gtk.Template.Child() # Mapped Spinner

    # Sidebar components mapped
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

        self.searchbar.set_visible(False)
        self.show_sidebar_button.set_visible(False)
        self.search_toggle.set_visible(False)

        self.start_hours.set_value(0)
        self.start_minutes.set_value(0)
        self.end_hours.set_value(0)
        self.end_minutes.set_value(0)

        self.delete_save.connect("activated", self._on_delete_save_clicked)

        # Connect signals for dynamic opacity when set to 00:00
        self.start_hours.connect("value-changed", self._update_time_opacity)
        self.start_minutes.connect("value-changed", self._update_time_opacity)
        self.end_hours.connect("value-changed", self._update_time_opacity)
        self.end_minutes.connect("value-changed", self._update_time_opacity)

        self.nav_view.connect("popped", self._on_nav_popped)
        self.back_button.connect("clicked", lambda *_: self.nav_view.pop())
        #self.network_banner.connect("button-clicked", lambda *_: self._fetch_database_async())

        # Search Toggle Sync
        self.search_toggle.connect("toggled", lambda btn: self.searchbar.set_search_mode(btn.get_active()))
        self.searchbar.connect("notify::search-mode-enabled", lambda sb, *_: self.search_toggle.set_active(sb.get_search_mode()))

        self.data={}

        # Key controller for cycling schedules
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_ctrl)


        def filter(row):
            match = re.search(self.searchentry.get_text(), row.get_title(), re.IGNORECASE)
            if match:
                self.results_count += 1
            return match


        self.listbox.set_filter_func(filter)


        def on_search_changed(_search_widget):
            self.results_count = -1
            self.listbox.invalidate_filter()
            if self.results_count == -1:
                self.stack.set_visible_child(self.status_page)
                self.listbox.set_opacity(0)
            elif self.searchbar.get_search_mode():
                self.stack.set_visible_child(self.search_page)
                self.listbox.set_opacity(100)


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

        # Connect alt_gen to the smart toggle logic
        self.alt_gen.connect("clicked", self.on_alt_gen_clicked)

        self.searchentry.connect("search-changed", on_search_changed)
        self.carousel.connect("page-changed", self.on_page_changed)
        self.search_page.connect("edge-overshot", self.on_edge_overshot)

        # Save state on close
        self.connect("close-request", self.on_close_request)

        # Apply visual updates, load saved settings, and build sidebar
        self._update_time_opacity()
        self.load_settings()
        if self.local_load_switch.get_active():
            self.fpickerbutton.set_visible(True)

        self._build_sidebar_controls()

        # Trigger automatic database download from GitHub
        self._fetch_database_async()

    def _on_nav_popped(self, *args):
        self.show_sidebar_button.set_visible(False)
        self.show_sidebar_button.set_active(False)
        self.back_button.set_visible(False)

    def _fetch_database_async(self):
        self.network_banner.set_revealed(False)
        self.network_status.set_opacity(1)
        self.network_status.set_visible(True)

        def fetch_task():
            url = "https://raw.githubusercontent.com/Epoch5427/Commodus/app-data/NU_course_data.json"
            try:
                # Add a dummy User-Agent as some raw hosts block vanilla python urllib
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    content = response.read().decode('utf-8')

                    # Cache the downloaded JSON locally so the C++ backend can read it
                    cache_dir = os.path.join(GLib.get_user_cache_dir(), "commodus")
                    os.makedirs(cache_dir, exist_ok=True)
                    local_path = os.path.join(cache_dir, "database.json")

                    with open(local_path, 'w', encoding='utf-8') as f:
                        f.write(content)

                    # Update UI on main thread safely
                    GLib.idle_add(self._on_fetch_success, local_path, content)
            except Exception as e:
                print(f"Failed to download database: {e}")
                GLib.idle_add(self._on_fetch_error, str(e))

        threading.Thread(target=fetch_task, daemon=True).start()

    def _on_fetch_success(self, local_path, content):
        self.network_status.set_visible(False)
        self.fpickerbutton.set_sensitive(True) # Moved safely to the main thread!

        # Create the icon if it doesn't exist yet
        if not hasattr(self, "check_icon"):
            self.check_icon = Gtk.Image()
            self.check_icon.set_pixel_size(24)
            self.check_icon.set_margin_top(18)
            self.network_status.get_parent().append(self.check_icon)

        # Always update its properties so it switches properly on a retry
        self.check_icon.set_from_icon_name("circle-checkmark-symbolic")
        self.check_icon.set_tooltip_text("Online Database Retrieved Successfully")
        self.check_icon.remove_css_class("error")
        self.check_icon.remove_css_class("warning")
        self.check_icon.add_css_class("success")

        self.check_icon.set_visible(True)
        GLib.timeout_add(1000, lambda: self.carousel.scroll_to(self.courses_page, True))

        try:
            self.data = json.loads(content)
            self.json_path = local_path
            self.populate_listbox()
        except json.JSONDecodeError:
            self.show_error_dialog("The downloaded database is corrupted or invalid JSON.")

        return False # Removes the idle callback

    def _on_fetch_error(self, err_msg):
        self.network_status.set_visible(False)
        self.network_banner.set_revealed(True)

        # Create the icon if it doesn't exist yet
        if not hasattr(self, "check_icon"):
            self.check_icon = Gtk.Image()
            self.check_icon.set_pixel_size(24)
            self.check_icon.set_margin_top(18)
            self.network_status.get_parent().append(self.check_icon)

        self.check_icon.remove_css_class("success")

        if self.json_path == None:
            self.check_icon.set_from_icon_name("circle-x-symbolic")
            self.check_icon.set_tooltip_text("Failed To Retrieve Online Database")
            self.check_icon.remove_css_class("warning")
            self.check_icon.add_css_class("error")

            self.network_banner.set_title("Failed to retrieve online database")
            self.fpickerbutton.set_sensitive(True)
        else:
            self.check_icon.set_from_icon_name("circle-checkmark-symbolic")
            self.check_icon.set_tooltip_text("Failed To Retrieve Online Database. Using Cached Version")
            self.check_icon.remove_css_class("error")
            self.check_icon.add_css_class("warning")

            self.network_banner.set_title("Failed to retrieve online database. Using Cached Version")

        self.check_icon.set_visible(True)
        return False

    def on_alt_gen_clicked(self, btn):
        if self.carousel.get_position() == 1.0:
            # We are on the Select Courses page, clear all!
            self.selected_courses.clear()
            self.course_preferences.clear()
            self.numcourses.set_text("0/7")
            self.numcourses.set_fraction(0.0)
            self.populate_listbox()
        else:
            # We are on another page, generate schedule
            self.on_generate_clicked(btn)

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

        prev_btn = Gtk.Button(icon_name="go-previous-symbolic")
        prev_btn.set_tooltip_text("Go To Previous Schedule (Left Arrow Key)")
        prev_btn.add_css_class("circular")
        prev_btn.connect("clicked", self._on_previous_clicked)
        if self.wrap_switch.get_active():
            prev_btn.set_sensitive(True)
        else:
            prev_btn.set_sensitive(False)
        self.schedule_sidebar_buttons.append(prev_btn)

        # 1. Copy Schedule Button
        copy_btn = Gtk.Button(icon_name="clipboard-symbolic")
        copy_btn.add_css_class("linked")
        copy_btn.set_tooltip_text("Copy Schedule To Clipboard")
        copy_btn.connect("clicked", self.on_copy_schedule_clicked)
        self.schedule_sidebar_buttons.append(copy_btn)

        compare_btn = Gtk.Button(icon_name="loop-arrow-symbolic")
        compare_btn.set_tooltip_text("Compare and Reschedule. This feature helps you create schedules that align with your friends even if you don't take the same courses")
        compare_btn.add_css_class("linked")
        compare_btn.connect("clicked", self.on_compare_clicked)
        self.schedule_sidebar_buttons.append(compare_btn)

        import_btn = Gtk.Button(icon_name="folder-download-symbolic")
        import_btn.set_tooltip_text("Import Schedule")
        import_btn.add_css_class("linked")
        import_btn.connect("clicked", self.on_import_clicked)
        self.schedule_sidebar_buttons.append(import_btn)

        next_btn = Gtk.Button(icon_name="go-next-symbolic")
        next_btn.set_tooltip_text("Go To Next Schedule (Right Arrow Key)")
        next_btn.add_css_class("circular")
        next_btn.connect("clicked", self._on_next_clicked)
        self.schedule_sidebar_buttons.append(next_btn)

        # 2. Course Filters Group
        self.sidebar_courses_group = Adw.PreferencesGroup(title="Course Filters")
        self.sidebar_courses_group.set_margin_top(0)
        self.sidebar_courses_group.set_margin_start(12)
        self.sidebar_courses_group.set_margin_end(12)
        self.schedule_sidebar_content.append(self.sidebar_courses_group)

        # 3. Constraints Group
        pref_group = Adw.PreferencesGroup(title="Filters and Tuning")
        pref_group.set_margin_top(12)
        pref_group.set_margin_start(12)
        pref_group.set_margin_end(12)
        self.schedule_sidebar_content.append(pref_group)

        # Exclude Days Expander
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

        # Bidirectional sync between main menu checks and sidebar checks
        for day_name, source_check in days_mapping:
            check = Gtk.CheckButton(label=day_name)
            source_check.bind_property("active", check, "active", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
            days_box.append(check)

        days_exp.add_row(days_box)
        pref_group.add(days_exp)

        # Time Boundary Expander
        time_exp = Adw.ExpanderRow(title="Time Boundary")

        # Start Time
        start_row = Adw.ActionRow(title="Start Time")
        start_h_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=23, step_increment=1))
        start_h_spin.set_valign(Gtk.Align.CENTER)
        self.start_hours.bind_property("value", start_h_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.start_hours.bind_property("opacity", start_h_spin, "opacity", GObject.BindingFlags.SYNC_CREATE)

        start_m_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=59, step_increment=15))
        start_m_spin.set_valign(Gtk.Align.CENTER)
        self.start_minutes.bind_property("value", start_m_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.start_minutes.bind_property("opacity", start_m_spin, "opacity", GObject.BindingFlags.SYNC_CREATE)

        start_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        start_box.append(start_h_spin)
        start_box.append(Gtk.Label(label=":"))
        start_box.append(start_m_spin)
        start_row.add_suffix(start_box)
        time_exp.add_row(start_row)

        # End Time
        end_row = Adw.ActionRow(title="End Time")
        end_h_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=23, step_increment=1))
        end_h_spin.set_valign(Gtk.Align.CENTER)
        self.end_hours.bind_property("value", end_h_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.end_hours.bind_property("opacity", end_h_spin, "opacity", GObject.BindingFlags.SYNC_CREATE)

        end_m_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(lower=0, upper=59, step_increment=15))
        end_m_spin.set_valign(Gtk.Align.CENTER)
        self.end_minutes.bind_property("value", end_m_spin, "value", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.end_minutes.bind_property("opacity", end_m_spin, "opacity", GObject.BindingFlags.SYNC_CREATE)

        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        end_box.append(end_h_spin)
        end_box.append(Gtk.Label(label=":"))
        end_box.append(end_m_spin)
        end_row.add_suffix(end_box)
        time_exp.add_row(end_row)

        pref_group.add(time_exp)

        # Exclude Full Switch
        self.sb_ls_switch = Adw.SwitchRow(title="Exclude Full Classes")
        self.ls_switch.bind_property("active", self.sb_ls_switch, "active", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        pref_group.add(self.sb_ls_switch)

        # Prioritize ComboRow
        self.sb_tuner = Adw.ComboRow(title="Prioritize")
        self.sb_tuner.set_model(Gtk.StringList.new(["Compact Days", "Fewer Days", "Shorter Days", "Consistent Days"]))
        self.tuner.bind_property("selected", self.sb_tuner, "selected", GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        pref_group.add(self.sb_tuner)

        # Generate Button for Sidebar
        sb_gen_btn = Gtk.Button(label="Generate Schedules")
        sb_gen_btn.add_css_class("suggested-action")
        sb_gen_btn.add_css_class("pill")
        sb_gen_btn.set_margin_top(12)
        sb_gen_btn.set_margin_start(12)
        sb_gen_btn.set_margin_end(12)
        sb_gen_btn.connect("clicked", self.on_generate_clicked)
        self.schedule_sidebar_content.append(sb_gen_btn)

    def _update_sidebar_course_filters(self):
        # Explicitly remove tracked rows safely rather than querying GTK's hidden layout children
        for row in self._sidebar_course_rows:
            self.sidebar_courses_group.remove(row)
        self._sidebar_course_rows.clear()

        # Re-populate dynamically for each selected course
        for course_code in sorted(self.selected_courses):
            expander = Adw.ExpanderRow(title=course_code)
            sections_list = self.data.get(course_code, [])

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            vbox.set_margin_top(12)
            vbox.set_margin_bottom(12)
            vbox.set_margin_start(12)
            vbox.set_margin_end(12)
            expander.add_row(vbox)

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

            none_btn = Gtk.CheckButton(label="None")
            vbox.append(none_btn)

            def on_btn_toggled(btn, pref_type, val, c=course_code):
                if btn.get_active():
                    self.course_preferences[c] = {"type": pref_type, "value": val}

            none_btn.connect("toggled", on_btn_toggled, "Neither", "")

            saved_pref = self.course_preferences.get(course_code, {"type": "Neither", "value": ""})
            if saved_pref["type"] == "Neither":
                none_btn.set_active(True)

            has_activated_instructor = False

            def append_instructor_group(title, inst_list):
                nonlocal has_activated_instructor
                if not inst_list:
                    return

                vbox.append(Gtk.Separator(margin_top=4, margin_bottom=4))
                lbl = Gtk.Label(label=f"<b>{title}</b>", use_markup=True)
                lbl.set_halign(Gtk.Align.START)
                lbl.add_css_class("dim-label")
                vbox.append(lbl)

                for inst in inst_list:
                    btn = Gtk.CheckButton(label=inst)
                    btn.set_group(none_btn)
                    btn.connect("toggled", on_btn_toggled, "Instructor", inst)
                    vbox.append(btn)

                    if not has_activated_instructor and saved_pref["type"] == "Instructor" and saved_pref["value"] == inst:
                        btn.set_active(True)
                        has_activated_instructor = True

            append_instructor_group("Lecture Instructors", lec_inst_list)
            append_instructor_group("Lab Instructors", lab_inst_list)
            append_instructor_group("Tutorial Instructors", tut_inst_list)

            if sec_list:
                vbox.append(Gtk.Separator(margin_top=4, margin_bottom=4))
                lbl = Gtk.Label(label="<b>Sections</b>", use_markup=True)
                lbl.set_halign(Gtk.Align.START)
                lbl.add_css_class("dim-label")
                vbox.append(lbl)

                for sec in sec_list:
                    btn = Gtk.CheckButton(label=sec)
                    btn.set_group(none_btn)
                    btn.connect("toggled", on_btn_toggled, "Section", sec)
                    vbox.append(btn)

                    if saved_pref["type"] == "Section" and saved_pref["value"] == sec:
                        btn.set_active(True)

            self.sidebar_courses_group.add(expander)
            self._sidebar_course_rows.append(expander)

    def on_copy_schedule_clicked(self, btn):
        if not self.schedules or self.current_schedule_idx >= len(self.schedules):
            return

        sched = self.schedules[self.current_schedule_idx]

        days_map = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
        lines = []

        # Sort by Course -> Type -> ID
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

        # Provide visual feedback on button
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

        # Instruction Label
        lbl = Gtk.Label(label="Paste your copied schedule text below:")
        lbl.set_halign(Gtk.Align.START)
        vbox.append(lbl)

        # Text View for pasting
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        textview = Gtk.TextView()
        textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        textview.add_css_class("card")
        scrolled.set_child(textview)
        vbox.append(scrolled)

        # Buttons
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

            # Split off the instructor part (right of the pipe)
            left, right = line.split("|", 1)
            tokens = left.strip().split()

            if not tokens:
                continue

            course = tokens[0]
            new_selected.add(course)

            # Look for the Lecture to lock down the core section path
            if len(tokens) > 2 and tokens[1] == "Lecture":
                section = tokens[2]
                new_prefs[course] = {"type": "Section", "value": section}

        if not new_selected:
            self.show_error_dialog("Could not parse any courses from the provided text.")
            return False

        # Apply parsed data
        self.selected_courses = new_selected
        self.course_preferences = new_prefs

        # Trigger generation immediately
        self.on_generate_clicked(None)
        # Clear preferences so specific sections/instructors are set to None
        self.course_preferences.clear()
        # Update UI Counters
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
            "start_hours": self.start_hours.get_value_as_int(),
            "start_minutes": self.start_minutes.get_value_as_int(),
            "end_hours": self.end_hours.get_value_as_int(),
            "end_minutes": self.end_minutes.get_value_as_int(),
            "exclude_full": self.ls_switch.get_active(),
            "tuner": self.tuner.get_selected(),
            "dark_mode": self.dm_switch.get_active(),
            "wrap_mode": self.wrap_switch.get_active(),
            "global_mode": self.global_generate.get_active(),
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

            self.start_hours.set_value(settings.get("start_hours", 0))
            self.start_minutes.set_value(settings.get("start_minutes", 0))
            self.end_hours.set_value(settings.get("end_hours", 0))
            self.end_minutes.set_value(settings.get("end_minutes", 0))

            self.ls_switch.set_active(settings.get("exclude_full", True))
            self.tuner.set_selected(settings.get("tuner", 0))
            self.dm_switch.set_active(settings.get("dark_mode", False))
            self.wrap_switch.set_active(settings.get("wrap_mode", False))
            self.global_generate.set_active(settings.get("global_mode", False))
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
                if self.global_generate.get_active():
                    self.action_bar.set_revealed(True)

        except Exception as e:
            print(f"Error loading settings: {e}")

    def _on_delete_save_clicked(self, _button):
        path = os.path.join(GLib.get_user_config_dir(), "commodus", "settings.json")
        if os.path.exists(path):
            try:
                os.remove(path)

                # Show success dialog
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

        # Complete reset of internal Python state
        self.selected_courses.clear()
        self.course_preferences.clear()
        self._saved_selected_courses.clear()
        self.json_path = None
        self.data = {}
        self.schedules = []
        self.current_schedule_idx = 0

        # Complete reset of all bound UI widgets
        self.start_hours.set_value(0)
        self.start_minutes.set_value(0)
        self.end_hours.set_value(0)
        self.end_minutes.set_value(0)

        self.ls_switch.set_active(False)
        self.tuner.set_selected(0)
        self.dm_switch.set_active(False)
        self.wrap_switch.set_active(False)
        self.global_generate.set_active(False)

        self.checksun.set_active(False)
        self.checkmon.set_active(False)
        self.checktue.set_active(False)
        self.checkwed.set_active(False)
        self.checkthu.set_active(False)
        self.checkfri.set_active(False)
        self.checksat.set_active(False)

        # Clear course counter UI
        self.numcourses.set_text("0/7")
        self.numcourses.set_fraction(0.0)

        # Clear populated lists and views
        self.populate_listbox()
        child = self.schedule.get_first_child()
        while child:
            self.schedule.remove(child)
            child = self.schedule.get_first_child()

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

    def show_error_dialog(self, message):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Error",
            body=message
        )
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.connect("response", lambda d, r: d.close())
        dialog.present()

    def on_key_pressed(self, controller, keyval, keycode, state):
        # Only allow cycling if the user is actively viewing the schedules page
        try:
            if self.nav_view.get_visible_page() != self.schedule_view:
                return False
        except AttributeError:
            pass

        if keyval == Gdk.KEY_Right:
            if self.schedules and self.current_schedule_idx < len(self.schedules) - 1:
                self.current_schedule_idx += 1
                self.draw_schedule_index(self.current_schedule_idx)
            elif self.wrap_switch.get_active() and self.current_schedule_idx == len(self.schedules) - 1:
                self.current_schedule_idx = 0
                self.draw_schedule_index(self.current_schedule_idx)
                return True
        elif keyval == Gdk.KEY_Left:
            if self.schedules and self.current_schedule_idx > 0:
                self.current_schedule_idx -= 1
                self.draw_schedule_index(self.current_schedule_idx)
            elif self.wrap_switch.get_active() and self.current_schedule_idx == 0:
                self.current_schedule_idx = len(self.schedules) - 1
                self.draw_schedule_index(self.current_schedule_idx)
                return True
        return False

    def _update_time_opacity(self, *args):
        start_is_zero = (self.start_hours.get_value_as_int() == 0 and self.start_minutes.get_value_as_int() == 0)
        end_is_zero = (self.end_hours.get_value_as_int() == 0 and self.end_minutes.get_value_as_int() == 0)

        # Dim to 0.5 if disabled (00:00), otherwise fully opaque
        self.start_hours.set_opacity(0.5 if start_is_zero else 1.0)
        self.start_minutes.set_opacity(0.5 if start_is_zero else 1.0)
        self.end_hours.set_opacity(0.5 if end_is_zero else 1.0)
        self.end_minutes.set_opacity(0.5 if end_is_zero else 1.0)

    def on_page_changed(self, carousel, index):
        if index==2:
            self.revealer_slide.set_reveal_child(True)
            self.searchbar.set_visible(False)
            self.search_toggle.set_visible(False)
            self.searchbar.set_key_capture_widget(None)
            self.show_sidebar_button.set_visible(False)
            if self.global_generate.get_active():
                self.action_bar.set_revealed(True)
            else:
                self.action_bar.set_revealed(False)
            self.alt_gen.set_label("Generate Schedule")
            self.alt_gen.remove_css_class("destructive-action")
            self.alt_gen.add_css_class("suggested-action")
        elif index==1:
            self.revealer_slide.set_reveal_child(False)
            self.searchbar.set_visible(True)
            self.search_toggle.set_visible(True)
            self.searchbar.set_key_capture_widget(self) # Typing ANYWHERE opens search instantly!
            self.show_sidebar_button.set_visible(False)
            self.action_bar.set_revealed(True)
            self.alt_gen.set_label("Clear Selection")
            self.alt_gen.remove_css_class("suggested-action")
            self.alt_gen.add_css_class("destructive-action")
        elif index==0:
            self.revealer_slide.set_reveal_child(False)
            self.searchbar.set_visible(False)
            self.search_toggle.set_visible(False)
            self.searchbar.set_key_capture_widget(None)
            self.show_sidebar_button.set_visible(False)
            self.action_bar.set_revealed(False)
            self.alt_gen.set_label("Generate Schedule")
            self.alt_gen.remove_css_class("destructive-action")
            self.alt_gen.add_css_class("suggested-action")
        else:
            self.revealer_slide.set_reveal_child(False)
            self.searchbar.set_visible(False)
            self.search_toggle.set_visible(False)
            self.searchbar.set_key_capture_widget(None)
            self.show_sidebar_button.set_visible(False)
            self.action_bar.set_revealed(False)
            self.alt_gen.set_label("Generate Schedule")
            self.alt_gen.remove_css_class("destructive-action")
            self.alt_gen.add_css_class("suggested-action")

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
        # Clear existing items
        child = self.listbox.get_first_child()
        while child:
            self.listbox.remove(child)
            child = self.listbox.get_first_child()

        # Restore from backup if present (applies heavily on startup)
        saved_selection = self._saved_selected_courses if hasattr(self, '_saved_selected_courses') and self._saved_selected_courses else set(self.selected_courses)

        self.selected_courses.clear()

        for course_code, sections_list in self.data.items():
            fullTitle = course_code
            row = Adw.ActionRow(title=fullTitle)
            self.listbox.append(row)
            chboxcont = Gtk.Box(spacing=10, valign="center")
            row.add_suffix(chboxcont)

            # --- Popover Filtering UI per Row ---
            popover = Gtk.Popover()

            # Setup menubutton early to modify its icon from callbacks
            menubutton = Gtk.MenuButton()
            menubutton.set_valign(Gtk.Align.CENTER)
            menubutton.set_tooltip_text("Filter By Section Or Instructor")
            menubutton.set_popover(popover)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            vbox.set_margin_top(12)
            vbox.set_margin_bottom(12)
            vbox.set_margin_start(12)
            vbox.set_margin_end(12)

            popover.set_child(vbox)

            # 1. Harvest Data First
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

                # Exclude tutorials & labs, only grab sections from lectures
                if subtype == "Lecture" and s_id:
                    sections.add(s_id)

            lec_inst_list = sorted(list(lec_instructors))
            lab_inst_list = sorted(list(lab_instructors))
            tut_inst_list = sorted(list(tut_instructors))
            sec_list = sorted(list(sections))

            # 2. Setup the group logic
            none_btn = Gtk.CheckButton(label="None")
            vbox.append(none_btn)

            def on_btn_toggled(btn, pref_type, val, c=course_code, mb=menubutton):
                if btn.get_active():
                    self.course_preferences[c] = {"type": pref_type, "value": val}
                    # Update icon based on active filter state
                    if pref_type == "Neither":
                        mb.set_icon_name("funnel-outline-symbolic")
                    else:
                        mb.set_icon_name("funnel-symbolic")

            none_btn.connect("toggled", on_btn_toggled, "Neither", "")

            saved_pref = self.course_preferences.get(course_code, {"type": "Neither", "value": ""})

            # Initialize icon states explicitly based on saved config
            if saved_pref["type"] == "Neither":
                none_btn.set_active(True)
                menubutton.set_icon_name("funnel-outline-symbolic")
            else:
                menubutton.set_icon_name("funnel-symbolic")

            # 3. Populate Separated Instructors Lists
            has_activated_instructor = False

            def append_instructor_group(title, inst_list):
                nonlocal has_activated_instructor
                if not inst_list:
                    return

                vbox.append(Gtk.Separator(margin_top=4, margin_bottom=4))
                lbl = Gtk.Label(label=f"<b>{title}</b>", use_markup=True)
                lbl.set_halign(Gtk.Align.START)
                lbl.add_css_class("dim-label")
                vbox.append(lbl)

                for inst in inst_list:
                    btn = Gtk.CheckButton(label=inst)
                    btn.set_group(none_btn) # Grouping makes them mutually exclusive radio buttons!
                    btn.connect("toggled", on_btn_toggled, "Instructor", inst)
                    vbox.append(btn)

                    if not has_activated_instructor and saved_pref["type"] == "Instructor" and saved_pref["value"] == inst:
                        btn.set_active(True)
                        has_activated_instructor = True

            append_instructor_group("Lecture Instructors", lec_inst_list)
            append_instructor_group("Lab Instructors", lab_inst_list)
            append_instructor_group("Tutorial Instructors", tut_inst_list)

            # 4. Populate Sections List
            if sec_list:
                vbox.append(Gtk.Separator(margin_top=4, margin_bottom=4))
                lbl = Gtk.Label(label="<b>Sections</b>", use_markup=True)
                lbl.set_halign(Gtk.Align.START)
                lbl.add_css_class("dim-label")
                vbox.append(lbl)

                for sec in sec_list:
                    btn = Gtk.CheckButton(label=sec)
                    btn.set_group(none_btn) # Mutually exclusive with both Instructors and None
                    btn.connect("toggled", on_btn_toggled, "Section", sec)
                    vbox.append(btn)

                    if saved_pref["type"] == "Section" and saved_pref["value"] == sec:
                        btn.set_active(True)

            # Attach popover button to layout
            chboxcont.append(menubutton)

            checkbox = Gtk.CheckButton(focusable=False)

            # Connect the signal *before* setting active so the list updates itself
            checkbox.connect("toggled", self.on_course_toggled, course_code)

            # Automatically tick if it was in memory
            if course_code in saved_selection:
                checkbox.set_active(True)

            chboxcont.append(checkbox)

        # Consume the saved selected courses so it doesn't persistently override manual toggles
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
            self.show_error_dialog("Please select a JSON file and at least one course.")
            return

        # Flatpak places installed binaries in /app/bin, which is automatically in the PATH.
        scheduler_path = shutil.which('scheduler')

        # Fallback for local, uninstalled development environments
        if not scheduler_path:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            scheduler_path = os.path.join(project_root, 'build', 'c++', 'scheduler')
            if not os.path.exists(scheduler_path):
                self.show_error_dialog(f"Error: Could not find 'scheduler' executable at {scheduler_path}.")
                return

        cmd = [
            scheduler_path,
            '--json-file', self.json_path,
            '--courses', ",".join(self.selected_courses)
        ]

        # Use Pipe (|) to join strings to avoid splitting names that contain commas!
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

        start_h = self.start_hours.get_value_as_int()
        start_m = self.start_minutes.get_value_as_int()
        if start_h != 0 or start_m != 0:
            cmd.extend(['--start-time', f"{start_h:02d}:{start_m:02d}"])

        end_h = self.end_hours.get_value_as_int()
        end_m = self.end_minutes.get_value_as_int()
        if end_h != 0 or end_m != 0:
            cmd.extend(['--end-time', f"{end_h:02d}:{end_m:02d}"])

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

        print(f"Running command: {' '.join(cmd)}")

        target_width = max(self.get_width(), 1175)
        target_height = max(self.get_height(), 750)
        self.set_default_size(target_width, target_height)

        self.start_scheduler_thread(cmd)

    # --- COMPARE & RESCHEDULE LOGIC ---
    def on_compare_clicked(self, _button):
        if not self.schedules or self.current_schedule_idx >= len(self.schedules):
            return

        current_sched = self.schedules[self.current_schedule_idx]

        # Build a map of course -> set of ALL section IDs (Lecture, Lab, Tutorial) present in this exact schedule
        current_courses = {}
        for m in current_sched['meetings']:
            c = m['course']
            if c not in current_courses:
                current_courses[c] = set()
            current_courses[c].add(m['id'])

        # Native Libadwaita popup styling (Beautiful card-style sheet floating over the window)
        dialog = Adw.Dialog(title="Compare & Reschedule")
        dialog.set_content_width(450)
        dialog.set_content_height(500)

        toolbar = Adw.ToolbarView()
        dialog.set_child(toolbar)

        # Flat header to match screenshot
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        toolbar.add_top_bar(header)

        # Search Toggle Button in HeaderBar
        search_btn = Gtk.ToggleButton(icon_name="system-search-symbolic")
        search_btn.set_tooltip_text("Search Courses")
        header.pack_start(search_btn)

        # Search Bar (Revealer style, hidden by default, sliding down from header)
        search_bar = Gtk.SearchBar()
        search_entry = Gtk.SearchEntry(placeholder_text="Filter courses...")
        search_bar.set_child(search_entry)
        search_bar.set_key_capture_widget(dialog) # Begins searching as soon as you type!
        search_bar.connect_entry(search_entry)
        toolbar.add_top_bar(search_bar)

        # Bind button state to search bar
        search_btn.connect("toggled", lambda btn: search_bar.set_search_mode(btn.get_active()))
        search_bar.connect("notify::search-mode-enabled", lambda sb, *_: search_btn.set_active(sb.get_search_mode()))

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(18)
        vbox.set_margin_start(45)
        vbox.set_margin_end(45)

        toolbar.set_content(vbox)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        list_box.set_margin_top(5)
        list_box.set_margin_bottom(5)
        list_box.set_margin_start(5)
        list_box.set_margin_end(5)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(list_box)
        vbox.append(scrolled)

        # Bottom Buttons (Homogeneous 50/50 Layout perfectly centered)
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

        combo_rows = {}
        rows = []

        # Populate the dialog listbox with all loaded courses in the database
        for course_code in sorted(self.data.keys()):
            row = Adw.ComboRow(title=course_code)

            if course_code in current_courses:
                row.set_model(Gtk.StringList.new(["Not Selected", "Locked", "Unlocked"]))
                row.set_selected(1) # Locked by default for current classes
                row.set_tooltip_text("Lock: Keep this exact section. Unlocked: Allow other sections. Not Selected: Remove.")
            else:
                row.set_model(Gtk.StringList.new(["Not Selected", "Selected"]))
                row.set_selected(0) # Not selected by default for outside classes
                row.set_tooltip_text("Selected: Add this course. Not Selected: Do not add.")

            list_box.append(row)
            combo_rows[course_code] = row
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
            self.execute_compare_generation(combo_rows, current_courses)
            dialog.close()

        cancel_btn.connect("clicked", on_cancel)
        generate_btn.connect("clicked", on_generate)

        dialog.present()

    def execute_compare_generation(self, combo_rows, current_courses):
        temp_selected = set()
        temp_section_locks = {}

        for course, row in combo_rows.items():
            selected_item = row.get_selected_item()
            if not selected_item:
                continue
            selected_text = selected_item.get_string()

            if selected_text == "Locked":
                temp_selected.add(course)
                temp_section_locks[course] = current_courses[course]
            elif selected_text in ("Unlocked", "Selected"):
                temp_selected.add(course)

        if not temp_selected:
            self.show_error_dialog("Please select at least one course.")
            return

        scheduler_path = shutil.which('scheduler')
        if not scheduler_path:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            scheduler_path = os.path.join(project_root, 'build', 'c++', 'scheduler')

        cmd = [
            scheduler_path,
            '--json-file', self.json_path,
            '--courses', ",".join(temp_selected)
        ]

        # Construct specific sections override ONLY for locked courses
        pref_secs = []
        for c in temp_selected:
            if c in temp_section_locks:
                # Append EVERY section ID (lecture, lab, tut) locked from the current schedule
                for sec_id in temp_section_locks[c]:
                    pref_secs.append(f"{c}:{sec_id}")

        if pref_secs:
            cmd.extend(['--specific-sections', "|".join(pref_secs)])

        # Append standard constraints
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

        start_h = self.start_hours.get_value_as_int()
        start_m = self.start_minutes.get_value_as_int()
        if start_h != 0 or start_m != 0:
            cmd.extend(['--start-time', f"{start_h:02d}:{start_m:02d}"])

        end_h = self.end_hours.get_value_as_int()
        end_m = self.end_minutes.get_value_as_int()
        if end_h != 0 or end_m != 0:
            cmd.extend(['--end-time', f"{end_h:02d}:{end_m:02d}"])

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

        threading.Thread(target=self._run_scheduler_async, args=(cmd,), daemon=True).start()

    def _run_scheduler_async(self, cmd):
        self.generation_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
                if now - last_update > 0.1: # Max 10 updates per second to protect rendering
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

        # Swap top schedule visually only if there is a score improvement
        if self.current_schedule_idx == 0 and old_top != new_top:
            self.draw_schedule_index(0)

        self.schedule_view_inner.set_title(f"Found {len(self.schedules)} Schedules...")

        if len(self.schedules) > 1 and not self.wrap_switch.get_active() and self.current_schedule_idx == 0:
            lastbuttonchild = self.schedule_sidebar_buttons.get_last_child()
            if lastbuttonchild:
                lastbuttonchild.set_sensitive(True)

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
        # Clear previous schedule view
        child = self.schedule.get_first_child()
        while child:
            self.schedule.remove(child)
            child = self.schedule.get_first_child()

        if not self.schedules or index >= len(self.schedules):
            # Update Title if no schedules
            self.schedule_view_inner.set_title("No Schedules Found")

            # If no schedules were generated, show a helpful status page instead of a blank screen
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

            self.schedule.attach(status, 0, 0, 1, 1)
            return

        # Update the title dynamically to "Schedule X of Y"
        self.schedule_view_inner.set_title(f"Schedule {index + 1} of {len(self.schedules)}")

        schedule_data = self.schedules[index]

        # Setup schedule grid properties
        self.schedule.set_row_spacing(0)
        self.schedule.set_column_spacing(10)
        self.schedule.set_margin_top(12)
        self.schedule.set_margin_bottom(12)
        self.schedule.set_margin_start(12)
        self.schedule.set_margin_end(12)

        # Stop grid from expanding vertically to avoid messing up Y-axis pixels alignment.
        # This removes the weird empty space at the top.
        self.schedule.set_valign(Gtk.Align.START)
        self.schedule.set_hexpand(True)
        self.schedule.set_halign(Gtk.Align.FILL)

        # 1. Draw Time Labels from 8:30 to 20:30
        # Scaled down to 60px height per hour instead of 90px (reduces total height by 33%)
        for i in range(13):
            hour = 8 + i
            time_str = f"{hour:02d}:30"
            label = Gtk.Label(label=time_str)
            label.add_css_class("dim-label")
            label.set_halign(Gtk.Align.END)
            label.set_valign(Gtk.Align.START)
            label.set_margin_end(6)

            # The box enforces the fixed row height for perfect alignment
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_valign(Gtk.Align.START)
            if i == 12:
                box.set_size_request(60, 1) # Last boundary label doesn't need to stretch
            else:
                box.set_size_request(60, 60) # 60 pixels per hour

            box.append(label)
            self.schedule.attach(box, 0, i + 1, 1, 1)

        # 2. Draw Day Headers & Initialize Columns using Gtk.Overlay
        days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        day_overlays = {}

        for col_idx, day in enumerate(days, start=1):
            day_label = Gtk.Label()
            day_label.set_markup(f"<b>{day}</b>")
            day_label.set_margin_bottom(12)
            day_label.set_halign(Gtk.Align.CENTER)
            self.schedule.attach(day_label, col_idx, 0, 1, 1)

            # Creating an Overlay allowing dynamic horizontal stretching to fill space
            overlay = Gtk.Overlay()

            # Use a dummy box as the underlying widget to force minimum column sizes
            dummy = Gtk.Box()
            dummy.set_size_request(140, 12 * 60) # Min 140px width, 720px total height
            overlay.set_child(dummy)

            overlay.set_hexpand(True)
            overlay.set_halign(Gtk.Align.FILL)
            overlay.set_valign(Gtk.Align.START)

            self.schedule.attach(overlay, col_idx, 1, 1, 12)
            day_overlays[col_idx] = overlay

        # 3. Schedule Coordinate Setup
        START_MINUTES = 8 * 60 + 30 # 8:30 in absolute minutes (510)
        PX_PER_MINUTE = 1.0         # 60 pixels per hour = 1.0 px/min (Clean coordinate scaling)

        # 4. Render Meetings
        for meeting in schedule_data["meetings"]:
            if meeting["day"] == 0 or meeting["start"] < 0 or meeting["end"] < 0:
                continue

            day_idx = meeting["day"] # 1 to 7
            if day_idx not in day_overlays:
                continue

            overlay = day_overlays[day_idx]

            # Calculate exact coordinates
            start_y = int((meeting["start"] - START_MINUTES) * PX_PER_MINUTE)
            height = int((meeting["end"] - meeting["start"]) * PX_PER_MINUTE)

            # Gracefully handle classes starting before 8:30 bounds
            if start_y < 0:
                height += start_y
                start_y = 0
            if height <= 0:
                continue

            # Create the native styling card
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            card.add_css_class("card")
            card.set_size_request(-1, height) # Don't bound width dynamically, enforce strict height

            card.set_halign(Gtk.Align.FILL) # Horizontally expand to container size
            card.set_valign(Gtk.Align.START) # Anchor perfectly from top of the Grid
            card.set_margin_top(start_y) # Absolute position distance

            # --- Extract Full Title for Tooltip ---
            full_title = meeting['course']
            course_data = self.data.get(meeting['course'], [])
            if course_data:
                # Pluck fullTitle from the first item found for this course
                full_title = course_data[0].get("fullTitle", meeting['course'])

            # Rich Tooltip Display
            tooltip_text = f"{full_title} ({meeting['id']})\n" \
                           f"Type: {meeting['type']}\n" \
                           f"Time: {meeting['start']//60:02d}:{meeting['start']%60:02d} - {meeting['end']//60:02d}:{meeting['end']%60:02d}\n" \
                           f"Instructor: {meeting['instructor']}\n" \
                           f"Location: {meeting['location']}\n" \
                           f"Seats Left: {meeting['seats']}"
            card.set_tooltip_text(tooltip_text)

            # --- Internal Card Layout (Homogeneous Dual-Column) ---
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            inner.set_homogeneous(True) # Forces perfect 50/50 visual split!
            inner.set_valign(Gtk.Align.CENTER) # <--- Vertically Centers the text block!
            inner.set_margin_top(4)
            inner.set_margin_bottom(4)
            inner.set_margin_start(6)
            inner.set_margin_end(6)
            card.append(inner)

            # Left Column (Course, Type, Room)
            left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            left_col.set_hexpand(True)
            left_col.set_halign(Gtk.Align.FILL)
            inner.append(left_col)

            # Right Column (Instructor)
            right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            right_col.set_hexpand(True)
            right_col.set_halign(Gtk.Align.FILL)
            inner.append(right_col)

            # Left: Title (Scaled to caption size, bold)
            title = Gtk.Label()
            title.set_markup(f"<b>{meeting['course']}</b>")
            title.set_ellipsize(3) # END
            title.set_halign(Gtk.Align.START)
            title.add_css_class("caption")
            left_col.append(title)

            # Left: Subtitle (Type & ID) (Scaled to caption size)
            subtitle = Gtk.Label(label=f"{meeting['type']} ({meeting['id']})")
            subtitle.set_ellipsize(2)
            subtitle.add_css_class("dim-label")
            subtitle.add_css_class("caption")
            subtitle.set_halign(Gtk.Align.START)
            left_col.append(subtitle)

            # Hide subtitle if slot height is extremely short (< 40 minutes)
            if height < 40:
                subtitle.set_visible(False)

            # Left: Room location (Scaled to caption size)
            raw_location = meeting['location']
            # Grab just the last part of the string (e.g. "Room 134")
            short_location = raw_location.split(',')[-1].strip() if ',' in raw_location else raw_location

            room = Gtk.Label(label=short_location)
            room.set_halign(Gtk.Align.START)
            room.add_css_class("caption")

            # Allow tall cards to show more room details before ellipsizing
            if height > 80:
                room.set_wrap(True)
                room.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
                room.set_lines(2)

            room.set_ellipsize(3)
            left_col.append(room)

            # Hide room if slot height is short (< 60 minutes) to prevent overflow
            if height < 60:
                room.set_visible(False)

            # Right: Instructor
            instructor = Gtk.Label(label=meeting['instructor'])
            instructor.set_halign(Gtk.Align.START)
            instructor.set_valign(Gtk.Align.START)
            instructor.add_css_class("caption")
            #instructor.add_css_class("dim-label")
            instructor.set_wrap(True)
            instructor.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            if height > 110:
                instructor.set_lines(4)
            else:
                instructor.set_lines(2)
            #instructor.set_lines(2) # Word-wraps cleanly up to 2 lines
            instructor.set_ellipsize(3) # Adds '...' if the name spans more than max lines allowed
            right_col.append(instructor)

            # Add to the day column overlay layer perfectly formatted
            overlay.add_overlay(card)

            #Handle Visual State of Previous and Next Buttons

            if not self.wrap_switch.get_active():
                firstbuttonchild = self.schedule_sidebar_buttons.get_first_child()
                lastbuttonchild = self.schedule_sidebar_buttons.get_last_child()
                if self.current_schedule_idx == 0:
                    firstbuttonchild.set_sensitive(False)
                elif self.current_schedule_idx == 1:
                    firstbuttonchild.set_sensitive(True)
                elif self.current_schedule_idx == len(self.schedules) -1:
                    lastbuttonchild.set_sensitive(False)
                elif self.current_schedule_idx == len(self.schedules) -2:
                    lastbuttonchild.set_sensitive(True)
