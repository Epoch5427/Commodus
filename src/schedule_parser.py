import base64
from dataclasses import dataclass, field
import os
import re
import shutil
import subprocess
import textwrap
from typing import Dict, List, Optional, Set, Tuple
import uuid
import zlib

DAY_NAMES = {
    1: "Sunday", 2: "Monday", 3: "Tuesday", 4: "Wednesday",
    5: "Thursday", 6: "Friday", 7: "Saturday",
}
DAY_SHORT = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}
DAY_MAP = {
    "sun": 1, "sunday": 1, "mon": 2, "monday": 2,
    "tue": 3, "tues": 3, "tuesday": 3, "wed": 4, "wednesday": 4,
    "thu": 5, "thur": 5, "thurs": 5, "thursday": 5,
    "fri": 6, "friday": 6, "sat": 7, "saturday": 7,
}

TIME_RANGE_RE = re.compile(
    r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)\s*[-–—]\s*(\d{1,2}:\d{2}\s*(?:AM|PM)?)',
    re.IGNORECASE,
)
DAY_TOKEN_RE = re.compile(
    r'\b(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sun|Mon|Tues|Tue|Wed|Thurs|Thur|Thu|Fri|Sat)\b',
    re.IGNORECASE,
)
FULL_DAY_TOKEN_RE = re.compile(
    r'\b(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)\b',
    re.IGNORECASE,
)
COURSE_HEADER_RE = re.compile(r'^\s*([A-Za-z]{2,6}\s*-?\s*\d{2,4}[A-Za-z]?)\s*:\s*(.+)$')
NON_ROOM_TOKENS = {
    "", "tba", "tbd", "n/a", "na", "none", "not specified", "not assigned",
    "to be announced", "online", "virtual", "remote", "hybrid",
}


@dataclass
class ImportedSchedule:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = "Schedule"
    source_type: str = "Imported"
    enabled: bool = True
    meetings: List[Dict] = field(default_factory=list)
    scheduled_courses: Set[str] = field(default_factory=set)
    unscheduled_courses: Set[str] = field(default_factory=set)

    @property
    def total_courses(self) -> int:
        return len(self.scheduled_courses | self.unscheduled_courses)

    @property
    def block_count(self) -> int:
        return len([m for m in self.meetings if m.get("day", 0) > 0 and m.get("start", -1) >= 0])

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "source_type": self.source_type,
            "enabled": self.enabled,
            "meetings": self.meetings,
            "scheduled_courses": sorted(self.scheduled_courses),
            "unscheduled_courses": sorted(self.unscheduled_courses),
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ImportedSchedule":
        return cls(
            id=d.get("id") or uuid.uuid4().hex[:10],
            name=d.get("name", "Schedule"),
            source_type=d.get("source_type", "Imported"),
            enabled=bool(d.get("enabled", True)),
            meetings=list(d.get("meetings", [])),
            scheduled_courses=set(d.get("scheduled_courses", [])),
            unscheduled_courses=set(d.get("unscheduled_courses", [])),
        )


def parse_single_time(t_str: str) -> int:
    if not t_str or ":" not in t_str:
        return -1
    m = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)?', t_str, re.IGNORECASE)
    if not m:
        return -1
    h, mins, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if h > 23 or mins > 59:
        return -1
    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and h != 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
    return h * 60 + mins


def parse_time_range(s: str) -> Tuple[int, int]:
    if not s or "n/a" in str(s).lower():
        return -1, -1
    m = TIME_RANGE_RE.search(s)
    if not m:
        return -1, -1
    st, en = parse_single_time(m.group(1)), parse_single_time(m.group(2))
    if st < 0 or en < 0:
        return -1, -1
    if en % 60 in (29, 59):
        en += 1
    if en <= st:
        return -1, -1
    return st, en


def format_minutes(minutes: int) -> str:
    h, m = divmod(max(0, int(minutes)), 60)
    return f"{h:02d}:{m:02d}"


def format_duration(minutes: int) -> str:
    h, m = divmod(max(0, int(minutes)), 60)
    if h > 0 and m > 0:
        return f"{h}h {m}m"
    if h > 0:
        return f"{h}h"
    return f"{m}m"


def get_section_prefix(sec_id: str) -> str:
    if not sec_id:
        return ""
    m = re.match(r'^\d+', str(sec_id).strip())
    return (m.group(0).lstrip("0") or "0") if m else str(sec_id).strip()


def iter_section_meetings(
    course: str,
    item: Dict,
    default_type: str = "",
    default_sec: str = "",
) -> List[Dict]:
    """Extracts normalized meeting dicts from a single JSON course-section entry."""
    mtype = item.get("subtype") or item.get("type") or default_type
    sec_id = item.get("section") or item.get("id") or default_sec
    inst = item.get("instructor", "Not Assigned")
    try:
        seats = int(item.get("seatsLeft", item.get("seats", 0)))
    except Exception:
        seats = 0

    def clean_loc(raw_loc: str) -> str:
        loc = (raw_loc or "TBA").strip()
        return "TBA" if not loc or loc == "Not specified" else loc

    results: List[Dict] = []
    sub_list = item.get("schedules") if isinstance(item.get("schedules"), list) else (
        item.get("meetings") if isinstance(item.get("meetings"), list) else None
    )

    if sub_list is not None:
        for sub in sub_list:
            d_num = DAY_MAP.get(str(sub.get("day", "")).strip().lower(), 0)
            st, en = parse_time_range(sub.get("time") or sub.get("schedule") or "")
            if d_num > 0 and st >= 0 and en > st:
                results.append({
                    "course": course, "type": mtype, "id": sec_id,
                    "day": d_num, "start": st, "end": en,
                    "location": clean_loc(sub.get("location") or item.get("location", "TBA")),
                    "instructor": inst, "seats": seats,
                })
    elif isinstance(item.get("schedule"), str) and "n/a" not in item["schedule"].lower():
        loc = clean_loc(item.get("location", "TBA"))
        for part in re.split(r'[\n;/]+', item["schedule"]):
            part = part.strip()
            if not part:
                continue
            dm = DAY_TOKEN_RE.search(part)
            d_num = DAY_MAP.get(dm.group(1).lower(), 0) if dm else 0
            st, en = parse_time_range(part)
            if d_num > 0 and st >= 0 and en > st:
                results.append({
                    "course": course, "type": mtype, "id": sec_id,
                    "day": d_num, "start": st, "end": en,
                    "location": loc, "instructor": inst, "seats": seats,
                })
    return results


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    for ch in ("\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\ufeff"):
        text = text.replace(ch, "")
    return text


