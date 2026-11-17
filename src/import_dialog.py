import os
from gi.repository import Adw, Gio, Gtk, GObject, GLib

from .schedule_parser import (
    extract_generator_selection,
    parse_schedule_auto,
    read_schedule_file_text,
)


@Gtk.Template(resource_path='/io/github/Epoch5427/Commodus/import_dialog.ui')
class ImportDialog(Adw.Dialog):
    __gtype_name__ = 'CommodusImportDialog'

    __gsignals__ = {
        'imported': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    cancel_btn = Gtk.Template.Child()
    import_action_btn = Gtk.Template.Child()
    name_group = Gtk.Template.Child()
    name_row = Gtk.Template.Child()
    open_file_btn = Gtk.Template.Child()
    paste_btn = Gtk.Template.Child()
    textview = Gtk.Template.Child()
    status_label = Gtk.Template.Child()

    def __init__(
        self,
        validate_generator: bool = False,
        show_name: bool = False,
        default_name: str = "Schedule",
        title: str = "Import Schedule",
        action_label: str = "Import",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.set_title(title)
        self.import_action_btn.set_label(action_label)

        self._validate_generator = validate_generator
        self._show_name = show_name
        self._default_name = default_name
        self._user_edited_name = False
        self._setting_auto_name = False
        self._parsed_schedule = None
        self._file_source_hint = None

        if show_name:
            self.name_group.set_visible(True)
            self._setting_auto_name = True
            self.name_row.set_text(default_name)
            self._setting_auto_name = False
            self.name_row.connect("changed", self._on_name_changed)

        self.buf = self.textview.get_buffer()
        self.buf.connect("changed", self._on_buffer_changed)
        self.open_file_btn.connect("clicked", self._on_open_file_clicked)
        self.paste_btn.connect("clicked", self._on_paste_clicked)
        self.cancel_btn.connect("clicked", lambda *_: self.close())
        self.import_action_btn.connect("clicked", self._on_import_clicked)

    def _on_name_changed(self, _entry):
        if not self._setting_auto_name:
            self._user_edited_name = bool(self.name_row.get_text().strip())

    def _on_buffer_changed(self, _buf):
        raw_text = _buf.get_text(_buf.get_start_iter(), _buf.get_end_iter(), False).strip()
        if not raw_text:
            self._parsed_schedule = None
            self._file_source_hint = None
            self.status_label.set_text("Paste Commodus or Self-Service schedule text above, or load a file.")
            self.status_label.remove_css_class("error")
            self.import_action_btn.set_sensitive(False)
            return

        parsed, err = parse_schedule_auto(
            raw_text,
            default_name=self._default_name,
            source_hint=self._file_source_hint,
        )
        if err or not parsed:
            self._parsed_schedule = None
            self.status_label.set_markup(f"<b>Error:</b> {GLib.markup_escape_text(err or 'Invalid schedule format.')}")
            self.status_label.add_css_class("error")
            self.import_action_btn.set_sensitive(False)
            return

        if self._validate_generator:
            courses, _, _, gen_err = extract_generator_selection(parsed, validate_sections=True)
            if gen_err:
                self._parsed_schedule = None
                self.status_label.set_markup(f"<b>Error:</b> {GLib.markup_escape_text(gen_err)}")
                self.status_label.add_css_class("error")
                self.import_action_btn.set_sensitive(False)
                return
            courses_str = ", ".join(sorted(courses))
            self.status_label.remove_css_class("error")
            self.status_label.set_markup(f"Found <b>{len(courses)}</b> course(s): {GLib.markup_escape_text(courses_str)}")
        else:
            if self._show_name and not self._user_edited_name:
                self._setting_auto_name = True
                self.name_row.set_text(parsed.name)
                self._setting_auto_name = False

            unsched = f" ({len(parsed.unscheduled_courses)} unscheduled)" if parsed.unscheduled_courses else ""
            self.status_label.remove_css_class("error")
            self.status_label.set_markup(
                f"Detected <b>{GLib.markup_escape_text(parsed.source_type)}</b> schedule: "
                f"<b>{parsed.total_courses}</b> course(s), <b>{parsed.block_count}</b> time block(s){unsched}"
            )

        self._parsed_schedule = parsed
        self.import_action_btn.set_sensitive(True)

    def _on_open_file_clicked(self, _btn):
        file_dialog = Gtk.FileDialog()
        file_dialog.set_title("Open Schedule File")

        sched_filter = Gtk.FileFilter(name="Schedule Files (PDF, Text)")
        sched_filter.add_mime_type("application/pdf")
        sched_filter.add_pattern("*.pdf")
        sched_filter.add_mime_type("text/plain")
        sched_filter.add_pattern("*.txt")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(sched_filter)
        file_dialog.set_filters(filters)
        file_dialog.set_default_filter(sched_filter)
        file_dialog.open(self.get_root(), None, self._on_file_opened)

    def _on_file_opened(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path() if gfile else None
        if not path:
            return

        text, err = read_schedule_file_text(path)
        if err or not text:
            self.status_label.set_markup(f"<b>Error:</b> {GLib.markup_escape_text(err or 'Empty file.')}")
            self.status_label.add_css_class("error")
            return

        ext = os.path.splitext(path)[1].lower()
        self._file_source_hint = "Self-Service PDF" if ext == ".pdf" else None
        if self._show_name and not self._user_edited_name:
            self._default_name = os.path.splitext(os.path.basename(path))[0] or self._default_name
        self.buf.set_text(text)

    def _on_paste_clicked(self, _btn):
        def _on_text_read(cb, res):
            try:
                text = cb.read_text_finish(res)
                if text:
                    self._file_source_hint = None
                    self.buf.set_text(text)
            except GLib.Error:
                pass

        self.get_clipboard().read_text_async(None, _on_text_read)

    def _on_import_clicked(self, _btn):
        if not self._parsed_schedule:
            return
        if self._show_name:
            custom_name = self.name_row.get_text().strip()
            if custom_name:
                self._parsed_schedule.name = custom_name
        self.emit('imported', self._parsed_schedule)
        self.close()
