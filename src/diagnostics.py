# diagnostics.py

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Set, Tuple

DAY_NAMES = {
    1: "Sunday",
    2: "Monday",
    3: "Tuesday",
    4: "Wednesday",
    5: "Thursday",
    6: "Friday",
    7: "Saturday"
}

DAY_MAP = {
    "SUNDAY": 1,
    "MONDAY": 2,
    "TUESDAY": 3,
    "WEDNESDAY": 4,
    "THURSDAY": 5,
    "FRIDAY": 6,
    "SATURDAY": 7
}


@dataclass
class ConstraintConfig:
    excluded_days: Set[int] = field(default_factory=set)
    time_boundary: Optional[Tuple[int, int]] = None       # (min_start_min, max_end_min)
    gap_window: Optional[Tuple[int, int, int]] = None     # (start_min, end_min, day_idx)
    exclude_full_courses: Set[str] = field(default_factory=set)


class ScheduleDiagnostics:
    """Diagnoses scheduling conflicts, identifies bottlenecks, and provides actionable suggestions."""

    def __init__(
        self,
        course_data: Dict,
        selected_courses: Set[str],
        course_preferences: Dict,
        constraints: ConstraintConfig,
    ):
        self.course_data = course_data
        self.selected_courses = sorted(list(selected_courses))
        self.course_preferences = course_preferences
        self.constraints = constraints

    # =========================================================================
    # TIME STRING PARSING HELPERS
    # =========================================================================

    @staticmethod
    def parse_single_time_str(t_str: str) -> int:
        if not t_str or ":" not in t_str:
            return -1
        cleaned = t_str.upper().strip()
        has_pm = "PM" in cleaned
        has_am = "AM" in cleaned
        cleaned = cleaned.replace("AM", "").replace("PM", "").strip()
        try:
            h, m = map(int, cleaned.split(":"))
            if has_pm and h != 12:
                h += 12
            if has_am and h == 12:
                h = 0
            return h * 60 + m
        except Exception:
            return -1

    @classmethod
    def parse_time_range_str(cls, time_str: str) -> Tuple[int, int]:
        if not time_str or "-" not in time_str:
            return -1, -1
        parts = time_str.split("-")
        return cls.parse_single_time_str(parts[0]), cls.parse_single_time_str(parts[1])

    # =========================================================================
    # COURSE SECTION PACK BUILDER
    # =========================================================================

    def get_course_packs(self, course_code: str) -> List[List[Dict]]:
        sections_list = self.course_data.get(course_code, [])
        if not sections_list:
            return []

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
                    d_int = DAY_MAP.get(s.get("day", "").upper().strip(), 0)
                    s_min, e_min = self.parse_time_range_str(s.get("time", ""))
                    if s_min != -1 and e_min != -1 and (e_min - s_min) % 30 == 29:
                        e_min += 1
                    meetings.append({
                        "course": course_code, "type": subtype, "id": sec_id,
                        "day": d_int, "start": s_min, "end": e_min,
                        "instructor": inst, "seats": seats
                    })
            else:
                sched_str = sec.get("schedule", "")
                if "," in sched_str:
                    d_str, t_str = sched_str.split(",", 1)
                    d_int = DAY_MAP.get(d_str.upper().strip(), 0)
                    s_min, e_min = self.parse_time_range_str(t_str.strip())
                    if s_min != -1 and e_min != -1 and (e_min - s_min) % 30 == 29:
                        e_min += 1
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

        def resolve_sections_for_lecture(section_dict: Dict, lec_id_str: str) -> List[List[Dict]]:
            if not section_dict:
                return [[]]
            if lec_id_str in section_dict:
                return section_dict[lec_id_str]

            clean_lec_num = lec_id_str.lstrip("0")
            for k, v in section_dict.items():
                if k.lstrip("0") == clean_lec_num:
                    return v

            lec_match = re.match(r'^\d+', lec_id_str)
            if lec_match:
                digits = lec_match.group(0).lstrip("0")
                for k, v in section_dict.items():
                    if k.lstrip("0") == digits:
                        return v

            if all(not re.match(r'^\d+', k) for k in section_dict.keys()):
                shared = []
                for sec_meetings in section_dict.values():
                    shared.extend(sec_meetings)
                return shared if shared else [[]]

            return [[]]

        packs = []
        for lec_id, lec_meetings in lectures.items():
            avail_labs = resolve_sections_for_lecture(labs, lec_id)
            avail_tuts = resolve_sections_for_lecture(tutorials, lec_id)

            for lab_m in avail_labs:
                for tut_m in avail_tuts:
                    packs.append(list(lec_meetings) + list(lab_m) + list(tut_m))

        return packs

    # =========================================================================
    # BACKTRACKING COMBINATORIAL SOLVER
    # =========================================================================

    @staticmethod
    def find_one_valid_combination(packs_by_course_list: List[List[List[Dict]]]) -> bool:
        num_courses = len(packs_by_course_list)
        if num_courses == 0:
            return True

        sorted_courses = sorted(packs_by_course_list, key=len)
        if any(len(packs) == 0 for packs in sorted_courses):
            return False

        def backtrack(course_idx: int, chosen_meetings: List[Dict]) -> bool:
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
                    if backtrack(course_idx + 1, chosen_meetings):
                        return True
                    del chosen_meetings[-len(pack):]

            return False

        return backtrack(0, [])

    # =========================================================================
    # PACK FILTERING LOGIC
    # =========================================================================

    def filter_packs(
        self,
        course_code: str,
        raw_packs: List[List[Dict]],
        ignore_prefs: bool = False,
        ignore_time: bool = False,
        ignore_gap: bool = False,
        ignore_days: bool = False,
        ignore_full: bool = False
    ) -> List[List[Dict]]:
        excluded_days = self.constraints.excluded_days if not ignore_days else set()

        time_boundary = self.constraints.time_boundary if not ignore_time else None
        min_start = time_boundary[0] if time_boundary else 0
        max_end = time_boundary[1] if time_boundary else 24 * 60

        gap_window = self.constraints.gap_window if not ignore_gap else None
        gap_start, gap_end, gap_day = gap_window if gap_window else (-1, -1, 0)

        exclude_full = (course_code in self.constraints.exclude_full_courses) if not ignore_full else False

        pref = self.course_preferences.get(course_code, {})
        pref_type = pref.get("type", "Neither")
        pref_val = pref.get("value", [])
        if isinstance(pref_val, str) and pref_val:
            pref_val = [pref_val]

        lec_pref_set = set()
        lab_pref_set = set()
        tut_pref_set = set()

        if pref_type == "Section" and pref_val:
            for p in pref_val:
                if ":" in p:
                    ptype, pid = p.split(":", 1)
                    if ptype == "Lecture": lec_pref_set.add(pid)
                    elif ptype == "Lab": lab_pref_set.add(pid)
                    elif ptype == "Tutorial": tut_pref_set.add(pid)
                else:
                    lec_pref_set.add(p)
                    lab_pref_set.add(p)
                    tut_pref_set.add(p)

        has_lec_pref = bool(lec_pref_set)
        has_lab_pref = bool(lab_pref_set)
        has_tut_pref = bool(tut_pref_set)

        valid_packs = []
        for pack in raw_packs:
            if not ignore_prefs:
                if pref_type == "Instructor" and pref_val:
                    if not any(any(p_inst.lower() in m.get("instructor", "").lower() for p_inst in pref_val) for m in pack):
                        continue
                elif pref_type == "Section" and pref_val:
                    failed_pref = False
                    if has_lec_pref and not any(m.get("type") == "Lecture" and m.get("id") in lec_pref_set for m in pack):
                        failed_pref = True
                    if has_lab_pref and not any(m.get("type") == "Lab" and m.get("id") in lab_pref_set for m in pack):
                        failed_pref = True
                    if has_tut_pref and not any(m.get("type") == "Tutorial" and m.get("id") in tut_pref_set for m in pack):
                        failed_pref = True
                    if failed_pref:
                        continue

            if exclude_full and any(m.get("seats", -1) == 0 for m in pack):
                continue
            if any(m.get("day", 0) in excluded_days for m in pack):
                continue
            if time_boundary and any(m.get("start", -1) < min_start or m.get("end", -1) > max_end for m in pack if m.get("day", 0) > 0):
                continue
            if gap_window and gap_start != -1 and gap_end != -1:
                if any(m.get("day", 0) > 0 and (gap_day == 0 or m.get("day") == gap_day) and (m.get("start", -1) < gap_end and m.get("end", -1) > gap_start) for m in pack):
                    continue

            valid_packs.append(pack)

        return valid_packs

    # =========================================================================
    # PREFERENCE INTROSPECTION
    # =========================================================================

    def get_pref_description(self, course_code: str) -> str:
        pref = self.course_preferences.get(course_code, {})
        ptype = pref.get("type", "Neither")
        pval = pref.get("value", "")
        if ptype == "Instructor" and pval:
            if isinstance(pval, list):
                return f"Instructor: {', '.join(pval)}"
            return f"Instructor: {pval}"
        elif ptype == "Section" and pval:
            if isinstance(pval, list):
                clean_vals = [v.split(":", 1)[1] if ":" in v else v for v in pval]
                return f"Section(s): {', '.join(clean_vals)}"
            clean_val = pval.split(":", 1)[1] if ":" in pval else pval
            return f"Section {clean_val}"
        return "Any"

    def has_active_filter(self, course_code: str) -> bool:
        pref = self.course_preferences.get(course_code)
        if not pref or not isinstance(pref, dict):
            return False
        ptype = pref.get("type")
        pval = pref.get("value")
        if ptype in ("Instructor", "Section"):
            if isinstance(pval, list):
                return any(bool(x and str(x).strip()) for x in pval)
            return bool(pval and str(pval).strip())
        return False

    def find_pref_blocker_reason(self, course_code: str, raw_packs: List[List[Dict]]) -> Tuple[str, Optional[Tuple[str, str]]]:
        pref_packs = self.filter_packs(
            course_code, raw_packs, ignore_prefs=False,
            ignore_time=True, ignore_gap=True, ignore_days=True, ignore_full=True
        )
        if not pref_packs:
            return "is not available in the database", None

        exclude_full_for_c = course_code in self.constraints.exclude_full_courses
        if exclude_full_for_c:
            if not self.filter_packs(course_code, pref_packs, ignore_prefs=False, ignore_full=False):
                return "is full or has no open lab/tutorial seats remaining", ("full", "")

        if self.constraints.gap_window:
            if not self.filter_packs(course_code, pref_packs, ignore_prefs=False, ignore_gap=False):
                g_start, g_end, _ = self.constraints.gap_window
                g_str = f"{g_start // 60:02d}:{g_start % 60:02d}–{g_end // 60:02d}:{g_end % 60:02d}"
                return f"collides with your Specified Gap (<b>{g_str}</b>)", ("gap", g_str)

        if self.constraints.time_boundary:
            if not self.filter_packs(course_code, pref_packs, ignore_prefs=False, ignore_time=False):
                t_start, t_end = self.constraints.time_boundary
                t_str = f"{t_start // 60:02d}:{t_start % 60:02d}–{t_end // 60:02d}:{t_end % 60:02d}"
                return f"falls outside your Time Boundary (<b>{t_str}</b>)", ("time", t_str)

        if self.constraints.excluded_days:
            if not self.filter_packs(course_code, pref_packs, ignore_prefs=False, ignore_days=False):
                days_hit = {DAY_NAMES.get(m["day"]) for pack in pref_packs for m in pack if m.get("day", 0) in self.constraints.excluded_days}
                d_str = ", ".join(filter(None, days_hit))
                return f"requires attending on an Excluded Day (<b>{d_str}</b>)", ("day", d_str)

        return "violates active constraints", None

    # =========================================================================
    # MAIN DIAGNOSIS ENTRY POINT
    # =========================================================================

    def diagnose(self) -> Tuple[List[str], List[str]]:
        issues = []
        suggestions_dict = {}

        if not self.selected_courses:
            return issues, []

        has_excluded_days = len(self.constraints.excluded_days) > 0
        time_enabled = self.constraints.time_boundary is not None
        gap_enabled = self.constraints.gap_window is not None
        exclude_full_enabled = len(self.constraints.exclude_full_courses) > 0

        raw_packs_by_course = {c: self.get_course_packs(c) for c in self.selected_courses}
        unfiltered_packs = {c: self.filter_packs(c, raw_packs_by_course[c], ignore_prefs=True) for c in self.selected_courses}
        filtered_packs = {c: self.filter_packs(c, raw_packs_by_course[c], ignore_prefs=False) for c in self.selected_courses}

        time_blocked = []
        gap_blocked = []
        day_blocked = {}
        full_blocked = []

        # 1. Single course checks
        for c in self.selected_courses:
            raw_p = raw_packs_by_course[c]
            glob_p = unfiltered_packs[c]

            if not raw_p:
                issues.append(f"<b>{c}</b>: No class sections found in database.")
                continue

            if not glob_p:
                is_individually_categorized = False
                exclude_full_for_c = c in self.constraints.exclude_full_courses
                if exclude_full_for_c and self.filter_packs(c, raw_p, ignore_prefs=True, ignore_full=True):
                    full_blocked.append(c)
                    is_individually_categorized = True
                if time_enabled and self.filter_packs(c, raw_p, ignore_prefs=True, ignore_time=True):
                    time_blocked.append(c)
                    is_individually_categorized = True
                if gap_enabled and self.filter_packs(c, raw_p, ignore_prefs=True, ignore_gap=True):
                    gap_blocked.append(c)
                    is_individually_categorized = True
                if has_excluded_days and self.filter_packs(c, raw_p, ignore_prefs=True, ignore_days=True):
                    days_hit = {DAY_NAMES.get(m["day"]) for pack in raw_p for m in pack if m.get("day", 0) in self.constraints.excluded_days}
                    d_str = ", ".join(filter(None, days_hit))
                    day_blocked.setdefault(d_str, []).append(c)
                    is_individually_categorized = True

                if not is_individually_categorized:
                    issues.append(f"<b>{c}</b>: All sections violate active time, day, or capacity constraints.")

        if full_blocked or time_blocked or gap_blocked or day_blocked:
            if full_blocked:
                c_str = ", ".join(f"<b>{c}</b>" for c in full_blocked)
                issues.append(f"<b>Full Classes:</b> All available sections (or their required labs/tutorials) of {c_str} have 0 seats remaining.")
                suggestions_dict["full"] = f"Deselect {c_str} in 'Exclude Full Classes' or turn it off."

            if time_blocked:
                c_str = ", ".join(f"<b>{c}</b>" for c in time_blocked)
                t_start, t_end = self.constraints.time_boundary
                t_str = f"{t_start // 60:02d}:{t_start % 60:02d}–{t_end // 60:02d}:{t_end % 60:02d}"
                issues.append(f"<b>Time Boundary ({t_str}):</b> All sections of {c_str} fall outside allowed hours.")
                suggestions_dict["time"] = f"Widen or disable your Start / End time boundary ({t_str})."

            if gap_blocked and gap_enabled:
                c_str = ", ".join(f"<b>{c}</b>" for c in gap_blocked)
                g_start, g_end, _ = self.constraints.gap_window
                g_str = f"{g_start // 60:02d}:{g_start % 60:02d}–{g_end // 60:02d}:{g_end % 60:02d}"
                issues.append(f"<b>Specified Gap ({g_str}):</b> All sections of {c_str} collide with your gap window.")
                suggestions_dict["gap"] = f"Adjust or disable your specified gap ({g_str})."

            for d_str, courses in day_blocked.items():
                c_str = ", ".join(f"<b>{c}</b>" for c in courses)
                issues.append(f"<b>Excluded Day ({d_str}):</b> Every section of {c_str} requires attending on {d_str}.")
                suggestions_dict[f"day_{d_str}"] = f"Un-exclude {d_str} in Constraints."

            return issues, list(suggestions_dict.values())

        # 2. Preference self-block checks
        pref_self_blocked = []
        for c in self.selected_courses:
            glob_p = unfiltered_packs[c]
            filt_p = filtered_packs[c]
            if not filt_p and glob_p and self.has_active_filter(c):
                pref_self_blocked.append((c, self.get_pref_description(c), len(glob_p)))

        if pref_self_blocked:
            for c, p_desc, alt_count in pref_self_blocked:
                reason_text, blocker_tuple = self.find_pref_blocker_reason(c, raw_packs_by_course[c])
                issues.append(f"<b>Filter Conflict on {c}:</b> Selected <i>{p_desc}</i> {reason_text}. <b>{alt_count}</b> other section(s) exist if unlocked.")

                if blocker_tuple:
                    b_type, b_val = blocker_tuple
                    if b_type == "full":
                        suggestions_dict["full"] = f"Deselect {c} in 'Exclude Full Classes' to allow {p_desc}."
                    elif b_type == "gap":
                        suggestions_dict["gap"] = f"Adjust or disable your specified gap ({b_val}) to allow {p_desc}."
                    elif b_type == "time":
                        suggestions_dict["time"] = f"Widen or disable your Time Boundary ({b_val}) to allow {p_desc}."
                    elif b_type == "day":
                        suggestions_dict[f"day_{b_val}"] = f"Un-exclude {b_val} to allow {p_desc}."

                suggestions_dict[f"pref_{c}"] = f"Or unlock {c} to use an alternative section."

            return issues, list(suggestions_dict.values())

        # 3. Multi-course combinatorial bottleneck analysis
        can_fit_all_any = self.find_one_valid_combination([unfiltered_packs[c] for c in self.selected_courses])

        active_filtered_courses = [
            c for c in self.selected_courses
            if self.has_active_filter(c) and len(unfiltered_packs[c]) > len(filtered_packs[c])
        ]

        if can_fit_all_any and active_filtered_courses:
            culprit_found = False

            for c_test in active_filtered_courses:
                test_set = [unfiltered_packs[c] if c == c_test else filtered_packs[c] for c in self.selected_courses]
                if self.find_one_valid_combination(test_set):
                    p_desc = self.get_pref_description(c_test)
                    issues.append(f"<b>Filter Bottleneck on {c_test}:</b> Filter (<i>{p_desc}</i>) blocks all combinations with other courses. Unlocking <b>{c_test}</b> yields valid schedules.")
                    suggestions_dict[f"pref_{c_test}"] = f"Unlock {c_test} (allow any section/instructor)."
                    culprit_found = True

            if not culprit_found and len(active_filtered_courses) >= 2:
                for i in range(len(active_filtered_courses)):
                    for j in range(i + 1, len(active_filtered_courses)):
                        c1, c2 = active_filtered_courses[i], active_filtered_courses[j]
                        test_set = [unfiltered_packs[c] if c in (c1, c2) else filtered_packs[c] for c in self.selected_courses]
                        if self.find_one_valid_combination(test_set):
                            p1_desc = self.get_pref_description(c1)
                            p2_desc = self.get_pref_description(c2)
                            issues.append(f"<b>Combined Filter Conflict:</b> Filters on <b>{c1}</b> (<i>{p1_desc}</i>) and <b>{c2}</b> (<i>{p2_desc}</i>) prevent fitting all courses together.")
                            suggestions_dict[f"pref_{c1}_{c2}"] = f"Unlock {c1} or {c2} (allow any section/instructor)."
                            culprit_found = True
                            break
                    if culprit_found:
                        break

            if not culprit_found:
                issues.append(f"<b>Course Filters:</b> Locked sections/instructors across multiple courses leave no open slots for all {len(self.selected_courses)} courses.")
                suggestions_dict["reset_all_prefs"] = "Unlock course filters to allow flexible combinations."

        else:
            if exclude_full_enabled:
                no_full_packs = [self.filter_packs(c, raw_packs_by_course[c], ignore_prefs=True, ignore_full=True) for c in self.selected_courses]
                if self.find_one_valid_combination(no_full_packs):
                    culprit_courses = []
                    for c_test in self.selected_courses:
                        test_set = [
                            self.filter_packs(c, raw_packs_by_course[c], ignore_prefs=True, ignore_full=(c == c_test))
                            for c in self.selected_courses
                        ]
                        if self.find_one_valid_combination(test_set):
                            culprit_courses.append(c_test)

                    if culprit_courses:
                        c_names = ", ".join(f"<b>{c}</b>" for c in culprit_courses)
                        issues.append(f"<b>Full Sections on {c_names}:</b> Compatible combinations exist if full sections (or their tutorials/labs) for {c_names} are included.")
                        suggestions_dict["full"] = f"Deselect {c_names} in 'Exclude Full Classes' or turn it off."
                    else:
                        issues.append("<b>Full Classes Blocking Schedules:</b> Remaining open sections conflict with each other. Conflict-free schedules exist if full classes (or tutorials/labs) are included.")
                        suggestions_dict["full"] = "Turn off 'Exclude Full Classes' or deselect some courses."

            if time_enabled:
                no_time_packs = [self.filter_packs(c, raw_packs_by_course[c], ignore_prefs=True, ignore_time=True) for c in self.selected_courses]
                if self.find_one_valid_combination(no_time_packs):
                    t_start, t_end = self.constraints.time_boundary
                    t_str = f"{t_start // 60:02d}:{t_start % 60:02d}–{t_end // 60:02d}:{t_end % 60:02d}"
                    issues.append(f"<b>Time Boundary Too Strict ({t_str}):</b> Allowed hours cannot accommodate all {len(self.selected_courses)} courses.")
                    suggestions_dict["time"] = f"Widen or disable your Start / End time boundary ({t_str})."

            if gap_enabled:
                no_gap_packs = [self.filter_packs(c, raw_packs_by_course[c], ignore_prefs=True, ignore_gap=True) for c in self.selected_courses]
                if self.find_one_valid_combination(no_gap_packs):
                    g_start, g_end, _ = self.constraints.gap_window
                    g_str = f"{g_start // 60:02d}:{g_start % 60:02d}–{g_end // 60:02d}:{g_end % 60:02d}"
                    issues.append(f"<b>Gap Constraint Conflict ({g_str}):</b> Specified gap leaves too little remaining time for all courses.")
                    suggestions_dict["gap"] = f"Adjust or disable your specified gap ({g_str})."

            if has_excluded_days:
                no_days_packs = [self.filter_packs(c, raw_packs_by_course[c], ignore_prefs=True, ignore_days=True) for c in self.selected_courses]
                if self.find_one_valid_combination(no_days_packs):
                    issues.append("<b>Too Many Excluded Days:</b> Excluded days leave too few available days for all courses.")
                    suggestions_dict["days"] = "Allow classes on one or more excluded days."

            if not issues:
                issues.append(f"<b>Schedule Overlap:</b> No conflict-free combination exists containing all <b>{len(self.selected_courses)}</b> selected courses.")
                sugg_actions = ["Try deselecting 1 course"]
                if exclude_full_enabled:
                    sugg_actions.append("allowing full classes")
                if time_enabled or gap_enabled or has_excluded_days:
                    sugg_actions.append("loosening time/day constraints")

                if len(sugg_actions) == 1:
                    suggestions_dict["remove_course"] = f"{sugg_actions[0]}."
                elif len(sugg_actions) == 2:
                    suggestions_dict["remove_course"] = f"{sugg_actions[0]} or {sugg_actions[1]}."
                else:
                    suggestions_dict["remove_course"] = f"{sugg_actions[0]}, {sugg_actions[1]}, or {sugg_actions[2]}."

        return issues, list(suggestions_dict.values())
