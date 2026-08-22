#include <iostream>
#include <vector>
#include <string>
#include <iomanip>
#include <cmath>
#include <fstream>
#include <map>
#include <set>
#include <algorithm>
#include <stdexcept>
#include <numeric>
#include <filesystem>
#include <sstream>

#include "json.hpp"

namespace fs = std::filesystem;
using json = nlohmann::json;

struct Meeting
{
    std::string course, type, id, location, instructor;
    int day, start, end, seats;
};

struct LectureOption
{
    std::string lectureId;
    std::vector<Meeting> lectureMeetings;
    std::vector<std::vector<Meeting>> labs, tutorials;
};

struct Course
{
    std::string name, title;
    std::vector<LectureOption> options;
};

struct ScheduleResult
{
    std::vector<Meeting> meetings;
    int numDays, totalGapMinutes, maxDailyClasses;
    double timeConsistencyScore, score;
    bool operator<(const ScheduleResult &other) const { return score < other.score; }
};

struct Constraints
{
    std::set<int> excludedDays;
    int maxEndTime = 24 * 60;
    int minStartTime = 0;

    int gapStartTime = -1;
    int gapEndTime = -1;
    int gapDay = 0;

    std::map<std::string, std::vector<std::string>> preferredInstructors;
    bool filterZeroSeats = false;
    std::map<std::string, std::set<std::string>> specificSections;
};

inline void writeJsonString(std::ostream &os, const std::string &s) {
    os << '"';
    for (char c : s) {
        if (c == '"') os << "\\\"";
        else if (c == '\\') os << "\\\\";
        else if (c == '\b') os << "\\b";
        else if (c == '\f') os << "\\f";
        else if (c == '\n') os << "\\n";
        else if (c == '\r') os << "\\r";
        else if (c == '\t') os << "\\t";
        else os << c;
    }
    os << '"';
}

// Emits format: <score>\t[ [course, type, id, loc, inst, day, start, end, seats], ... ]\n
void outputSchedule(const ScheduleResult &r) {
    std::cout << r.score << '\t' << '[';
    for (size_t i = 0; i < r.meetings.size(); ++i) {
        const auto &m = r.meetings[i];
        if (i > 0) std::cout << ',';
        std::cout << '[';
        writeJsonString(std::cout, m.course);
        std::cout << ',';
        writeJsonString(std::cout, m.type);
        std::cout << ',';
        writeJsonString(std::cout, m.id);
        std::cout << ',';
        writeJsonString(std::cout, m.location);
        std::cout << ',';
        writeJsonString(std::cout, m.instructor);
        std::cout << ',' << m.day << ',' << m.start << ',' << m.end << ',' << m.seats << ']';
    }
    std::cout << "]\n";
}

int parseTime(const std::string &timeStr)
{
    if (timeStr.empty() || timeStr.find("N/A") != std::string::npos)
        return -1;

    std::string cleanedTime = timeStr;
    bool has_pm = (cleanedTime.find("PM") != std::string::npos) || (cleanedTime.find("pm") != std::string::npos);
    bool has_am = (cleanedTime.find("AM") != std::string::npos) || (cleanedTime.find("am") != std::string::npos);
    bool is_12_hour_format = has_pm || has_am;

    size_t am_pos = cleanedTime.find(" AM");
    if (am_pos != std::string::npos) cleanedTime.erase(am_pos, 3);
    size_t pm_pos = cleanedTime.find(" PM");
    if (pm_pos != std::string::npos) cleanedTime.erase(pm_pos, 3);

    am_pos = cleanedTime.find("AM");
    if (am_pos != std::string::npos) cleanedTime.erase(am_pos, 2);
    pm_pos = cleanedTime.find("PM");
    if (pm_pos != std::string::npos) cleanedTime.erase(pm_pos, 2);

    size_t colon_pos = cleanedTime.find(":");
    if (colon_pos == std::string::npos)
        return -1;

    try
    {
        int hh = std::stoi(cleanedTime.substr(0, colon_pos));
        int mm = std::stoi(cleanedTime.substr(colon_pos + 1));

        if (is_12_hour_format) {
            if (has_pm && hh != 12)
                hh += 12;
            if (has_am && hh == 12)
                hh = 0;
        }

        return hh * 60 + mm;
    }
    catch (const std::exception &)
    {
        return -1;
    }
}