def parse_commodus_text(text: str) -> Tuple[List[Dict], Set[str]]:
    text = _normalize_text(text)
    meetings: List[Dict] = []
    courses: Set[str] = set()

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line:
            left_part, right_part = line.split("|", 1)
            instructor = right_part.strip() or "Not Assigned"
        else:
            left_part, instructor = line, "Not Assigned"

        time_match = TIME_RANGE_RE.search(left_part)
        if not time_match:
            continue
        st, en = parse_time_range(time_match.group(0))
        if st < 0 or en < 0:
            continue

        day_match = DAY_TOKEN_RE.search(left_part[:time_match.start()]) or DAY_TOKEN_RE.search(left_part)
        if not day_match:
            continue
        day_int = DAY_MAP.get(day_match.group(1).lower(), 0)
        if day_int == 0:
            continue

        tokens = left_part[:day_match.start()].strip().split()
        if not tokens:
            continue

        course = tokens[0].upper()
        courses.add(course)
        meetings.append({
            "course": course,
            "type": tokens[1] if len(tokens) > 1 else "",
            "id": tokens[2] if len(tokens) > 2 else "",
            "day": day_int,
            "start": st,
            "end": en,
            "location": "TBA",
            "instructor": instructor,
        })
    return meetings, courses


def _extract_student_name(lines: List[str]) -> Optional[str]:
    term_re = re.compile(r'^\s*\d{4}\s*/\s*(?:FALL|SPRING|SUMMER|WINTER|[A-Z]{3,10})\s*$', re.IGNORECASE)
    skip_re = re.compile(
        r'^(?:Page\s+\d+|Advisor|Session\s*-|Instructor|Undergraduate|Graduate|Bachelor|Master|Registered\b|Section:|Subtype:|Type:|Credit\s+Type:|No\s+schedule)',
        re.IGNORECASE,
    )
    for idx, line in enumerate(lines):
        if term_re.match(line.strip()):
            for nxt in lines[idx + 1: idx + 4]:
                cand = nxt.strip()
                if not cand:
                    continue
                if skip_re.match(cand) or COURSE_HEADER_RE.match(cand):
                    break
                if re.search(r'\d', cand) or ":" in cand or "|" in cand:
                    break
                words = cand.split()
                if 1 <= len(words) <= 6 and all(re.fullmatch(r"[A-Za-z.\-']+", w) for w in words):
                    return cand
    return None


def parse_self_service_text(text: str) -> Tuple[List[Dict], Set[str], Set[str], Optional[str]]:
    text = _normalize_text(text)
    raw_lines = [ln.strip() for ln in text.split("\n")]

    lines: List[str] = []
    i = 0
    while i < len(raw_lines):
        cur = raw_lines[i]
        if (
            cur
            and re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM)?\s*[-–—]\s*$', cur, re.IGNORECASE)
            and i + 1 < len(raw_lines)
            and re.match(r'^\d{1,2}:\d{2}', raw_lines[i + 1])
        ):
            lines.append(f"{cur} {raw_lines[i + 1]}")
            i += 2
        else:
            lines.append(cur)
            i += 1

    student_name = _extract_student_name(lines)
    footer_re = re.compile(r'^(?:\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}|Page\s+\d+\s+of\s+\d+)', re.IGNORECASE)
    header_noise_re = re.compile(
        r'^(?:\d{4}/(?:FALL|SPRING|SUMMER|WINTER)|Registered\s+(?:Credits|Courses)\s*:|Advisor\(s\)\s*:|Instructor\(s\)\s+Credits)',
        re.IGNORECASE,
    )
    meta_line_re = re.compile(r'^(?:Section:|Subtype:|Type:|Duration:|Credit\s+Type:|Session\s*-)', re.IGNORECASE)
    status_line_re = re.compile(r'^(.*?)\s+\d+\.\d{2}\s+(?:Registered|Waitlisted|Pending|In\s+Cart|Cart|Dropped)\b', re.IGNORECASE)

    meetings: List[Dict] = []
    scheduled_courses: Set[str] = set()
    unscheduled_courses: Set[str] = set()

    current_course: Optional[str] = None
    current_type = "Lecture"
    current_sec = ""
    current_instructor = "Not Assigned"
    current_block_meetings: List[Dict] = []
    has_no_schedule = False
    pending_time: Optional[Tuple[int, int]] = None
    pending_day: Optional[int] = None

    def flush_block():
        nonlocal current_course, current_block_meetings, has_no_schedule, pending_time, pending_day
        if current_course:
            if current_block_meetings:
                scheduled_courses.add(current_course)
                meetings.extend(current_block_meetings)
            elif has_no_schedule:
                unscheduled_courses.add(current_course)
        current_course = None
        current_block_meetings = []
        has_no_schedule = False
        pending_time = pending_day = None

    def emit_meeting(day_int: int, st: int, en: int):
        if current_course and day_int > 0 and st >= 0 and en > st:
            current_block_meetings.append({
                "course": current_course, "type": current_type, "id": current_sec,
                "day": day_int, "start": st, "end": en,
                "location": "TBA", "instructor": current_instructor,
            })

    for line in lines:
        if not line or footer_re.match(line) or header_noise_re.match(line):
            continue
        if student_name and line == student_name:
            continue

        hdr_match = COURSE_HEADER_RE.match(line)
        if hdr_match:
            flush_block()
            current_course = re.sub(r'[\s-]+', '', hdr_match.group(1)).upper()
            current_type, current_sec, current_instructor = "Lecture", "", "Not Assigned"
            tail_status = status_line_re.search(hdr_match.group(2))
            if tail_status:
                split_cols = re.split(r'\s{2,}', tail_status.group(1).strip())
                if len(split_cols) >= 2:
                    current_instructor = split_cols[-1].strip() or "Not Assigned"
            continue

        if current_course is None:
            continue

        sec_match = re.search(
            r'\bSection:\s*([A-Za-z0-9_-]+(?:\s+[A-Za-z0-9_-]+)?)(?=\s*\||\s*$)',
            line,
            re.IGNORECASE,
        )
        if sec_match:
            current_sec = re.sub(r'\s+', '', sec_match.group(1)).strip()

        sub_match = re.search(r'\bSubtype:\s*([A-Za-z]+)', line, re.IGNORECASE)
        if sub_match:
            current_type = sub_match.group(1).strip()

        if "no schedule" in line.lower():
            has_no_schedule = True
            pending_time = pending_day = None
            continue

        st_match = status_line_re.match(line)
        if st_match and not TIME_RANGE_RE.search(line):
            inst_cand = st_match.group(1).strip()
            if inst_cand and not re.match(r'^\d+\.\d{2}$', inst_cand):
                current_instructor = inst_cand
                for m in current_block_meetings:
                    if m["instructor"] == "Not Assigned":
                        m["instructor"] = current_instructor
            continue

        if meta_line_re.match(line):
            continue

        if re.match(r'^(?:Nile\s+University|Building\b|Floor\b|Room\b)', line, re.IGNORECASE) or (
            current_block_meetings
            and current_block_meetings[-1]["location"] != "TBA"
            and re.search(r'\bRoom\b', line, re.IGNORECASE)
        ):
            if current_block_meetings:
                prev_loc = current_block_meetings[-1]["location"]
                current_block_meetings[-1]["location"] = line if prev_loc == "TBA" else f"{prev_loc} {line}"
            continue

        t_match = TIME_RANGE_RE.search(line)
        d_match = FULL_DAY_TOKEN_RE.search(line)
        if t_match and d_match:
            st, en = parse_time_range(t_match.group(0))
            d_int = DAY_MAP.get(d_match.group(1).lower(), 0)
            if st >= 0 and en > st and d_int > 0:
                emit_meeting(d_int, st, en)
            pending_time = pending_day = None
        elif t_match:
            st, en = parse_time_range(t_match.group(0))
            if st >= 0 and en > st:
                if pending_day is not None:
                    emit_meeting(pending_day, st, en)
                    pending_day = pending_time = None
                else:
                    pending_time = (st, en)
        elif d_match:
            is_standalone = len(line.split()) <= 2
            if is_standalone or pending_time is not None:
                d_int = DAY_MAP.get(d_match.group(1).lower(), 0)
                if d_int > 0:
                    if pending_time is not None:
                        emit_meeting(d_int, pending_time[0], pending_time[1])
                        pending_time = pending_day = None
                    elif is_standalone:
                        pending_day = d_int

    flush_block()
    return meetings, scheduled_courses, unscheduled_courses, student_name


