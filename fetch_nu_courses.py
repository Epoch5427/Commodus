#!/usr/bin/env python3
"""
fetch_nu_courses.py

Fetch course sections from Nile University self-service using the same
endpoint and payload shape used by Scheds and write output in the requested JSON format.

Usage:
  # Fetch all available courses:
  python fetch_nu_courses.py --out courses.json

  # Fetch only specific courses:
  python fetch_nu_courses.py ECE231 ECE101 --out courses.json

  # Fetch all courses for a specific semester:
  python fetch_nu_courses.py --period 2026/Fall --out courses.json

Dependencies:
  pip install requests
  (optional) pip install python-dateutil
"""

import argparse
import json
import time
from typing import Any, Dict, List
import requests
from requests.adapters import HTTPAdapter, Retry
from datetime import datetime

try:
    from dateutil import parser as dateutil_parser  # optional, nicer parsing
except Exception:
    dateutil_parser = None

# === Endpoint / payload settings from the Scheds repo ===
BASE_URL = "https://register.nu.edu.eg/PowerCampusSelfService/Sections/Search"
WARMUP_URL = "https://register.nu.edu.eg/PowerCampusSelfService/Search/Section"
BATCH_SIZE = 100
REQUEST_TIMEOUT = 30.0
ORIGIN_HEADER = "https://register.nu.edu.eg"
REFERER_HEADER = "https://register.nu.edu.eg/PowerCampusSelfService/Registration/Courses"