std::map<std::string, int> dayStringToInt = {
    {"SUNDAY", 1}, {"MONDAY", 2}, {"TUESDAY", 3}, {"WEDNESDAY", 4},
    {"THURSDAY", 5}, {"FRIDAY", 6}, {"SATURDAY", 7}
};

std::vector<Meeting> parseMeetings(const std::string &courseCode, const json &sectionJson)
{
    std::vector<Meeting> meetings;
    int seatsVal = -1;
    if (sectionJson.contains("seatsLeft") && sectionJson["seatsLeft"].is_string())
    {
        try
        {
            seatsVal = std::stoi(sectionJson["seatsLeft"].get<std::string>());
        }
        catch (const std::exception &e)
        {
            seatsVal = -1;
        }
    }
    std::string instructor = sectionJson.value("instructor", "Not Assigned");
    if (sectionJson.contains("schedules") && sectionJson["schedules"].is_array())
    {
        for (const auto &schedule_item : sectionJson["schedules"])
        {
            Meeting m;
            m.course = courseCode;
            m.type = sectionJson.value("subtype", "N/A");
            m.id = sectionJson.value("section", "N/A");
            m.location = schedule_item.value("location", "N/A");
            m.instructor = instructor;
            m.seats = seatsVal;
            std::string dayStr = schedule_item.value("day", "");
            transform(dayStr.begin(), dayStr.end(), dayStr.begin(), ::toupper);
            m.day = dayStringToInt.count(dayStr) ? dayStringToInt[dayStr] : 0;
            std::string timeRangeStr = schedule_item.value("time", "");
            size_t dashPos = timeRangeStr.find('-');
            if (dashPos != std::string::npos)
            {
                m.start = parseTime(timeRangeStr.substr(0, dashPos));
                m.end = parseTime(timeRangeStr.substr(dashPos + 1));
            }
            else
            {
                m.start = -1;
                m.end = -1;
            }
            meetings.push_back(m);
        }
    }
    else
    {
        Meeting m;
        m.course = courseCode;
        m.type = sectionJson.value("subtype", "N/A");
        m.id = sectionJson.value("section", "N/A");
        m.location = sectionJson.value("location", "N/A");
        m.instructor = instructor;
        m.seats = seatsVal;
        std::string scheduleStr = sectionJson.value("schedule", "N/A");
        size_t commaPos = scheduleStr.find(',');
        if (commaPos != std::string::npos)
        {
            std::string dayStr = scheduleStr.substr(0, commaPos);
            transform(dayStr.begin(), dayStr.end(), dayStr.begin(), ::toupper);
            m.day = dayStringToInt.count(dayStr) ? dayStringToInt[dayStr] : 0;
            std::string timeRangeStr = scheduleStr.substr(commaPos + 2);
            size_t dashPos = timeRangeStr.find('-');
            if (dashPos != std::string::npos)
            {
                m.start = parseTime(timeRangeStr.substr(0, dashPos));
                m.end = parseTime(timeRangeStr.substr(dashPos + 1));
            }
            else
            {
                m.start = -1;
                m.end = -1;
            }
        }
        else
        {
            m.day = 0;
            m.start = -1;
            m.end = -1;
        }
        meetings.push_back(m);
    }
    return meetings;
}

std::vector<Course> loadCoursesFromJson(const std::string &filename)
{
    std::ifstream ifs(filename);
    if (!ifs.is_open())
        throw std::runtime_error("Could not open file: " + filename);
    json j;
    ifs >> j;
    std::vector<Course> courses;
    for (auto &[courseCode, sectionsJson] : j.items())
    {
        Course currentCourse;
        currentCourse.name = courseCode;
        for (const auto &sectionJson : sectionsJson)
        {
            if (sectionJson.contains("fullTitle") && sectionJson["fullTitle"].is_string())
            {
                std::string fullTitleStr = sectionJson.value("fullTitle", "");
                size_t pos = fullTitleStr.find(": ");
                if (pos != std::string::npos)
                {
                    currentCourse.title = fullTitleStr.substr(pos + 2);
                }
                else
                {
                    currentCourse.title = fullTitleStr;
                }
                if (!currentCourse.title.empty())
                    break;
            }
        }
        std::map<std::string, LectureOption> lectureOptionsMap;
        for (const auto &sectionJson : sectionsJson)
        {
            if (sectionJson.value("subtype", "") == "Lecture")
            {
                LectureOption opt;
                opt.lectureId = sectionJson.value("section", "");
                opt.lectureMeetings = parseMeetings(courseCode, sectionJson);
                if (!opt.lectureMeetings.empty())
                    lectureOptionsMap[opt.lectureId] = opt;
            }
        }
        for (const auto &sectionJson : sectionsJson)
        {
            std::string subtype = sectionJson.value("subtype", "");
            if (subtype == "Lab" || subtype == "Tutorial")
            {
                std::string sectionId = sectionJson.value("section", "");
                std::string parentId;
                for (char c : sectionId)
                {
                    if (isdigit(c))
                        parentId += c;
                    else
                        break;
                }
                if (lectureOptionsMap.count(parentId))
                {
                    std::vector<Meeting> meetings = parseMeetings(courseCode, sectionJson);
                    if (!meetings.empty()) {
                        if (subtype == "Lab")
                            lectureOptionsMap[parentId].labs.push_back(meetings);
                        else
                            lectureOptionsMap[parentId].tutorials.push_back(meetings);
                    }
                }
            }
        }
        for (auto const &[id, opt] : lectureOptionsMap)
            currentCourse.options.push_back(opt);
        if (!currentCourse.options.empty())
            courses.push_back(currentCourse);
    }
    std::sort(courses.begin(), courses.end(), [](const Course &a, const Course &b)
              { return a.name < b.name; });
    return courses;
}

