import json
import os
import tempfile
import threading
import time
import urllib.request
from typing import Optional, Tuple
from gi.repository import GLib, GObject

DB_RAW_BASE = "https://raw.githubusercontent.com/Epoch5427/Commodus"
DB_URL = f"{DB_RAW_BASE}/app-data/NU_course_data.json"
SPEC_URL = f"{DB_RAW_BASE}/app-data/curriculum_spec.json"
RUNS_URL = "https://api.github.com/repos/Epoch5427/Commodus/actions/workflows/fetch_courses.yml/runs?per_page=1"
BRANCH_COMMIT_URL = "https://api.github.com/repos/Epoch5427/Commodus/commits/app-data"
PROXY_URL = "https://commodus-updater.omarnad141076.workers.dev"


class DatabaseService(GObject.Object):
    __gtype_name__ = 'CommodusDatabaseService'

    __gsignals__ = {
        'cached-loaded': (GObject.SignalFlags.RUN_FIRST, None, (object, object, str)),
        'fetch-started': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'fetch-completed': (GObject.SignalFlags.RUN_FIRST, None, (object, object, str)),
        'fetch-failed': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'update-progress': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'update-completed': (GObject.SignalFlags.RUN_FIRST, None, (bool, str)),
        'local-loaded': (GObject.SignalFlags.RUN_FIRST, None, (object, str)),
    }

    def __init__(self):
        super().__init__()
        self.cache_dir = os.path.join(GLib.get_user_cache_dir(), "commodus")
        os.makedirs(self.cache_dir, exist_ok=True)

        self.local_db_path = os.path.join(self.cache_dir, "database.json")
        self.local_spec_path = os.path.join(self.cache_dir, "curriculum_spec.json")

    @staticmethod
    def _get_ssl_context():
        if os.name == 'nt':
            import ssl
            return ssl._create_unverified_context()
        return None

    def _atomic_write(self, target_path: str, content: str):
        """Atomically writes content to prevent corrupted reads by concurrent processes."""
        dir_name = os.path.dirname(target_path)
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            tf.write(content)
            temp_name = tf.name
        os.replace(temp_name, target_path)

    def load_cached_async(self):
        def load_task():
            db_data = None
            spec_data = None

            if os.path.exists(self.local_db_path):
                try:
                    with open(self.local_db_path, 'r', encoding='utf-8') as f:
                        db_data = json.load(f)
                except Exception as e:
                    print(f"Error loading cached database: {e}")

            if os.path.exists(self.local_spec_path):
                try:
                    with open(self.local_spec_path, 'r', encoding='utf-8') as f:
                        spec_data = json.load(f)
                except Exception as e:
                    print(f"Error loading cached curriculum specs: {e}")

            GLib.idle_add(self.emit, 'cached-loaded', db_data, spec_data, self.local_db_path)

        threading.Thread(target=load_task, daemon=True).start()

    def fetch_database_async(self, force_refresh: bool = False, commit_sha: Optional[str] = None):
        """Downloads fresh database. If commit_sha is provided, downloads via immutable SHA to bypass CDN."""
        self.emit('fetch-started')

        def fetch_task():
            context = self._get_ssl_context()
            sha = commit_sha

            # If force refresh requested and no SHA provided, resolve latest commit SHA of app-data
            if force_refresh and not sha:
                try:
                    req_branch = urllib.request.Request(BRANCH_COMMIT_URL, headers={'User-Agent': 'Commodus-App'})
                    with urllib.request.urlopen(req_branch, context=context, timeout=8) as resp:
                        sha_data = json.loads(resp.read().decode('utf-8'))
                        sha = sha_data.get('sha')
                except Exception as e:
                    print(f"Failed to resolve latest commit SHA, falling back: {e}")

            if sha:
                db_url = f"{DB_RAW_BASE}/{sha}/NU_course_data.json"
                spec_url = f"{DB_RAW_BASE}/{sha}/curriculum_spec.json"
            else:
                db_url = DB_URL
                spec_url = SPEC_URL

            parsed_db = None
            parsed_spec = None

            # 1. Fetch Course Database
            try:
                req_db = urllib.request.Request(db_url, headers={'User-Agent': 'Commodus-App'})
                with urllib.request.urlopen(req_db, context=context, timeout=12) as response:
                    db_content = response.read().decode('utf-8')
                parsed_db = json.loads(db_content)
                self._atomic_write(self.local_db_path, db_content)
            except Exception as e:
                print(f"Database fetch warning: {e}")

            # 2. Fetch Curriculum Spec
            try:
                req_spec = urllib.request.Request(spec_url, headers={'User-Agent': 'Commodus-App'})
                with urllib.request.urlopen(req_spec, context=context, timeout=12) as response:
                    spec_content = response.read().decode('utf-8')
                parsed_spec = json.loads(spec_content)
                self._atomic_write(self.local_spec_path, spec_content)
            except Exception as e:
                print(f"Curriculum spec fetch warning: {e}")

            if parsed_db is not None:
                GLib.idle_add(self.emit, 'fetch-completed', parsed_db, parsed_spec, self.local_db_path)
            else:
                GLib.idle_add(self.emit, 'fetch-failed', "Could not download course database")

        threading.Thread(target=fetch_task, daemon=True).start()

    def trigger_remote_update(self):
        """Triggers the Cloudflare Worker proxy and polls GitHub Actions until complete."""
        def update_flow():
            context = self._get_ssl_context()
            start_time = time.time()

            # 1. Fetch current latest workflow run ID
            old_run_id = None
            try:
                req = urllib.request.Request(RUNS_URL, headers={"User-Agent": "Commodus-App"})
                with urllib.request.urlopen(req, context=context, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data.get("workflow_runs"):
                        old_run_id = data["workflow_runs"][0]["id"]
            except Exception as e:
                print(f"Could not determine prior run ID: {e}")

            # 2. Trigger Cloudflare Worker Proxy
            try:
                trigger_req = urllib.request.Request(PROXY_URL, method="POST", headers={"User-Agent": "Commodus-App"})
                with urllib.request.urlopen(trigger_req, context=context, timeout=10) as resp:
                    if resp.status not in (200, 204):
                        raise Exception(f"Proxy returned status {resp.status}")
            except Exception as e:
                GLib.idle_add(self.emit, 'update-completed', False, f"Could not trigger remote update: {e}")
                return

            GLib.idle_add(self.emit, 'update-progress', "Update job started! Waiting for GitHub to compile... (1-2 mins)")

            # 3. Poll GitHub API (timeout after 5 mins)
            new_run_completed = False
            conclusion = None
            timeout_counter = 0

            # Wait a brief moment for GitHub Actions to register the new run
            time.sleep(6)

            while not new_run_completed and timeout_counter < 60:
                time.sleep(5)
                timeout_counter += 1
                try:
                    req = urllib.request.Request(RUNS_URL, headers={"User-Agent": "Commodus-App"})
                    with urllib.request.urlopen(req, context=context, timeout=10) as resp:
                        data = json.loads(resp.read().decode('utf-8'))
                        if data.get("workflow_runs"):
                            latest_run = data["workflow_runs"][0]
                            run_id = latest_run["id"]
                            status = latest_run["status"]

                            # Ensure this run is actually newer than our trigger
                            is_new_run = (old_run_id is not None and run_id != old_run_id) or (old_run_id is None)
                            if is_new_run and status == "completed":
                                new_run_completed = True
                                conclusion = latest_run["conclusion"]
                except Exception:
                    pass

            # 4. Notify completion and download via fresh commit
            if new_run_completed:
                if conclusion == "success":
                    GLib.idle_add(self.emit, 'update-completed', True, "Workflow finished! Downloading fresh database...")
                    # Give GitHub storage 2 seconds to ensure ref replication, then fetch
                    time.sleep(2)
                    GLib.idle_add(self.fetch_database_async, True, None)
                else:
                    GLib.idle_add(self.emit, 'update-completed', False, f"GitHub workflow failed with status: {conclusion}")
            else:
                GLib.idle_add(self.emit, 'update-completed', False, "Timed out waiting for GitHub workflow to finish.")

        threading.Thread(target=update_flow, daemon=True).start()

    def load_local_file_async(self, file_path: str):
        def load_task():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                GLib.idle_add(self.emit, 'local-loaded', data, file_path)
            except Exception as e:
                GLib.idle_add(self.emit, 'fetch-failed', f"Error loading local database: {e}")

        threading.Thread(target=load_task, daemon=True).start()

