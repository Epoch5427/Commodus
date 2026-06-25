<p align="center">
  <img src="data/icons/hicolor/scalable/apps/io.github.Epoch5427.Commodus.svg" width="128" height="128" alt="Commodus Icon">
</p>

<h1 align="center">Commodus</h1>

<p align="center">
  <strong>Generate conflict-free university schedules</strong>
</p>

# Commodus

An elegant, modern university schedule generator and optimizer built for **Nile University**, powered by **GTK4/Libadwaita** and a blazing-fast **C++ backtracking solver** [1].

Commodus helps you take control of your academic calendar. Instead of spending hours manually juggling sections, classes, and instructors, Commodus automatically generates every possible conflict-free schedule combination based on your unique constraints.

---

## Features

*   **Blazing-Fast Solver:** Powered by a customized backtrack-matching algorithm written in C++ [1] to find and evaluate hundreds of valid timetables in milliseconds.
*   **Intuitive Libadwaita Interface:** Built natively using GNOME's flagship UI toolkit, supporting seamless adaptive light/dark modes and responsive window layouts.
*   **Smart Timeline Grid:** A high-density timeline that scales dynamically. Shorter classes automatically hide lesser-needed labels to prevent overlap, and full details remain readily accessible via hovering tooltips.
*   **Compare & Reschedule:** A granular overlay tool that lets you selectively lock down specific sections, swap open courses, and regenerate schedules around your fixed choices.
*   **Granular Filters:**
    *   Exclude specific days of the week.
    *   Filter out closed/full classes (0 seats remaining).
    *   Restrict timetables to strict daily start and end times.
    *   Filter courses directly by specific Lecture/Lab/Tutorial sections or preferred instructors.
*   **Auto-Update Database:** Automatically downloads the latest remote course offerings from GitHub on startup using background threads so your scheduling data is never stale.
*   **Persistent Offline State:** Saves all your selections, filters, and window states offline, so you can pick up exactly where you left off.
*   **Easy Sharing:** Export your active schedule directly to the system clipboard in clean, plain-text columns for quick sharing with friends.

---

## Screenshots

| Schedule View | Constraints & Filters |
| :---: | :---: |
| <img width="1225" height="1041" alt="Screenshot From 2026-06-26 02-27-35" src="https://github.com/user-attachments/assets/ee305416-858a-444f-8a72-337be3f5bc88" /> | <img width="770" height="590" alt="Screenshot From 2026-06-26 02-27-52" src="https://github.com/user-attachments/assets/a34d1051-1717-499a-a695-3a8a391e1836" /> |

---

## Architecture

Commodus is designed as a hybrid application leveraging the strengths of both Python and compiled C++:
*   **Frontend:** Python 3 utilizing `PyGObject` for native GTK4/Libadwaita desktop controls and system state management.
*   **Backend:** A robust, standalone C++ executable (`scheduler`) that receives layout parameters via command-line arguments and returns output as flat JSON payloads [1] for instant UI rendering.

---

## Installation & Running

### Requirements
*   Python 3.10+
*   GTK4 & Libadwaita
*   `PyGObject` (Python bindings for GTK)
*   A C++17 compliant compiler (for building the backend solver)
*   [nlohmann/json](https://github.com/nlohmann/json) (Header-only library included in backend compilation)

### Building the Solver
Compile the backend scheduling binary first:
```bash
g++ -std=c++17 -O3 build/c++/scheduler.cpp -o build/c++/scheduler
```

## Importing & Sharing Schedules

Commodus makes collaborating on class registration incredibly easy:

    To Share: Navigate to your desired schedule and click Copy Schedule Text in the sidebar. This copies a cleanly aligned layout to your clipboard.

    To Import: Click the Import Schedule button in the sidebar and paste a friend's exported schedule. Commodus will instantly parse the classes, update your selections, and regenerate the possibilities for you.

## License

This project is licensed under the GPL-3.0 License. See the LICENSE file for more details.
