# timetable_view.py

import re
from typing import Dict, List
from gi.repository import Adw, Gtk, GLib, Pango, Gdk

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

START_MINUTES = 8 * 60 + 30  # 08:30
PX_PER_MINUTE = 1.0
TOTAL_HOURS = 13  # 08:30 to 20:30
DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


class TimetableView:
    """Manages the timetable grid skeleton and renders schedule meeting cards."""

    def __init__(self, grid: Gtk.Grid, on_right_click_block=None):
        self.grid = grid
        self._day_overlays: Dict[int, Gtk.Overlay] = {}
        self._active_cards: Dict[int, List[Gtk.Widget]] = {col: [] for col in range(1, 8)}
        self.on_right_click_block = on_right_click_block

        self._init_grid_properties()
        self._init_skeleton()

    def _init_grid_properties(self):
        self.grid.set_row_spacing(0)
        self.grid.set_column_spacing(10)
        self.grid.set_valign(Gtk.Align.START)
        self.grid.set_hexpand(True)
        self.grid.set_halign(Gtk.Align.FILL)

    def _init_skeleton(self):
        """Constructs static time markers and day overlays once on initialization."""
        # 1. Clear any initial children
        child = self.grid.get_first_child()
        while child:
            self.grid.remove(child)
            child = self.grid.get_first_child()

        # 2. Time markers (08:30 to 20:30 in column 0)
        for i in range(TOTAL_HOURS):
            hour = 8 + i
            label = Gtk.Label(label=f"{hour:02d}:30")
            label.add_css_class("dim-label")
            label.set_halign(Gtk.Align.END)
            label.set_valign(Gtk.Align.START)
            label.set_margin_end(6)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.set_valign(Gtk.Align.START)
            box.set_size_request(55, 1 if i == TOTAL_HOURS - 1 else 60)
            box.append(label)
            self.grid.attach(box, 0, i + 1, 1, 1)

        # 3. Day columns (columns 1 to 7)
        for col_idx, day in enumerate(DAYS, start=1):
            day_label = Gtk.Label(label=f"<b>{day}</b>", use_markup=True)
            day_label.set_margin_bottom(8)
            day_label.set_halign(Gtk.Align.CENTER)
            self.grid.attach(day_label, col_idx, 0, 1, 1)

            overlay = Gtk.Overlay()
            dummy = Gtk.Box()
            dummy.set_size_request(120, (TOTAL_HOURS - 1) * 60)
            overlay.set_child(dummy)
            overlay.set_hexpand(True)
            overlay.set_halign(Gtk.Align.FILL)
            overlay.set_valign(Gtk.Align.START)

            self.grid.attach(overlay, col_idx, 1, 1, TOTAL_HOURS - 1)
            self._day_overlays[col_idx] = overlay

    def clear(self):
        """Clears only the active cards, leaving the grid skeleton intact."""
        for col_idx, overlay in self._day_overlays.items():
            for card in self._active_cards[col_idx]:
                overlay.remove_overlay(card)
            self._active_cards[col_idx].clear()

    def render(self, meetings: List[Dict], course_data: Dict, block_info_choice: int, use_full_title: bool):
        """Draws all meeting cards onto their respective day overlays."""
        self.clear()

        if not meetings:
            return

        unique_courses = sorted(list({m['course'] for m in meetings}))
        course_color_idx_map = {c: i % len(COURSE_COLORS) for i, c in enumerate(unique_courses)}

        for meeting in meetings:
            if meeting.get("day", 0) == 0 or meeting.get("start", -1) < 0 or meeting.get("end", -1) < 0:
                continue

            day_idx = meeting["day"]
            if day_idx not in self._day_overlays:
                continue

            card = self._create_meeting_card(
                meeting=meeting,
                course_data=course_data,
                color_idx=course_color_idx_map.get(meeting['course'], 0),
                block_info_choice=block_info_choice,
                use_full_title=use_full_title
            )

            if card:
                self._day_overlays[day_idx].add_overlay(card)
                self._active_cards[day_idx].append(card)

    def _create_meeting_card(
        self,
        meeting: Dict,
        course_data: Dict,
        color_idx: int,
        block_info_choice: int,
        use_full_title: bool
    ) -> Gtk.Widget:
        start_y = int((meeting["start"] - START_MINUTES) * PX_PER_MINUTE)
        # 1px visual gap so consecutive cards don't touch
        height = int((meeting["end"] - meeting["start"]) * PX_PER_MINUTE) - 1

        if start_y < 0:
            height += start_y
            start_y = 0
        if height <= 0:
            return None

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")
        card.add_css_class(f"course-color-{color_idx}")
        card.set_size_request(-1, height)
        card.set_halign(Gtk.Align.FILL)
        card.set_valign(Gtk.Align.START)
        card.set_margin_top(start_y)

        # Full title fallback
        full_title = meeting['course']
        c_info = course_data.get(meeting['course'], [])
        if c_info:
            full_title = c_info[0].get("fullTitle", meeting['course'])

        # Tooltip
        card.set_tooltip_text(
            f"{full_title} ({meeting['id']})\n"
            f"Type: {meeting['type']}\n"
            f"Time: {meeting['start']//60:02d}:{meeting['start']%60:02d} - {meeting['end']//60:02d}:{meeting['end']%60:02d}\n"
            f"Instructor: {meeting['instructor']}\n"
            f"Location: {meeting['location']}\n"
            f"Seats: {meeting['seats']}\n"
            f"\nRight-click to swap section"
        )

        # Right click gesture
        click_gesture = Gtk.GestureClick.new()
        click_gesture.set_button(Gdk.BUTTON_SECONDARY)
        click_gesture.connect("pressed", self._on_card_right_clicked, meeting)
        card.add_controller(click_gesture)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        inner.set_margin_top(4)
        inner.set_margin_bottom(4)
        inner.set_margin_start(6)
        inner.set_margin_end(6)
        card.append(inner)

        # Information tag choice
        info_str = self._resolve_info_string(meeting, c_info, block_info_choice)

        display_title = full_title if use_full_title else meeting['course']
        title = Gtk.Label(
            label=f"<b>{GLib.markup_escape_text(display_title)}</b>",
            use_markup=True,
            halign=Gtk.Align.START,
            ellipsize=Pango.EllipsizeMode.END
        )
        title.add_css_class("caption")

        # Responsive card layout based on available card height
        if height >= 65:
            inner.append(title)
            sub = Gtk.Label(
                label=f"{meeting['type']} ({meeting['id']})",
                halign=Gtk.Align.START,
                ellipsize=Pango.EllipsizeMode.END
            )
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            inner.append(sub)

            info_lbl = Gtk.Label(label=info_str, halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
            info_lbl.add_css_class("caption")
            inner.append(info_lbl)

        elif height >= 40:
            inner.append(title)

            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            inner.append(hbox)

            sub = Gtk.Label(
                label=f"{meeting['type']} ({meeting['id']})",
                halign=Gtk.Align.START,
                ellipsize=Pango.EllipsizeMode.MIDDLE
            )
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            sub.set_hexpand(True)
            hbox.append(sub)

            info_lbl = Gtk.Label(label=info_str, halign=Gtk.Align.END, ellipsize=Pango.EllipsizeMode.END)
            info_lbl.add_css_class("caption")
            hbox.append(info_lbl)

        else:
            inner.append(title)

        return card

    @staticmethod
    def _resolve_info_string(meeting: Dict, c_info: List[Dict], choice: int) -> str:
        if choice == 0:  # Instructor
            inst = meeting.get('instructor', '')
            if inst and inst != "Not Assigned":
                parts = [p for p in inst.strip().split() if p]
                if len(parts) > 1:
                    return f"{parts[0]} {parts[-1]}"
                elif len(parts) == 1:
                    return parts[0]
            return "TBA"
        elif choice == 1:  # Room
            loc = meeting.get('location', '')
            return loc.split(',')[-1].strip() if ',' in loc else loc
        elif choice == 2:  # Seats
            return f"Seats: {meeting.get('seats', 'N/A')}"
        elif choice == 3:  # Credits
            credits = c_info[0].get("creditHours", c_info[0].get("hours", c_info[0].get("credits", "N/A"))) if c_info else "N/A"
            return f"Credits: {credits}"
        elif choice == 4:  # Time
            return f"{meeting['start']//60:02d}:{meeting['start']%60:02d} - {meeting['end']//60:02d}:{meeting['end']%60:02d}"
        return ""

    def _on_card_right_clicked(self, gesture, n_press, x, y, meeting):
        if self.on_right_click_block:
            card = gesture.get_widget()
            self.on_right_click_block(card, meeting)
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