def parse_schedule_auto(
    text: str,
    default_name: str = "Schedule",
    source_hint: Optional[str] = None,
) -> Tuple[Optional[ImportedSchedule], Optional[str]]:
    cleaned = _normalize_text(text).strip()
    if not cleaned:
        return None, "No schedule text provided."

    looks_self_service = bool(
        re.search(r'\b(?:Subtype|Section|Credit\s+Type)\s*:', cleaned, re.IGNORECASE)
        or (COURSE_HEADER_RE.search(cleaned) and FULL_DAY_TOKEN_RE.search(cleaned))
    )

    if looks_self_service:
        meetings, sched_courses, unsched_courses, student_name = parse_self_service_text(cleaned)
        if meetings or unsched_courses:
            return ImportedSchedule(
                name=student_name or default_name,
                source_type=source_hint or "Self-Service",
                meetings=meetings,
                scheduled_courses=sched_courses,
                unscheduled_courses=unsched_courses,
            ), None

    c_meetings, c_courses = parse_commodus_text(cleaned)
    if c_meetings:
        return ImportedSchedule(
            name=default_name,
            source_type=source_hint or "Commodus",
            meetings=c_meetings,
            scheduled_courses=c_courses,
        ), None

    if not looks_self_service:
        meetings, sched_courses, unsched_courses, student_name = parse_self_service_text(cleaned)
        if meetings:
            return ImportedSchedule(
                name=student_name or default_name,
                source_type=source_hint or "Self-Service",
                meetings=meetings,
                scheduled_courses=sched_courses,
                unscheduled_courses=unsched_courses,
            ), None

    return None, "Could not recognize Commodus or Self-Service schedule format."


def extract_generator_selection(
    sched: ImportedSchedule,
    validate_sections: bool = True,
) -> Tuple[Set[str], Dict, Set[str], Optional[str]]:
    """Extracts Generator course selection, lecture section locks, and exact meeting pairs."""
    selected = set(sched.scheduled_courses | sched.unscheduled_courses)
    prefs: Dict = {}
    exact_imported: Set[str] = set()
    course_sections: Dict[str, Set[Tuple[str, str]]] = {}

    for m in sched.meetings:
        course = m["course"]
        mtype = m.get("type", "").strip()
        sec_id = str(m.get("id", "")).strip()
        selected.add(course)
        if sec_id:
            exact_imported.add(f"{course}:{sec_id}")
            course_sections.setdefault(course, set()).add((mtype, sec_id))
            if mtype in ("Lecture", "Lab", "Tutorial"):
                entry = prefs.setdefault(course, {"type": "Section", "value": []})
                tag = f"{mtype}:{sec_id}"
                if tag not in entry["value"]:
                    entry["value"].append(tag)

    if validate_sections:
        for course, sec_set in course_sections.items():
            subtypes: Dict[str, Set[str]] = {}
            for mtype, sec_id in sec_set:
                subtypes.setdefault(mtype, set()).add(sec_id)
            for mtype, sids in subtypes.items():
                if len(sids) > 1:
                    return set(), {}, set(), f"Tampered schedule: {course} contains multiple {mtype} sections ({', '.join(sorted(sids))})."

            num_prefixes = {
                get_section_prefix(sec_id)
                for _, sec_id in sec_set
                if re.match(r'^\d+', sec_id)
            }
            if len(num_prefixes) > 1:
                sec_list = ", ".join(sorted({f"{mt} {sid}" for mt, sid in sec_set}))
                return set(), {}, set(), f"Cross-section detected in {course}: incompatible sections ({sec_list})."

    return selected, prefs, exact_imported, None


# =============================================================================
# MULTI-TIER PDF TEXT EXTRACTOR
# =============================================================================

