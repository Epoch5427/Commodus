#!/usr/bin/env python3
"""
fetch_nu_courses.py

Fetch course sections from Nile University self-service using the same
endpoint and payload shape used by Scheds and write output in the requested JSON format.

Usage:
  # Fetch all available courses:
  python fetch_nu_courses.py --out courses.json

  # Fetch ignoring broken SSL certificate chains:
  python fetch_nu_courses.py --insecure --out courses.json

  # Fetch only specific courses:
  python fetch_nu_courses.py ECE231 ECE101 --out courses.json
"""

import argparse
import json
import sys
import time
from typing import Any, Dict, List
import requests
from requests.adapters import HTTPAdapter, Retry
import urllib3
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
def make_session(verify_ssl: bool = True) -> requests.Session:
    s = requests.Session()
    s.verify = verify_ssl
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        # warmup is best-effort
        pass

# === Build payload following SearchRequest and SectionSearchParameters ===
def build_search_request(course_code: str, start_index: int, length: int, period: str = "") -> Dict[str, Any]:
    section_search = {
        "keywords": course_code,
        "eventId": course_code,
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

def try_unescape_and_strip(resp_text: str) -> str:
    t = resp_text
    if len(t) >= 2 and ((t[0] == '"' and t[-1] == '"') or (t[0] == "'" and t[-1] == "'")):
        t = t[1:-1]
    try:
        return t.encode("utf-8").decode("unicode_escape")
    except Exception:
        return t

def parse_time_string(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    if dateutil_parser:
        try:
            dt = dateutil_parser.parse(s)
            return dt.strftime("%-I:%M %p") if hasattr(dt, "strftime") else s
        except Exception:
            pass
    fmts = ["%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            return dt.strftime("%-I:%M %p")
        except Exception:
            continue
    return s

def parse_sections_from_response(resp_text: str) -> List[Dict[str, Any]]:
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

        instructors_arr = sec.get("instructors") or []
        instructor_names = []
        if isinstance(instructors_arr, list):
            for instr in instructors_arr:
                name = instr.get("fullName") or instr.get("name")
                if name:
                    instructor_names.append(name)
        instructor_str = ", ".join(instructor_names) if instructor_names else "Not Assigned"

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
                sch_location = sch.get("location") or sch.get("roomId") or ""
                
                parsed_schedules.append({
                    "day": day,
                    "time": time_str,
                    "location": sch_location
                })

        location_string = sec.get("location") or sec.get("roomId") or ""

        parsed_sections.append({
            "course_code": event_id,
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
        if len(sections) < BATCH_SIZE:
            break
        start_index += BATCH_SIZE
        time.sleep(0.15)
    return all_sections

def merge_and_group_sections(sections_list: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    
    for sec in sections_list:
        course_code = sec.get("course_code")
        if not course_code:
            continue
            
        if course_code not in grouped:
            grouped[course_code] = []
            
        existing_sec = None
        for s in grouped[course_code]:
            if s["section"] == sec["section"] and s["subtype"] == sec["subtype"]:
                existing_sec = s
                break
                
        if existing_sec:
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
            grouped[course_code].append(dict(sec))

    final_grouped: Dict[str, List[Dict[str, Any]]] = {}
    for course_code, sec_list in grouped.items():
        final_grouped[course_code] = []
        for sec in sec_list:
            schedules = sec.get("schedules") or []
            
            clean_sec = {
                "fullTitle": sec["fullTitle"],
                "section": sec["section"],
                "session": sec["session"],
                "subtype": sec["subtype"],
            }
            
            if len(schedules) == 1:
                sch = schedules[0]
                day = sch.get("day") or "N/A"
                time_str = sch.get("time") or "N/A"
                clean_sec["schedule"] = f"{day}, {time_str}"
                clean_sec["location"] = sch.get("location") or ""
            elif len(schedules) > 1:
                clean_sec["schedules"] = schedules
                clean_sec["location"] = "Not specified"
            else:
                clean_sec["schedule"] = "N/A, N/A"
                clean_sec["location"] = "N/A"
            
            clean_sec["instructor"] = sec["instructor"]
            clean_sec["credits"] = sec["credits"]
            clean_sec["seatsLeft"] = sec["seatsLeft"]
            
            final_grouped[course_code].append(clean_sec)
            
    return final_grouped

def main():
    parser = argparse.ArgumentParser(description="Fetch NU course sections.")
    parser.add_argument("courses", nargs="*", help="Optional course codes to fetch (e.g. ECE231). If none, fetches ALL.")
    parser.add_argument("--period", default="", help="Academic period (e.g., '2026/Fall').")
    parser.add_argument("--out", "-o", default="courses.json", help="Output JSON file")
    parser.add_argument("--insecure", "-k", action="store_true", help="Allow insecure SSL connections (skip certificate verification)")
    args = parser.parse_args()

    session = make_session(verify_ssl=not args.insecure)
    all_raw_sections: List[Dict[str, Any]] = []

    try:
        if args.courses:
            for code in args.courses:
                print(f"Fetching {code} ...")
                items = fetch_course(session, code, args.period)
                print(f"  -> {len(items)} raw sections fetched")
                all_raw_sections.extend(items)
        else:
            print("Fetching all courses ...")
            all_raw_sections = fetch_course(session, "", args.period)
            print(f"  -> Total of {len(all_raw_sections)} raw section entries fetched")
    except Exception as e:
        print(f"\n[FATAL ERROR] Failed while fetching courses: {e}", file=sys.stderr)
        print("Aborting. Existing database will NOT be overwritten.", file=sys.stderr)
        sys.exit(1)

    if not all_raw_sections:
        print("\n[FATAL ERROR] 0 courses fetched from server.", file=sys.stderr)
        print("Aborting. Existing database will NOT be overwritten.", file=sys.stderr)
        sys.exit(1)

    results = merge_and_group_sections(all_raw_sections)

    if not results:
        print("\n[FATAL ERROR] No valid course data produced after processing.", file=sys.stderr)
        sys.exit(1)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Successfully wrote {len(results)} courses to {args.out}")

if __name__ == "__main__":
    main()