# === HTTP session ===
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Origin": ORIGIN_HEADER,
        "Referer": REFERER_HEADER,
        "User-Agent": "scheds-fetcher-python/1.0",
        "Accept": "application/json, text/plain, */*"
    })
    # cookies kept by Session; retry on transient server errors
    retries = Retry(total=3, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s

def warmup(session: requests.Session):
    try:
        session.get(WARMUP_URL, timeout=5)
    except Exception:
        # warmup is best-effort (server-side code does same)
        pass

# === Build payload following SearchRequest and SectionSearchParameters from the repo ===
def build_search_request(course_code: str, start_index: int, length: int, period: str = "") -> Dict[str, Any]:
    section_search = {
        # constructor in C# sets both eventId and keywords to the course code
        "keywords": course_code,
        "eventId": course_code,
        # include other fields with empty defaults to mirror SectionSearchParameters shape
        "eventType": "",
        "eventSubType": "",
        "campusId": "",
        "classLevel": "",
        "college": "",
        "creditType": "",
        "curriculum": "",
        "department": "",
        "endDate": "",
        "endDateKey": "",
        "endTime": "",
        "generalEd": "",
        "instructorId": "",
        "meeting": "",
        "nonTradProgram": "",
        "period": period,
        "population": "",
        "program": "",
        "registrationtype": "",
        "session": "",
        "startDate": "",
        "startTime": "",
        "status": ""
    }
    return {
        "sectionSearchParameters": section_search,
        "startIndex": start_index,
        "length": length
    }

# === Helpers to normalize/parse the server's response ===
def try_unescape_and_strip(resp_text: str) -> str:
    # The C# parsing unescapes and strips surrounding quotes if present.
    t = resp_text
    # Strip surrounding quotes if response looks quoted: starts and ends with a quote char
    if len(t) >= 2 and ((t[0] == '"' and t[-1] == '"') or (t[0] == "'" and t[-1] == "'")):
        t = t[1:-1]
    # Try to decode common escape sequences (like C# Regex.Unescape does)
    try:
        t2 = t.encode("utf-8").decode("unicode_escape")
        return t2
    except Exception:
        return t

def parse_time_string(s: str) -> str:
    """
    Normalize times into h:mm AM/PM format (e.g. '8:30 AM').
    Accepts multiple input formats. If parsing fails, return original trimmed string.
    """
    if not s:
        return ""
    s = s.strip()
    # try dateutil first
    if dateutil_parser:
        try:
            dt = dateutil_parser.parse(s)
            return dt.strftime("%-I:%M %p") if hasattr(dt, "strftime") else s
        except Exception:
            pass
    # try common formats
    fmts = ["%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            return dt.strftime("%-I:%M %p")
        except Exception:
            continue
    # fallback: return original
    return s

def parse_sections_from_response(resp_text: str) -> List[Dict[str, Any]]:
    """
    Return a list of section dictionaries containing schedules as list objects.
    Each parsed item includes a helper "course_code" key used for later grouping.
    """
    raw = try_unescape_and_strip(resp_text)
    parsed_sections: List[Dict[str, Any]] = []
    try:
        j = json.loads(raw)
    except Exception:
        return []

    data = j.get("data") or {}
    sections = data.get("sections")
    if not sections or not isinstance(sections, list):
        return []

    for sec in sections:
        event_name = sec.get("eventName") or ""
        event_id = sec.get("eventId") or ""
        full_title = f"{event_id}: {event_name}" if event_id else event_name

        section_code = sec.get("section") or ""
        subtype = sec.get("eventSubType") or sec.get("eventType") or ""
        seats = sec.get("seatsLeft")
        seats_str = str(seats) if seats is not None else "0"
        credits = sec.get("credits")
        credits_str = f"{float(credits):.2f}" if credits not in (None, "") else "0.00"

        # standardized session formatting
        raw_session = sec.get("session") or sec.get("sessionName") or ""
        raw_session_str = str(raw_session).strip()
        if raw_session_str:
            if raw_session_str.isdigit():
                session_name = f"Session {raw_session_str.zfill(2)}"
            elif raw_session_str.lower().startswith("session"):
                parts = raw_session_str.split(None, 1)
                if len(parts) == 2 and parts[1].isdigit():
                    session_name = f"Session {parts[1].zfill(2)}"
                else:
                    session_name = raw_session_str.capitalize()
            else:
                session_name = f"Session {raw_session_str}"
        else:
            session_name = "N/A"

        # instructors - fallback to "Not Assigned"
        instructors_arr = sec.get("instructors") or []
        instructor_names = []
        if isinstance(instructors_arr, list):
            for instr in instructors_arr:
                name = instr.get("fullName") or instr.get("name")
                if name:
                    instructor_names.append(name)
        instructor_str = ", ".join(instructor_names) if instructor_names else "Not Assigned"

        # schedules (parsed into structures of {day, time, location})
        schedules_arr = sec.get("schedules") or []
        parsed_schedules = []
        if isinstance(schedules_arr, list):
            for sch in schedules_arr:
                day = sch.get("dayDesc") or sch.get("day") or ""
                start = sch.get("startTime") or ""
                end = sch.get("endTime") or ""
                start_f = parse_time_string(start)
                end_f = parse_time_string(end)
                time_str = f"{start_f} - {end_f}" if (start_f and end_f) else ""
                
                # Take location property exactly as is without modifications
                sch_location = sch.get("location") or sch.get("roomId") or ""
                
                parsed_schedules.append({
                    "day": day,
                    "time": time_str,
                    "location": sch_location
                })

        # Section-level fallback for section location
        location_string = sec.get("location") or sec.get("roomId") or ""

        parsed_sections.append({
            "course_code": event_id,  # Helper internal field used for grouping/deduplication
            "fullTitle": full_title,
            "section": section_code,
            "session": session_name,
            "subtype": subtype,
            "schedules": parsed_schedules,
            "location": location_string,
            "instructor": instructor_str,
            "credits": credits_str,
            "seatsLeft": seats_str
        })

    return parsed_sections

# === Fetch loop using paging identical to the repo ===
def fetch_course(session: requests.Session, course_code: str, period: str = "") -> List[Dict[str, Any]]:
    warmup(session)
    all_sections: List[Dict[str, Any]] = []
    start_index = 0
    while True:
        payload = build_search_request(course_code, start_index, BATCH_SIZE, period)
        resp = session.post(BASE_URL, json=payload, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            raise requests.HTTPError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        sections = parse_sections_from_response(resp.text)
        if not sections:
            break
        all_sections.extend(sections)
        # repository code breaks if returned batch < BatchSize
        if len(sections) < BATCH_SIZE:
            break
        start_index += BATCH_SIZE
        time.sleep(0.15)  # polite pacing
    return all_sections

# === Grouping and merging logic with split format support ===
def merge_and_group_sections(sections_list: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Groups raw sections by their course code and merges duplicates.
    Outputs a structured "schedules" array for multi-meeting sections,
    and a singular "schedule" string for single-meeting sections.
    """
    # Step 1: Accumulate unique schedules per section
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    
    for sec in sections_list:
        course_code = sec.get("course_code")
        if not course_code:
            continue
            
        if course_code not in grouped:
            grouped[course_code] = []
            
        # Match sections of the same code and subtype to merge multiple meeting times
        existing_sec = None
        for s in grouped[course_code]:
            if s["section"] == sec["section"] and s["subtype"] == sec["subtype"]:
                existing_sec = s
                break
                
        if existing_sec:
            # Merge schedules if they are unique
            for sch in sec["schedules"]:
                is_duplicate = False
                for existing_sch in existing_sec["schedules"]:
                    if (existing_sch["day"] == sch["day"] and 
                        existing_sch["time"] == sch["time"] and 
                        existing_sch["location"] == sch["location"]):
                        is_duplicate = True
                        break
                if not is_duplicate:
                    existing_sec["schedules"].append(sch)
        else:
            # Store copy of the dictionary for second-pass formatting
            grouped[course_code].append(dict(sec))

    # Step 2: Second-pass format output dynamically depending on schedule count
    final_grouped: Dict[str, List[Dict[str, Any]]] = {}
    for course_code, sec_list in grouped.items():
        final_grouped[course_code] = []
        for sec in sec_list:
            schedules = sec.get("schedules") or []
            
            # Map basic keys in order
            clean_sec = {
                "fullTitle": sec["fullTitle"],
                "section": sec["section"],
                "session": sec["session"],
                "subtype": sec["subtype"],
            }
            
            if len(schedules) == 1:
                # Single schedule layout
                sch = schedules[0]
                day = sch.get("day") or "N/A"
                time_str = sch.get("time") or "N/A"
                sch_field = f"{day}, {time_str}"
                
                clean_sec["schedule"] = sch_field
                clean_sec["location"] = sch.get("location") or ""
            elif len(schedules) > 1:
                # Multiple schedules layout
                clean_sec["schedules"] = schedules
                clean_sec["location"] = "Not specified"
            else:
                # No schedule layout (Unavailable info handling)
                clean_sec["schedule"] = "N/A, N/A"
                clean_sec["location"] = "N/A"
            
            # Append other properties
            clean_sec["instructor"] = sec["instructor"]
            clean_sec["credits"] = sec["credits"]
            clean_sec["seatsLeft"] = sec["seatsLeft"]
            
            final_grouped[course_code].append(clean_sec)
            
    return final_grouped

def main():
    parser = argparse.ArgumentParser(description="Fetch NU course sections using Scheds-style payload.")
    parser.add_argument("courses", nargs="*", help="Optional course codes to fetch (e.g. ECE231). If none, fetches ALL courses.")
    parser.add_argument("--period", default="", help="Academic period (e.g., '2026/Fall', '2025/Fall'). Defaults to empty (current active period).")
    parser.add_argument("--out", "-o", default="courses.json", help="Output JSON file")
    args = parser.parse_args()

    session = make_session()
    all_raw_sections: List[Dict[str, Any]] = []

    if args.courses:
        # Fetch specific courses
        for code in args.courses:
            try:
                print(f"Fetching {code} ...")
                items = fetch_course(session, code, args.period)
                print(f"  -> {len(items)} raw sections fetched")
                all_raw_sections.extend(items)
            except Exception as e:
                print(f"Error fetching {code}: {e}")
    else:
        # Fetch ALL courses automatically
        try:
            print("Fetching all courses ...")
            all_raw_sections = fetch_course(session, "", args.period)
            print(f"  -> Total of {len(all_raw_sections)} raw section entries fetched")
        except Exception as e:
            print(f"Error fetching all courses: {e}")

    # Process raw lists into formatted sections grouped by course
    results = merge_and_group_sections(all_raw_sections)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(results)} courses to {args.out}")

if __name__ == "__main__":
    main()