def _extract_with_pdftotext(file_path: str) -> Optional[str]:
    binary = shutil.which("pdftotext")
    if not binary:
        return None
    try:
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        res = subprocess.run(
            [binary, "-enc", "UTF-8", file_path, "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, **kwargs,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout
    except Exception:
        pass
    return None


def _extract_with_poppler(file_path: str) -> Optional[str]:
    try:
        import gi
        gi.require_version("Poppler", "0.18")
        from gi.repository import GLib, Poppler
        doc = Poppler.Document.new_from_file(GLib.filename_to_uri(os.path.abspath(file_path), None), None)
        pages = [doc.get_page(i).get_text() for i in range(doc.get_n_pages()) if doc.get_page(i)]
        joined = "\n".join(p for p in pages if p).strip()
        if joined:
            return joined
    except Exception:
        pass
    return None


def _extract_with_python_libs(file_path: str) -> Optional[str]:
    try:
        import fitz  # type: ignore
        with fitz.open(file_path) as doc:
            txt = "\n".join(page.get_text("text") for page in doc).strip()
            if txt:
                return txt
    except Exception:
        pass
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(mod_name)
            txt = "\n".join((p.extract_text() or "") for p in mod.PdfReader(file_path).pages).strip()
            if txt:
                return txt
        except Exception:
            pass
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(file_path) as pdf:
            txt = "\n".join((p.extract_text() or "") for p in pdf.pages).strip()
            if txt:
                return txt
    except Exception:
        pass
    try:
        from pdfminer.high_level import extract_text as pm_extract_text  # type: ignore
        txt = (pm_extract_text(file_path) or "").strip()
        if txt:
            return txt
    except Exception:
        pass
    return None


def _decode_png_predictor(raw: bytes, columns: int) -> bytes:
    if columns <= 0:
        return raw
    row_len = columns + 1
    out = bytearray()
    prev = bytearray(columns)
    for off in range(0, len(raw), row_len):
        row = raw[off: off + row_len]
        if len(row) < 2:
            break
        filt = row[0]
        cur = bytearray(row[1:])
        if len(cur) < columns:
            cur.extend(b"\x00" * (columns - len(cur)))
        if filt == 1:
            for i in range(1, columns):
                cur[i] = (cur[i] + cur[i - 1]) & 0xFF
        elif filt == 2:
            for i in range(columns):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(columns):
                cur[i] = (cur[i] + (((cur[i - 1] if i > 0 else 0) + prev[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(columns):
                a = cur[i - 1] if i > 0 else 0
                b, c = prev[i], (prev[i - 1] if i > 0 else 0)
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[i] = (cur[i] + pr) & 0xFF
        out.extend(cur[:columns])
        prev = cur
    return bytes(out)


def _decompress_stream(dict_bytes: bytes, stream_bytes: bytes) -> bytes:
    data = stream_bytes
    if re.search(rb'/ASCIIHexDecode\b', dict_bytes):
        cleaned = re.sub(rb'[^0-9A-Fa-f]', b'', data.split(b'>', 1)[0])
        if len(cleaned) % 2 == 1:
            cleaned += b'0'
        try:
            data = bytes.fromhex(cleaned.decode('ascii'))
        except Exception:
            pass
    elif re.search(rb'/ASCII85Decode\b', dict_bytes):
        try:
            body = data.strip()
            if not body.endswith(b'~>'):
                body += b'~>'
            data = base64.a85decode(body, adobe=True)
        except Exception:
            pass

    if re.search(rb'/(?:FlateDecode|Fl)\b', dict_bytes):
        try:
            data = zlib.decompress(data)
        except Exception:
            try:
                data = zlib.decompress(data, -zlib.MAX_WBITS)
            except Exception:
                return b""
        pred_m = re.search(rb'/Predictor\s+(\d+)', dict_bytes)
        cols_m = re.search(rb'/Columns\s+(\d+)', dict_bytes)
        if pred_m and int(pred_m.group(1)) >= 10:
            data = _decode_png_predictor(data, int(cols_m.group(1)) if cols_m else 1)
    return data


def _scan_pdf_objects(data: bytes) -> Dict[int, Tuple[bytes, Optional[bytes]]]:
    objects: Dict[int, Tuple[bytes, Optional[bytes]]] = {}
    obj_re = re.compile(rb'(?:^|[\r\n\s])(\d+)\s+\d+\s+obj\b')
    pos, n = 0, len(data)

    while pos < n:
        m = obj_re.search(data, pos)
        if not m:
            break
        obj_num, body_start = int(m.group(1)), m.end()
        next_endobj = data.find(b"endobj", body_start)
        next_stream = data.find(b"stream", body_start)

        if next_stream != -1 and (next_endobj == -1 or next_stream < next_endobj):
            header_slice = data[body_start:next_stream]
            eol_pos = next_stream + 6
            if b">>" in header_slice and eol_pos < n and data[eol_pos:eol_pos + 1] in (b"\r", b"\n"):
                stream_start = eol_pos + (2 if data[eol_pos:eol_pos + 2] == b"\r\n" else 1)
                stream_end = -1
                len_m = re.search(rb'/Length\s+(\d+)\b(?!\s+\d+\s+R)', header_slice)
                if len_m:
                    cand_end = stream_start + int(len_m.group(1))
                    if cand_end <= n and data[cand_end:cand_end + 14].lstrip(b"\r\n ").startswith(b"endstream"):
                        stream_end = cand_end
                if stream_end == -1:
                    es_m = re.search(rb'\r?\n?endstream\b', data[stream_start:])
                    if es_m:
                        stream_end = stream_start + es_m.start()
                if stream_end != -1:
                    objects[obj_num] = (header_slice, data[stream_start:stream_end])
                    after_es = data.find(b"endobj", stream_end)
                    pos = (after_es + 6) if after_es != -1 else (stream_end + 9)
                    continue

        if next_endobj != -1:
            objects[obj_num] = (data[body_start:next_endobj], None)
            pos = next_endobj + 6
        else:
            pos = body_start + 1

    for _, (hdr, strm) in list(objects.items()):
        if strm is None or not re.search(rb'/Type\s*/ObjStm\b', hdr):
            continue
        first_m = re.search(rb'/First\s+(\d+)', hdr)
        n_m = re.search(rb'/N\s+(\d+)', hdr)
        if not first_m or not n_m:
            continue
        dec = _decompress_stream(hdr, strm)
        first_off, count = int(first_m.group(1)), int(n_m.group(1))
        if not dec or first_off > len(dec):
            continue
        tokens = dec[:first_off].decode("latin-1", errors="ignore").split()
        entries: List[Tuple[int, int]] = []
        for idx in range(0, min(len(tokens) - 1, count * 2), 2):
            try:
                entries.append((int(tokens[idx]), first_off + int(tokens[idx + 1])))
            except ValueError:
                pass
        for idx, (sub_id, start_off) in enumerate(entries):
            end_off = entries[idx + 1][1] if idx + 1 < len(entries) else len(dec)
            if 0 <= start_off <= end_off <= len(dec):
                objects[sub_id] = (dec[start_off:end_off], None)

    return objects


def _hex_to_unicode(hex_str: str) -> str:
    h = re.sub(r'\s+', '', hex_str)
    if len(h) % 2 == 1:
        h = '0' + h
    if not h:
        return ""
    raw = bytes.fromhex(h)
    if len(raw) == 1:
        return raw.decode("latin-1")
    if len(raw) % 2 == 1:
        raw = b"\x00" + raw
    return raw.decode("utf-16-be", errors="replace")


def _parse_tounicode_cmap(cmap_bytes: bytes) -> Tuple[Dict[int, str], int]:
    text = cmap_bytes.decode("latin-1", errors="ignore")
    mapping: Dict[int, str] = {}
    code_bytes = 2 if re.search(r'<[0-9A-Fa-f]{4}>\s*<[0-9A-Fa-f]{4}>', text) else 1

    for block in re.findall(r'beginbfchar(.*?)endbfchar', text, re.S):
        for src_h, dst_h in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', block):
            code_bytes = max(code_bytes, max(1, (len(src_h) + 1) // 2))
            mapping[int(src_h, 16)] = _hex_to_unicode(dst_h)

    for block in re.findall(r'beginbfrange(.*?)endbfrange', text, re.S):
        for s_h, e_h, arr in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]', block, re.S):
            code_bytes = max(code_bytes, max(1, (len(s_h) + 1) // 2))
            s_val, e_val = int(s_h, 16), int(e_h, 16)
            for idx, d_h in enumerate(re.findall(r'<([0-9A-Fa-f]+)>', arr)):
                if s_val + idx <= e_val:
                    mapping[s_val + idx] = _hex_to_unicode(d_h)
        cleaned = re.sub(r'<[0-9A-Fa-f]+>\s*<[0-9A-Fa-f]+>\s*\[.*?\]', '', block, flags=re.S)
        for s_h, e_h, d_h in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', cleaned):
            code_bytes = max(code_bytes, max(1, (len(s_h) + 1) // 2))
            s_val, e_val, d_val = int(s_h, 16), int(e_h, 16), int(d_h, 16)
            byte_len = max(2, (len(d_h) + 1) // 2)
            for offset in range(min(e_val - s_val + 1, 4096)):
                try:
                    mapping[s_val + offset] = (d_val + offset).to_bytes(byte_len, "big").decode("utf-16-be", errors="replace")
                except Exception:
                    pass
    return mapping, code_bytes


def _decode_pdf_literal(raw: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(raw)
    escapes = {ord('n'): 10, ord('r'): 13, ord('t'): 9, ord('b'): 8, ord('f'): 12,
               ord('('): 40, ord(')'): 41, ord('\\'): 92}
    while i < n:
        ch = raw[i]
        if ch == 92 and i + 1 < n:
            nxt = raw[i + 1]
            if nxt in escapes:
                out.append(escapes[nxt])
                i += 2
            elif nxt in (10, 13):
                i += 3 if (nxt == 13 and i + 2 < n and raw[i + 2] == 10) else 2
            elif 48 <= nxt <= 55:
                oct_d = bytes([nxt])
                j = i + 2
                while j < n and len(oct_d) < 3 and 48 <= raw[j] <= 55:
                    oct_d += bytes([raw[j]])
                    j += 1
                out.append(int(oct_d, 8) & 0xFF)
                i = j
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(ch)
            i += 1
    return bytes(out)


def _decode_text_bytes(raw_bytes: bytes, is_hex: bool, font_info: Optional[Tuple[Dict[int, str], int]]) -> str:
    if not raw_bytes:
        return ""
    if font_info and font_info[0]:
        cmap, bpc = font_info
        if is_hex and bpc == 2 and len(raw_bytes) % 2 == 0:
            return "".join(
                cmap.get((raw_bytes[idx] << 8) | raw_bytes[idx + 1],
                         chr((raw_bytes[idx] << 8) | raw_bytes[idx + 1]) if 32 <= ((raw_bytes[idx] << 8) | raw_bytes[idx + 1]) <= 126 else "")
                for idx in range(0, len(raw_bytes), 2)
            )
        return "".join(cmap.get(b, chr(b) if 32 <= b <= 126 else "") for b in raw_bytes)
    return raw_bytes.decode("cp1252", errors="replace")


def _tokenize_content_stream(stream_bytes: bytes):
    i, n = 0, len(stream_bytes)
    ws, delims = b" \t\r\n\x00\x0c", b"()<>[]{}/%"

    def read_token():
        nonlocal i
        while i < n:
            b = stream_bytes[i]
            if b in ws:
                i += 1
            elif b == 37:
                while i < n and stream_bytes[i] not in (10, 13):
                    i += 1
            else:
                break
        if i >= n:
            return None
        b = stream_bytes[i]
        if b == 40:
            i += 1
            start, depth = i, 1
            while i < n and depth > 0:
                c = stream_bytes[i]
                if c == 92:
                    i += 2
                    continue
                if c == 40:
                    depth += 1
                elif c == 41:
                    depth -= 1
                    if depth == 0:
                        raw = stream_bytes[start:i]
                        i += 1
                        return ("str", _decode_pdf_literal(raw), False)
                i += 1
            return ("str", _decode_pdf_literal(stream_bytes[start:i]), False)
        if b == 60:
            if i + 1 < n and stream_bytes[i + 1] == 60:
                i += 2
                return ("op", "<<")
            i += 1
            end = stream_bytes.find(b">", i)
            if end == -1:
                end = n
            hex_part = re.sub(rb'\s+', b'', stream_bytes[i:end])
            i = min(end + 1, n)
            if len(hex_part) % 2 == 1:
                hex_part += b'0'
            try:
                return ("str", bytes.fromhex(hex_part.decode("ascii")), True)
            except Exception:
                return ("str", b"", True)
        if b == 62:
            if i + 1 < n and stream_bytes[i + 1] == 62:
                i += 2
                return ("op", ">>")
            i += 1
            return ("op", ">")
        if b == 91:
            i += 1
            items = []
            while i < n:
                tok = read_token()
                if tok is None or tok == ("op", "]"):
                    break
                items.append(tok)
            return ("arr", items)
        if b == 93:
            i += 1
            return ("op", "]")
        if b == 47:
            i += 1
            start = i
            while i < n and stream_bytes[i] not in ws and stream_bytes[i] not in delims:
                i += 1
            return ("name", stream_bytes[start:i].decode("latin-1", errors="ignore"))
        start = i
        while i < n and stream_bytes[i] not in ws and stream_bytes[i] not in delims:
            i += 1
        val = stream_bytes[start:i].decode("latin-1", errors="ignore")
        try:
            return ("num", float(val))
        except ValueError:
            return ("op", val)

    tokens = []
    while i < n:
        tok = read_token()
        if tok is None:
            break
        tokens.append(tok)
    return tokens


def _mat_mul(a: Tuple[float, ...], b: Tuple[float, ...]) -> Tuple[float, ...]:
    return (
        a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5],
    )


def _extract_page_lines(
    streams: List[bytes],
    font_maps: Dict[str, Tuple[Dict[int, str], int]],
    merged_fallback: Optional[Tuple[Dict[int, str], int]],
) -> List[str]:
    spans: List[Tuple[float, float, float, str]] = []
    ctm = tm = tlm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    ctm_stack: List[Tuple[float, ...]] = []
    leading, font_name, font_size = 0.0, "", 10.0

    def active_font():
        return font_maps[font_name] if (font_name in font_maps and font_maps[font_name][0]) else merged_fallback

    def emit_span(text: str):
        if not text:
            return
        m_tot = _mat_mul(tm, ctm)
        scale = (m_tot[0] * m_tot[0] + m_tot[1] * m_tot[1]) ** 0.5
        eff_size = max(4.0, abs(font_size * (scale if scale > 1e-4 else 1.0)))
        spans.append((m_tot[5], m_tot[4], eff_size, text))

    for s_bytes in streams:
        operands: List = []
        for tok in _tokenize_content_stream(s_bytes):
            if tok[0] != "op":
                operands.append(tok)
                continue
            op = tok[1]
            if op == "q":
                ctm_stack.append(ctm)
            elif op == "Q" and ctm_stack:
                ctm = ctm_stack.pop()
            elif op == "cm" and len(operands) >= 6:
                ctm = _mat_mul(tuple(float(operands[-6 + k][1]) for k in range(6)), ctm)
            elif op == "BT":
                tm = tlm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            elif op == "Tf" and len(operands) >= 2:
                if operands[-2][0] == "name":
                    font_name = operands[-2][1]
                if operands[-1][0] == "num":
                    font_size = float(operands[-1][1])
            elif op == "TL" and operands and operands[-1][0] == "num":
                leading = float(operands[-1][1])
            elif op == "Tm" and len(operands) >= 6:
                tm = tlm = tuple(float(operands[-6 + k][1]) for k in range(6))
            elif op in ("Td", "TD") and len(operands) >= 2:
                tx, ty = float(operands[-2][1]), float(operands[-1][1])
                if op == "TD":
                    leading = -ty
                tlm = _mat_mul((1.0, 0.0, 0.0, 1.0, tx, ty), tlm)
                tm = tlm
            elif op == "T*":
                tlm = _mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -leading), tlm)
                tm = tlm
            elif op in ("Tj", "'", '"') and operands:
                if op in ("'", '"'):
                    tlm = _mat_mul((1.0, 0.0, 0.0, 1.0, 0.0, -leading), tlm)
                    tm = tlm
                if operands[-1][0] == "str":
                    emit_span(_decode_text_bytes(operands[-1][1], operands[-1][2], active_font()))
            elif op == "TJ" and operands and operands[-1][0] == "arr":
                fi = active_font()
                parts = []
                for item in operands[-1][1]:
                    if item[0] == "str":
                        parts.append(_decode_text_bytes(item[1], item[2], fi))
                    elif item[0] == "num" and float(item[1]) < -120.0:
                        parts.append(" ")
                emit_span("".join(parts))
            operands.clear()

    if not spans:
        return []

    spans.sort(key=lambda sp: (-round(sp[0] / 2.5), sp[1]))
    lines: List[str] = []
    cur_y, row = spans[0][0], []

    def _est_text_width(txt: str, eff: float) -> float:
        total = 0.0
        for ch in txt:
            if ch in "MW@#%&":
                total += 0.78
            elif ch in "iljtI.,;:|!'\"() ":
                total += 0.28
            elif ch.isupper() or ch.isdigit():
                total += 0.58
            else:
                total += 0.50
        return total * eff

    def flush_row():
        if not row:
            return
        row.sort(key=lambda r: r[0])
        out, prev_end_x = [], None
        for x, eff, txt in row:
            if prev_end_x is not None:
                gap = x - prev_end_x
                if gap > max(14.0, eff * 1.4):
                    out.append("  ")
                elif gap > max(2.2, eff * 0.24):
                    out.append(" ")
            out.append(txt)
            prev_end_x = x + _est_text_width(txt, eff)
        line_str = "".join(out).strip()
        if line_str:
            lines.append(line_str)

    for y, x, eff, txt in spans:
        if abs(y - cur_y) > 2.5:
            flush_row()
            row, cur_y = [(x, eff, txt)], y
        else:
            row.append((x, eff, txt))
    flush_row()
    return lines


def _extract_pdf_text_pure_python(file_path: str) -> Optional[str]:
    with open(file_path, "rb") as f:
        data = f.read()
    objects = _scan_pdf_objects(data)
    if not objects:
        return None

    cmap_cache: Dict[int, Tuple[Dict[int, str], int]] = {}
    merged_cmap: Dict[int, str] = {}
    merged_bpc = 1

    def get_cmap(obj_id: int) -> Optional[Tuple[Dict[int, str], int]]:
        nonlocal merged_bpc
        if obj_id in cmap_cache:
            return cmap_cache[obj_id]
        if obj_id not in objects or objects[obj_id][1] is None:
            return None
        dec = _decompress_stream(objects[obj_id][0], objects[obj_id][1])
        if b"beginbfchar" in dec or b"beginbfrange" in dec:
            mp, bpc = _parse_tounicode_cmap(dec)
            cmap_cache[obj_id] = (mp, bpc)
            merged_cmap.update(mp)
            merged_bpc = max(merged_bpc, bpc)
            return cmap_cache[obj_id]
        return None

    for oid in list(objects.keys()):
        tu_m = re.search(rb'/ToUnicode\s+(\d+)\s+\d+\s+R', objects[oid][0])
        if tu_m:
            get_cmap(int(tu_m.group(1)))

    fallback_info = (merged_cmap, merged_bpc) if merged_cmap else None

    def resolve_dict_bytes(raw: bytes, key: bytes) -> bytes:
        inline = re.search(rb'/' + key + rb'\s*<<(.*?)>>', raw, re.S)
        if inline:
            return inline.group(1)
        ref = re.search(rb'/' + key + rb'\s+(\d+)\s+\d+\s+R', raw)
        return objects[int(ref.group(1))][0] if (ref and int(ref.group(1)) in objects) else b""

    def collect_page_fonts(page_hdr: bytes) -> Dict[str, Tuple[Dict[int, str], int]]:
        font_maps: Dict[str, Tuple[Dict[int, str], int]] = {}
        cur_hdr = page_hdr
        for _ in range(8):
            res_bytes = resolve_dict_bytes(cur_hdr, b"Resources") or cur_hdr
            font_bytes = resolve_dict_bytes(res_bytes, b"Font")
            for fname, f_oid in re.findall(rb'/([A-Za-z0-9_+.-]+)\s+(\d+)\s+\d+\s+R', font_bytes):
                oid = int(f_oid)
                if oid in objects:
                    tu_m = re.search(rb'/ToUnicode\s+(\d+)\s+\d+\s+R', objects[oid][0])
                    if tu_m:
                        cm = get_cmap(int(tu_m.group(1)))
                        if cm:
                            font_maps[fname.decode("latin-1", errors="ignore")] = cm
            par_m = re.search(rb'/Parent\s+(\d+)\s+\d+\s+R', cur_hdr)
            if not par_m or int(par_m.group(1)) not in objects:
                break
            cur_hdr = objects[int(par_m.group(1))][0]
        return font_maps

    all_lines: List[str] = []
    for _, (hdr, _) in objects.items():
        if not re.search(rb'/Type\s*/Page(?![A-Za-z])', hdr):
            continue
        arr_m = re.search(rb'/Contents\s*\[(.*?)\]', hdr, re.S)
        if arr_m:
            content_ids = [int(x) for x in re.findall(rb'(\d+)\s+\d+\s+R', arr_m.group(1))]
        else:
            single_m = re.search(rb'/Contents\s+(\d+)\s+\d+\s+R', hdr)
            content_ids = [int(single_m.group(1))] if single_m else []

        streams = [
            _decompress_stream(objects[cid][0], objects[cid][1])
            for cid in content_ids
            if cid in objects and objects[cid][1] is not None
        ]
        streams = [s for s in streams if s]
        if streams:
            all_lines.extend(_extract_page_lines(streams, collect_page_fonts(hdr), fallback_info))

    result = "\n".join(all_lines).strip()
    return result or None


def extract_text_from_pdf(file_path: str) -> Tuple[Optional[str], Optional[str]]:
    if not os.path.exists(file_path):
        return None, f"File not found: {file_path}"
    for extractor in (_extract_with_pdftotext, _extract_with_poppler, _extract_with_python_libs, _extract_pdf_text_pure_python):
        try:
            text = extractor(file_path)
            if text and text.strip():
                return text, None
        except Exception:
            continue
    return None, (
        "Could not extract text from PDF (it may be scanned/image-only or encrypted). "
        "Try copying the schedule text directly from the PDF or print view."
    )


def read_schedule_file_text(file_path: str) -> Tuple[Optional[str], Optional[str]]:
    if os.path.splitext(file_path)[1].lower() == ".pdf":
        return extract_text_from_pdf(file_path)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read(), None
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="cp1252", errors="replace") as f:
            return f.read(), None
    except Exception as e:
        return None, f"Failed to read file: {e}"


def parse_schedule_file(file_path: str) -> Tuple[Optional[ImportedSchedule], Optional[str]]:
    base_name = os.path.splitext(os.path.basename(file_path))[0] or "Schedule"
    hint = "Self-Service PDF" if os.path.splitext(file_path)[1].lower() == ".pdf" else None
    text, err = read_schedule_file_text(file_path)
    if err:
        return None, err
    return parse_schedule_auto(text, default_name=base_name, source_hint=hint)


# =============================================================================
# EMPTY ROOMS & COMMON SLOT ENGINE
# =============================================================================

def normalize_room_location(loc: str) -> Optional[Tuple[str, str]]:
    if not loc:
        return None
    cleaned = re.sub(r'\s+', ' ', str(loc)).strip()
    low = cleaned.lower()
    if low in NON_ROOM_TOKENS or re.search(r'\b(online|virtual|remote|zoom|teams)\b', low):
        return None

    bldg_m = re.search(r'(?:University\s+)?Building\s+([A-Za-z0-9]+)', cleaned, re.IGNORECASE)
    if bldg_m:
        bldg = f"UB{bldg_m.group(1)}"
    elif re.search(r'\b(?:BUB1|GUB1|SUB1|UB1)\b', cleaned, re.IGNORECASE):
        bldg = "UB1"
    elif re.search(r'\b(?:FUB2|GUB2|SUB2|UB2)\b', cleaned, re.IGNORECASE):
        bldg = "UB2"
    else:
        bldg = "Campus"

    room_m = re.search(r'\bRoom\s+([^,]+)$', cleaned, re.IGNORECASE)
    room = room_m.group(1).strip() if room_m else cleaned.split(",")[-1].strip()
    room = re.sub(r'^Room\s+', '', room, flags=re.IGNORECASE).strip()

    if not room or room.lower() in NON_ROOM_TOKENS:
        return None
    return bldg, room


def _natural_room_key(item: Tuple[str, str]):
    bldg, room = item
    parts = [(0, int(p)) if p.isdigit() else (1, p.lower()) for p in re.findall(r'\d+|\D+', room)]
    return (bldg, parts)


def build_room_occupancy_index(course_data: Dict) -> Dict[Tuple[str, str], Dict[int, List[Tuple[int, int]]]]:
    """Builds merged busy intervals per physical room across the entire course catalog."""
    raw_index: Dict[Tuple[str, str], Dict[int, List[Tuple[int, int]]]] = {}
    if not course_data:
        return raw_index

    for course_code, sections in course_data.items():
        if not isinstance(sections, list):
            continue
        for sec in sections:
            for m in iter_section_meetings(course_code, sec):
                room_key = normalize_room_location(m.get("location", ""))
                if room_key:
                    raw_index.setdefault(room_key, {}).setdefault(m["day"], []).append((m["start"], m["end"]))

    for day_map in raw_index.values():
        for day, intervals in day_map.items():
            intervals.sort()
            merged: List[Tuple[int, int]] = []
            for st, en in intervals:
                if merged and st <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], en))
                else:
                    merged.append((st, en))
            day_map[day] = merged

    return raw_index


def find_empty_rooms(
    room_index: Dict[Tuple[str, str], Dict[int, List[Tuple[int, int]]]],
    day: int,
    slot_start: int,
    slot_end: int,
    min_duration: int = 30,
) -> Tuple[List[Tuple[str, str]], List[Tuple[int, str, str, int, int]]]:
    full_rooms: List[Tuple[str, str]] = []
    partial_rooms: List[Tuple[int, str, str, int, int]] = []

    for room_key, day_map in room_index.items():
        overlaps = [
            (max(st, slot_start), min(en, slot_end))
            for st, en in day_map.get(day, [])
            if st < slot_end and en > slot_start
        ]
        if not overlaps:
            full_rooms.append(room_key)
        else:
            cur = slot_start
            best = None
            for o_st, o_en in overlaps:
                if o_st > cur:
                    dur = o_st - cur
                    if dur >= min_duration and (best is None or dur > best[0]):
                        best = (dur, cur, o_st)
                cur = max(cur, o_en)
            if slot_end > cur:
                dur = slot_end - cur
                if dur >= min_duration and (best is None or dur > best[0]):
                    best = (dur, cur, slot_end)
            if best:
                partial_rooms.append((best[0], room_key[0], room_key[1], best[1], best[2]))

    full_rooms.sort(key=_natural_room_key)
    partial_rooms.sort(key=lambda r: (-r[0], _natural_room_key((r[1], r[2]))))
    return full_rooms, partial_rooms


def format_empty_rooms_text(
    room_index: Dict[Tuple[str, str], Dict[int, List[Tuple[int, int]]]],
    day: int,
    slot_start: int,
    slot_end: int,
    min_duration: int = 30,
) -> Tuple[int, str]:
    if not room_index:
        return 0, ""

    full_rooms, partial_rooms = find_empty_rooms(room_index, day, slot_start, slot_end, min_duration)
    if full_rooms:
        by_bldg: Dict[str, List[str]] = {}
        for bldg, room in full_rooms:
            by_bldg.setdefault(bldg, []).append(room)

        lines = [f"Empty Rooms ({len(full_rooms)}):"]
        for bldg, rooms in by_bldg.items():
            shown = rooms[:24]
            extra = f" (+{len(rooms) - 24} more)" if len(rooms) > 24 else ""
            wrapped = textwrap.fill(
                f"• {bldg}: {', '.join(shown)}{extra}",
                width=54,
                subsequent_indent="  ",
            )
            lines.append(wrapped)
        return len(full_rooms), "\n".join(lines)

    if partial_rooms:
        top = partial_rooms[:8]
        lines = ["Partially Empty Rooms:"]
        for _, bldg, room, st, en in top:
            lines.append(f"• {bldg} {room} ({format_minutes(st)}–{format_minutes(en)})")
        return 0, "\n".join(lines)

    return 0, "Empty Rooms: None available in catalog"


def compute_common_slots(
    schedules: List[ImportedSchedule],
    excluded_days: Set[int],
    window_start: int,
    window_end: int,
    min_duration: int,
) -> Dict:
    active = [s for s in schedules if s.enabled]
    free_slots_by_day: Dict[int, List[Dict]] = {}
    busy_segments_by_day: Dict[int, List[Dict]] = {}

    if not active or window_start >= window_end:
        return {
            "active_schedules": active,
            "invalid_window": bool(active and window_start >= window_end),
            "free_slots_by_day": free_slots_by_day,
            "busy_segments_by_day": busy_segments_by_day,
            "total_free_minutes": 0,
            "total_slot_count": 0,
        }

    total_free_minutes, total_slot_count = 0, 0
    for day in range(1, 8):
        if day in excluded_days:
            continue
        points: Set[int] = {window_start, window_end}
        clipped_by_sched: Dict[str, List[Tuple[int, int, Dict]]] = {}

        for sched in active:
            s_intervals = []
            for m in sched.meetings:
                if m.get("day", 0) != day:
                    continue
                st, en = max(m.get("start", -1), window_start), min(m.get("end", -1), window_end)
                if st >= 0 and en > st:
                    points.add(st)
                    points.add(en)
                    s_intervals.append((st, en, m))
            if s_intervals:
                clipped_by_sched[sched.id] = s_intervals

        sorted_pts = sorted(points)
        free_segs: List[Dict] = []
        busy_segs: List[Dict] = []

        for idx in range(len(sorted_pts) - 1):
            t0, t1 = sorted_pts[idx], sorted_pts[idx + 1]
            if t1 <= t0:
                continue
            busy_ids: List[str] = []
            details: Dict[str, List[Dict]] = {}
            for sched in active:
                hits = [m for st, en, m in clipped_by_sched.get(sched.id, []) if st <= t0 and en >= t1]
                if hits:
                    busy_ids.append(sched.id)
                    details[sched.id] = hits

            if not busy_ids:
                if free_segs and free_segs[-1]["end"] == t0:
                    free_segs[-1]["end"] = t1
                    free_segs[-1]["duration"] = t1 - free_segs[-1]["start"]
                else:
                    free_segs.append({"day": day, "start": t0, "end": t1, "duration": t1 - t0})
            else:
                busy_key = frozenset(busy_ids)
                if busy_segs and busy_segs[-1]["end"] == t0 and busy_segs[-1]["busy_key"] == busy_key:
                    prev = busy_segs[-1]
                    prev["end"] = t1
                    for sid, ms in details.items():
                        existing = prev["details"].setdefault(sid, [])
                        for m in ms:
                            if m not in existing:
                                existing.append(m)
                else:
                    busy_segs.append({
                        "day": day, "start": t0, "end": t1,
                        "busy_key": busy_key, "busy_ids": busy_ids, "details": details,
                    })

        qualifying_free = [seg for seg in free_segs if seg["duration"] >= min_duration]
        if qualifying_free:
            free_slots_by_day[day] = qualifying_free
            total_slot_count += len(qualifying_free)
            total_free_minutes += sum(seg["duration"] for seg in qualifying_free)
        if busy_segs:
            busy_segments_by_day[day] = busy_segs

    return {
        "active_schedules": active,
        "invalid_window": False,
        "free_slots_by_day": free_slots_by_day,
        "busy_segments_by_day": busy_segments_by_day,
        "total_free_minutes": total_free_minutes,
        "total_slot_count": total_slot_count,
    }


def format_common_slots_text(
    schedules: List[ImportedSchedule],
    free_slots_by_day: Dict[int, List[Dict]],
    excluded_days: Set[int],
) -> str:
    active_names = [s.name for s in schedules if s.enabled]
    if not active_names:
        return ""
    lines = [f"Common Free Slots ({', '.join(active_names)}):"]
    found_any = False
    for day in range(1, 8):
        if day in excluded_days:
            continue
        slots = free_slots_by_day.get(day, [])
        if not slots:
            continue
        found_any = True
        parts = [f"{format_minutes(s['start'])}–{format_minutes(s['end'])} ({format_duration(s['duration'])})" for s in slots]
        lines.append(f"• {DAY_NAMES[day]}: {', '.join(parts)}")
    if not found_any:
        lines.append("No common free slots match the current filters.")
    return "\n".join(lines)