inline bool conflict(const Meeting &a, const Meeting &b)
{
    if (a.day != b.day || a.day == 0)
        return false;
    return !(a.end <= b.start || b.end <= a.start);
}

bool meetsInstructorPreference(const std::vector<Meeting> &pack, const Constraints &constraints)
{
    if (pack.empty())
        return true;
    const std::string &courseCode = pack.front().course;
    if (constraints.preferredInstructors.count(courseCode))
    {
        const auto &preferredList = constraints.preferredInstructors.at(courseCode);
        if (preferredList.empty())
            return true;

        for (const auto &m : pack) {
            std::string actualInstructor = m.instructor;
            transform(actualInstructor.begin(), actualInstructor.end(), actualInstructor.begin(), ::toupper);

            for (const auto &pref : preferredList) {
                std::string upperPref = pref;
                transform(upperPref.begin(), upperPref.end(), upperPref.begin(), ::toupper);
                if (actualInstructor.find(upperPref) != std::string::npos)
                    return true;
            }
        }
        return false;
    }
    return true;
}

bool isValid(const std::vector<Meeting> &pack, const Constraints &constraints)
{
    for (const auto &m : pack)
    {
        if (m.day == 0 || m.start < 0)
            continue;

        if (constraints.excludedDays.count(m.day))
            return false;

        if (m.start < constraints.minStartTime)
            return false;

        if (m.end > constraints.maxEndTime)
            return false;

        if (constraints.gapStartTime != -1 && constraints.gapEndTime != -1)
        {
            if (constraints.gapDay == 0 || m.day == constraints.gapDay)
            {
                if (m.start < constraints.gapEndTime && m.end > constraints.gapStartTime)
                    return false;
            }
        }
    }
    return true;
}

double calculateStdDev(const std::vector<int> &v)
{
    if (v.size() < 2)
        return 0.0;
    double sum = std::accumulate(v.begin(), v.end(), 0.0);
    double mean = sum / v.size();
    double sq_sum = std::inner_product(v.begin(), v.end(), v.begin(), 0.0);
    return sqrt(sq_sum / v.size() - mean * mean);
}

double getMetricScore(const ScheduleResult& r, const std::string& metric) {
    if (metric == "few-days") return r.numDays;
    if (metric == "compact") return r.totalGapMinutes;
    if (metric == "balanced-days") return r.maxDailyClasses;
    if (metric == "consistent-times") return r.timeConsistencyScore;
    return 0.0;
}

