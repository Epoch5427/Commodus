# scheduler_runner.py

from dataclasses import dataclass, field
import os
import shutil
import subprocess
import time
from typing import List, Optional, Tuple
from gi.repository import GLib, GObject

LIVE_SORT_THRESHOLD = 50000


@dataclass
class SchedulerOptions:
    json_file: str
    courses: List[str]
    preferred_instructors: List[str] = field(default_factory=list)  # ["MATH101:Dr. Smith", ...]
    specific_sections: List[str] = field(default_factory=list)      # ["MATH101:Lecture:01", ...]
    excluded_days: List[int] = field(default_factory=list)          # [1, 2, ...]
    start_time: Optional[str] = None                                # "08:30"
    end_time: Optional[str] = None                                  # "17:30"
    gap_start: Optional[str] = None                                 # "12:00"
    gap_end: Optional[str] = None                                   # "13:00"
    gap_day: Optional[int] = None                                   # 0 (all) or 1-7
    exclude_full_courses: List[str] = field(default_factory=list)   # ["MATH101", ...]
    optimize_by: str = "compact"
    secondary_optimize_by: Optional[str] = None


class SchedulerRunner(GObject.Object):
    __gtype_name__ = 'CommodusSchedulerRunner'

    __gsignals__ = {
        # count: int, is_live_sorting: bool, top_changed: bool
        'progress': (GObject.SignalFlags.RUN_FIRST, None, (int, bool, bool)),
        # ret_code: int, stderr: str, schedules: object, is_cancelled: bool
        'completed': (GObject.SignalFlags.RUN_FIRST, None, (int, str, object, bool)),
    }

    def __init__(self):
        super().__init__()
        self._process: Optional[subprocess.Popen] = None
        self._is_cancelled = False
        self.schedules: List[Tuple[float, str]] = []

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def is_cancelled(self) -> bool:
        return self._is_cancelled

    @staticmethod
    def find_binary() -> Optional[str]:
        """Locates the scheduler executable in system PATH or local build directories."""
        binary_path = shutil.which('scheduler')
        if binary_path:
            return binary_path

        # Fallback to local Flatpak/meson project directory structure
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        exe_name = 'scheduler.exe' if os.name == 'nt' else 'scheduler'
        candidate = os.path.join(project_root, 'build', 'c++', exe_name)
        if os.path.exists(candidate):
            return candidate

        return None

    @classmethod
    def build_command(cls, binary_path: str, options: SchedulerOptions) -> List[str]:
        """Constructs the CLI argument list from high-level options."""
        cmd = [
            binary_path,
            '--json-file', options.json_file,
            '--courses', ",".join(options.courses)
        ]

        if options.preferred_instructors:
            cmd.extend(['--preferred-instructors', "|".join(options.preferred_instructors)])

        if options.specific_sections:
            cmd.extend(['--specific-sections', "|".join(options.specific_sections)])

        if options.excluded_days:
            cmd.extend(['--exclude-days', ",".join(str(d) for d in options.excluded_days)])

        if options.start_time and options.end_time:
            cmd.extend(['--start-time', options.start_time, '--end-time', options.end_time])

        if options.gap_start and options.gap_end:
            cmd.extend(['--gap-start', options.gap_start, '--gap-end', options.gap_end])
            if options.gap_day is not None:
                cmd.extend(['--gap-day', str(options.gap_day)])

        if options.exclude_full_courses:
            cmd.extend(['--exclude-full', ",".join(options.exclude_full_courses)])

        cmd.extend(['--optimize-by', options.optimize_by])

        if options.secondary_optimize_by and options.secondary_optimize_by != "none":
            cmd.extend(['--secondary-optimize-by', options.secondary_optimize_by])

        return cmd

    def cancel(self):
        """Signals the process to terminate."""
        self._is_cancelled = True
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass

    def start(self, cmd: List[str]):
        """Runs the external scheduler process on a background thread."""
        import threading
        self.cancel()  # Terminate any previously running job
        self._is_cancelled = False
        self.schedules = []
        threading.Thread(target=self._worker, args=(cmd,), daemon=True).start()

    def _worker(self, cmd: List[str]):
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1024 * 1024,
            **kwargs
        )

        all_schedules: List[Tuple[float, str]] = []
        self.schedules = all_schedules
        last_ui_update = time.time()
        has_shown_first = False

        for line in self._process.stdout:
            line = line.strip()
            # If the process terminates mid-generation, ignore abruptly truncated JSON lists
            if not line or not line.endswith(']'):
                continue
            try:
                if '\t' in line:
                    score_str, raw_data = line.split('\t', 1)
                    all_schedules.append((float(score_str), raw_data))
                else:
                    all_schedules.append((0.0, line))
            except Exception:
                continue

            now = time.time()
            if now - last_ui_update > 0.12:
                count = len(all_schedules)
                is_live_sorting = count <= LIVE_SORT_THRESHOLD
                top_changed = False

                if is_live_sorting and count > 0:
                    old_top = all_schedules[0] if has_shown_first else None
                    all_schedules.sort(key=lambda s: s[0])
                    if not has_shown_first or all_schedules[0] != old_top:
                        top_changed = True
                        has_shown_first = True
                elif not has_shown_first and count > 0:
                    top_changed = True
                    has_shown_first = True

                GLib.idle_add(self.emit, 'progress', count, is_live_sorting, top_changed)
                last_ui_update = now

        self._process.wait()
        ret_code = self._process.returncode
        stderr = self._process.stderr.read()

        all_schedules.sort(key=lambda s: s[0])
        self._process = None

        GLib.idle_add(self.emit, 'completed', ret_code, stderr, all_schedules, self._is_cancelled)
