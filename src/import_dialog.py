from gi.repository import Adw, Gtk, GObject

@Gtk.Template(resource_path='/io/github/Epoch5427/Commodus/import_dialog.ui')
class ImportDialog(Adw.Dialog):
    __gtype_name__ = 'CommodusImportDialog'

    __gsignals__ = {
        'imported': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    cancel_btn = Gtk.Template.Child()
    import_action_btn = Gtk.Template.Child()
    paste_btn = Gtk.Template.Child()
    textview = Gtk.Template.Child()
    status_label = Gtk.Template.Child()

    def __init__(self, parse_preview_fn, **kwargs):
        super().__init__(**kwargs)
        self.parse_preview_fn = parse_preview_fn

        self.buf = self.textview.get_buffer()
        self.buf.connect("changed", self._on_buffer_changed)
        self.paste_btn.connect("clicked", self._on_paste_clicked)
        self.cancel_btn.connect("clicked", lambda *_: self.close())
        self.import_action_btn.connect("clicked", self._on_import_clicked)

    def _on_buffer_changed(self, _buf):
        raw_text = _buf.get_text(_buf.get_start_iter(), _buf.get_end_iter(), False).strip()
        if not raw_text:
            self.status_label.set_text("Paste exported schedule text above.")
            self.import_action_btn.set_sensitive(False)
            return

        courses, _, _ = self.parse_preview_fn(raw_text)
        if courses:
            courses_str = ", ".join(sorted(courses))
            self.status_label.set_markup(f"Found <b>{len(courses)}</b> course(s): {courses_str}")
            self.import_action_btn.set_sensitive(True)
        else:
            self.status_label.set_text("No valid schedule format detected. Expected: COURSE TYPE SEC DAY TIME | INSTRUCTOR")
            self.import_action_btn.set_sensitive(False)

    def _on_paste_clicked(self, _btn):
        clipboard = self.get_clipboard()
        clipboard.read_text_async(None, lambda cb, res: self.buf.set_text(cb.read_text_finish(res) or ""))

    def _on_import_clicked(self, _btn):
        raw_text = self.buf.get_text(self.buf.get_start_iter(), self.buf.get_end_iter(), False)
        self.emit('imported', raw_text)
        self.close()