void calculateScheduleMetrics(ScheduleResult &result, const std::string &opt_metric, const std::string &sec_metric)
{
    std::set<int> days;
    std::map<int, std::vector<Meeting>> meetingsByDay;
    for (const auto &m : result.meetings)
        if (m.day > 0)
        {
            days.insert(m.day);
            meetingsByDay[m.day].push_back(m);
        }
    result.numDays = days.size();
    result.totalGapMinutes = 0;
    for (auto const &[day, meetingsOnDay] : meetingsByDay)
    {
        if (meetingsOnDay.size() > 1)
        {
            int minTime = 24 * 60, maxTime = 0, totalClassTime = 0;
            for (const auto &m : meetingsOnDay)
            {
                minTime = std::min(minTime, m.start);
                maxTime = std::max(maxTime, m.end);
                totalClassTime += (m.end - m.start);
            }
            result.totalGapMinutes += (maxTime - minTime - totalClassTime);
        }
    }
    std::map<int, int> classesPerDay;
    for (const auto &m : result.meetings)
        if (m.day > 0)
            classesPerDay[m.day]++;
    int maxClasses = 0;
    for (const auto &pair : classesPerDay)
        if (pair.second > maxClasses)
            maxClasses = pair.second;
    result.maxDailyClasses = maxClasses;

    std::vector<int> startTimes, endTimes;
    for (const auto &day : days)
    {
        int dayStart = 24 * 60, dayEnd = 0;
        for (const auto &m : meetingsByDay[day])
        {
            dayStart = std::min(dayStart, m.start);
            dayEnd = std::max(dayEnd, m.end);
        }
        startTimes.push_back(dayStart);
        endTimes.push_back(dayEnd);
    }
    result.timeConsistencyScore = calculateStdDev(startTimes) + calculateStdDev(endTimes);

    double primary = getMetricScore(result, opt_metric);
    double secondary = getMetricScore(result, sec_metric);
    result.score = primary + (secondary / 1000000.0);
}

void backtrack(const std::vector<Course> &courses, int idx, std::vector<Meeting> &chosen, const Constraints &constraints, const std::string &opt_metric, const std::string &sec_metric)
{
    if (idx == (int)courses.size())
    {
        ScheduleResult r;
        r.meetings = chosen;
        calculateScheduleMetrics(r, opt_metric, sec_metric);
        outputSchedule(r);
        return;
    }
    const Course &course = courses[idx];
    const std::set<std::string> *specificSectionsForCourse = constraints.specificSections.count(course.name) ? &constraints.specificSections.at(course.name) : nullptr;
    for (const auto &opt : course.options)
    {
        if (constraints.filterZeroSeats)
        {
            bool is_full = false;
            for (const auto &lm : opt.lectureMeetings)
                if (lm.seats == 0)
                {
                    is_full = true;
                    break;
                }
            if (is_full)
                continue;
        }
        if (specificSectionsForCourse && any_of(specificSectionsForCourse->begin(), specificSectionsForCourse->end(), [](const std::string &s)
                                                { return !s.empty() && (isdigit(s[0])); }))
        {
            if (specificSectionsForCourse->find(opt.lectureId) == specificSectionsForCourse->end())
                continue;
        }

        std::vector<std::vector<Meeting>> availableLabs = opt.labs;
        if (specificSectionsForCourse)
        {
            availableLabs.erase(remove_if(availableLabs.begin(), availableLabs.end(), [&](const std::vector<Meeting> &ms)
                                          {
                                              if(ms.empty()) return false;
                                              return any_of(specificSectionsForCourse->begin(), specificSectionsForCourse->end(), [](const std::string &s)
                                                          { return !s.empty() && toupper(s[0]) == 'L'; }) &&
                                                   specificSectionsForCourse->find(ms.front().id) == specificSectionsForCourse->end();
                                          }),
                                availableLabs.end());
        }
        std::vector<std::vector<Meeting>> availableTutorials = opt.tutorials;
        if (specificSectionsForCourse)
        {
            availableTutorials.erase(remove_if(availableTutorials.begin(), availableTutorials.end(), [&](const std::vector<Meeting> &ms)
                                               {
                                                   if(ms.empty()) return false;
                                                   return any_of(specificSectionsForCourse->begin(), specificSectionsForCourse->end(), [](const std::string &s)
                                                               { return !s.empty() && toupper(s[0]) == 'T'; }) &&
                                                        specificSectionsForCourse->find(ms.front().id) == specificSectionsForCourse->end();
                                               }),
                                     availableTutorials.end());
        }
        int labsN = std::max(1, (int)availableLabs.size());
        int tutsN = std::max(1, (int)availableTutorials.size());
        for (int li = 0; li < labsN; ++li)
        {
            for (int ti = 0; ti < tutsN; ++ti)
            {
                std::vector<Meeting> pack;
                pack.insert(pack.end(), opt.lectureMeetings.begin(), opt.lectureMeetings.end());
                if (!availableLabs.empty())
                    pack.insert(pack.end(), availableLabs[li].begin(), availableLabs[li].end());
                if (!availableTutorials.empty())
                    pack.insert(pack.end(), availableTutorials[ti].begin(), availableTutorials[ti].end());

                if (!meetsInstructorPreference(pack, constraints))
                    continue;

                if (!isValid(pack, constraints))
                    continue;

                bool has_conflict = false;
                for (size_t i = 0; i < pack.size(); ++i)
                {
                    for (size_t j = i + 1; j < pack.size(); ++j)
                    {
                        if (conflict(pack[i], pack[j]))
                        {
                            has_conflict = true;
                            break;
                        }
                    }
                    if (has_conflict)
                        break;
                    for (const auto &mOld : chosen)
                    {
                        if (conflict(pack[i], mOld))
                        {
                            has_conflict = true;
                            break;
                        }
                    }
                    if (has_conflict)
                        break;
                }
                if (has_conflict)
                    continue;
                chosen.insert(chosen.end(), pack.begin(), pack.end());
                backtrack(courses, idx + 1, chosen, constraints, opt_metric, sec_metric);
                chosen.resize(chosen.size() - pack.size());
            }
        }
    }
}

int main(int argc, char* argv[]) {
    std::ios_base::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::string json_file;
    std::set<std::string> selected_course_names;
    Constraints constraints;
    std::string opt_metric = "compact";
    std::string sec_metric = "none";

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--json-file" && i + 1 < argc) {
            json_file = argv[++i];
        } else if (arg == "--courses" && i + 1 < argc) {
            std::string courses_str = argv[++i];
            std::stringstream ss(courses_str);
            std::string course;
            while (std::getline(ss, course, ',')) {
                selected_course_names.insert(course);
            }
        } else if (arg == "--exclude-days" && i + 1 < argc) {
            std::string days_str = argv[++i];
            std::stringstream ss(days_str);
            std::string day;
            while (std::getline(ss, day, ',')) {
                try {
                    constraints.excludedDays.insert(std::stoi(day));
                } catch(...) {}
            }
        } else if (arg == "--start-time" && i + 1 < argc) {
            constraints.minStartTime = parseTime(argv[++i]);
        } else if (arg == "--end-time" && i + 1 < argc) {
            constraints.maxEndTime = parseTime(argv[++i]);
        } else if (arg == "--gap-start" && i + 1 < argc) {
            constraints.gapStartTime = parseTime(argv[++i]);
        } else if (arg == "--gap-end" && i + 1 < argc) {
            constraints.gapEndTime = parseTime(argv[++i]);
        } else if (arg == "--gap-day" && i + 1 < argc) {
            constraints.gapDay = std::stoi(argv[++i]);
        } else if (arg == "--exclude-full" && i + 1 < argc) {
            std::string val = argv[++i];
            constraints.filterZeroSeats = (val == "true");
        } else if (arg == "--optimize-by" && i + 1 < argc) {
            opt_metric = argv[++i];
        } else if (arg == "--secondary-optimize-by" && i + 1 < argc) {
            sec_metric = argv[++i];
        } else if (arg == "--preferred-instructors" && i + 1 < argc) {
            std::string insts_str = argv[++i];
            std::stringstream ss(insts_str);
            std::string pair;
            while (std::getline(ss, pair, '|')) {
                size_t colon_pos = pair.find(':');
                if (colon_pos != std::string::npos) {
                    std::string course = pair.substr(0, colon_pos);
                    std::string inst = pair.substr(colon_pos + 1);
                    constraints.preferredInstructors[course].push_back(inst);
                }
            }
        } else if (arg == "--specific-sections" && i + 1 < argc) {
            std::string secs_str = argv[++i];
            std::stringstream ss(secs_str);
            std::string pair;
            while (std::getline(ss, pair, '|')) {
                size_t colon_pos = pair.find(':');
                if (colon_pos != std::string::npos) {
                    std::string course = pair.substr(0, colon_pos);
                    std::string sec = pair.substr(colon_pos + 1);
                    constraints.specificSections[course].insert(sec);
                }
            }
        }
    }

    if (json_file.empty() || selected_course_names.empty()) {
        std::cerr << "Usage: " << argv[0] << " --json-file <path> --courses <course1,course2,...> [options]" << std::endl;
        return 1;
    }

    try {
        std::vector<Course> all_courses = loadCoursesFromJson(json_file);
        std::vector<Course> courses_to_schedule;
        for (const auto &c : all_courses) {
            if (selected_course_names.count(c.name)) {
                courses_to_schedule.push_back(c);
            }
        }

        std::vector<Meeting> chosen;
        backtrack(courses_to_schedule, 0, chosen, constraints, opt_metric, sec_metric);
        std::cout.flush();

    } catch (const std::exception &e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
