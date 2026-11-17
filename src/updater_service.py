import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from typing import Dict, Optional, Tuple
from gi.repository import GLib, GObject

from .version import APP_VERSION

REPO = "Epoch5427/Commodus"
RELEASES_LATEST_WEB = f"https://github.com/{REPO}/releases/latest"
RELEASES_LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
MANIFEST_URL = f"https://github.com/{REPO}/releases/latest/download/latest.json"


def _parse_version(v: str) -> Tuple[int, ...]:
    cleaned = v.strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    parts = []
    for part in cleaned.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_newer_version(remote: str, current: str) -> bool:
    r = list(_parse_version(remote))
    c = list(_parse_version(current))
    n = max(len(r), len(c))
    r.extend([0] * (n - len(r)))
    c.extend([0] * (n - len(c)))
    return tuple(r) > tuple(c)


def _has_py7zr() -> bool:
    try:
        import py7zr  # noqa: F401
        return True
    except ImportError:
        return False


class WindowsUpdaterService(GObject.Object):
    __gtype_name__ = "CommodusWindowsUpdaterService"

    __gsignals__ = {
        # info dict: {version, url, sha256, notes, release_url, can_auto_update}
        "update-available": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "up-to-date": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "check-failed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # fraction (0.0..1.0 or -1 for indeterminate), status text
        "download-progress": (GObject.SignalFlags.RUN_FIRST, None, (float, str)),
        # staged_ok, error_message
        "ready-to-apply": (GObject.SignalFlags.RUN_FIRST, None, (bool, str)),
    }

    def __init__(self):
        super().__init__()
        self._cancel_event = threading.Event()
        self._prepared_payload_dir: Optional[str] = None
        self._prepared_staging_root: Optional[str] = None

    @staticmethod
    def is_supported_platform() -> bool:
        # Only run in-place binary replacement on frozen Windows builds
        return os.name == "nt" and getattr(sys, "frozen", False)

    @staticmethod
    def get_app_dir() -> str:
        return os.path.dirname(os.path.abspath(sys.executable))

    @classmethod
    def is_app_dir_writable(cls) -> bool:
        app_dir = cls.get_app_dir()
        probe = os.path.join(app_dir, f".commodus_write_test_{os.getpid()}")
        try:
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return True
        except OSError:
            return False

    @classmethod
    def cleanup_leftover_staging(cls):
        """Removes leftover _update_staging (and _update_backup if exe is healthy)."""
        if not cls.is_supported_platform():
            return
        app_dir = cls.get_app_dir()
        for folder in ("_update_staging", "_update_backup"):
            path = os.path.join(app_dir, folder)
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _get_verified_ssl_context() -> ssl.SSLContext:
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            return ssl.create_default_context()

    def check_for_updates_async(self, manual: bool = False):
        def task():
            ctx = self._get_verified_ssl_context()
            try:
                info = self._fetch_update_info(ctx)
                if info and is_newer_version(info["version"], APP_VERSION):
                    GLib.idle_add(self.emit, "update-available", info)
                elif manual:
                    GLib.idle_add(self.emit, "up-to-date")
            except Exception as e:
                if manual:
                    GLib.idle_add(self.emit, "check-failed", str(e))

        threading.Thread(target=task, daemon=True).start()

    def _fetch_release_notes(self, ctx: ssl.SSLContext, version: str) -> str:
        urls = [
            f"https://api.github.com/repos/{REPO}/releases/tags/v{version}",
            RELEASES_LATEST_API,
        ]
        for api_url in urls:
            try:
                req = urllib.request.Request(api_url, headers={"User-Agent": "Commodus-App"})
                with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
                    rel = json.loads(resp.read().decode("utf-8"))
                    body = (rel.get("body") or "").replace("\r\n", "\n").strip()
                    if body:
                        return body
            except Exception:
                continue
        return ""

    def _fetch_update_info(self, ctx: ssl.SSLContext) -> Optional[Dict]:
        # 1. Prefer CDN-served latest.json attached to the release (no API rate limit)
        try:
            req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "Commodus-App"})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ver = str(data.get("version", "")).strip().lstrip("vV")
                url = str(data.get("url", "")).strip()
                if ver and url:
                    manifest_notes = (data.get("notes") or "").replace("\r\n", "\n").strip()
                    notes = manifest_notes
                    if is_newer_version(ver, APP_VERSION):
                        # Prefer live GitHub Release body (reflects UI edits), fallback to manifest notes
                        notes = self._fetch_release_notes(ctx, ver) or manifest_notes
                    return self._enrich_update_info({
                        "version": ver,
                        "url": url,
                        "sha256": str(data.get("sha256", "")).strip().lower(),
                        "notes": notes,
                        "release_url": data.get("release_url") or RELEASES_LATEST_WEB,
                    })
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        except Exception:
            pass

        # 2. Fallback: zero-rate-limit redirect check before hitting api.github.com
        head_req = urllib.request.Request(RELEASES_LATEST_WEB, method="HEAD", headers={"User-Agent": "Commodus-App"})
        with urllib.request.urlopen(head_req, context=ctx, timeout=10) as resp:
            final_url = resp.geturl()
        if "/releases/tag/" not in final_url:
            return None
        latest_tag = final_url.rsplit("/releases/tag/", 1)[-1]
        if not is_newer_version(latest_tag, APP_VERSION):
            return None

        # Only hit api.github.com when an actual update exists
        api_req = urllib.request.Request(RELEASES_LATEST_API, headers={"User-Agent": "Commodus-App"})
        with urllib.request.urlopen(api_req, context=ctx, timeout=12) as resp:
            rel = json.loads(resp.read().decode("utf-8"))

        assets = rel.get("assets", [])
        chosen = None
        for ext in (".zip", ".7z"):
            for asset in assets:
                name = asset.get("name", "").lower()
                if name.endswith(ext) and ("win" in name or "commodus" in name):
                    chosen = asset
                    break
            if chosen:
                break

        sha = ""
        if chosen and isinstance(chosen.get("digest"), str) and chosen["digest"].startswith("sha256:"):
            sha = chosen["digest"].split(":", 1)[1].strip().lower()

        return self._enrich_update_info({
            "version": rel.get("tag_name", latest_tag).lstrip("vV"),
            "url": chosen.get("browser_download_url", "") if chosen else "",
            "sha256": sha,
            "notes": (rel.get("body") or "").replace("\r\n", "\n").strip(),
            "release_url": rel.get("html_url", RELEASES_LATEST_WEB),
        })

    def _enrich_update_info(self, info: Dict) -> Dict:
        url_lower = info.get("url", "").lower()
        extractable = url_lower.endswith(".zip") or (url_lower.endswith(".7z") and _has_py7zr())
        info["can_auto_update"] = (
            self.is_supported_platform()
            and self.is_app_dir_writable()
            and bool(info.get("url"))
            and extractable
        )
        return info

    def cancel_download(self):
        self._cancel_event.set()

    def download_and_stage_async(self, info: Dict):
        self._cancel_event.clear()
        self._prepared_payload_dir = None
        self._prepared_staging_root = None

        def task():
            app_dir = self.get_app_dir()
            staging_root = os.path.join(app_dir, "_update_staging")
            shutil.rmtree(staging_root, ignore_errors=True)
            os.makedirs(staging_root, exist_ok=True)

            url = info["url"]
            ext = ".7z" if url.lower().endswith(".7z") else ".zip"
            archive_path = os.path.join(staging_root, f"update{ext}")
            extract_dir = os.path.join(staging_root, "extracted")
            os.makedirs(extract_dir, exist_ok=True)

            try:
                ctx = self._get_verified_ssl_context()
                req = urllib.request.Request(url, headers={"User-Agent": "Commodus-App"})
                hasher = hashlib.sha256()

                with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                    total = int(resp.headers.get("Content-Length") or 0)
                    downloaded = 0
                    chunk_size = 65536
                    with open(archive_path, "wb") as out:
                        while True:
                            if self._cancel_event.is_set():
                                raise InterruptedError("Update cancelled.")
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            out.write(chunk)
                            hasher.update(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                frac = min(downloaded / total, 1.0)
                                mb_done = downloaded / (1024 * 1024)
                                mb_tot = total / (1024 * 1024)
                                GLib.idle_add(
                                    self.emit,
                                    "download-progress",
                                    frac,
                                    f"Downloading… {mb_done:.1f} / {mb_tot:.1f} MB",
                                )
                            else:
                                GLib.idle_add(self.emit, "download-progress", -1.0, "Downloading update…")

                expected_sha = info.get("sha256", "")
                if expected_sha:
                    GLib.idle_add(self.emit, "download-progress", -1.0, "Verifying SHA-256 checksum…")
                    actual_sha = hasher.hexdigest().lower()
                    if actual_sha != expected_sha:
                        raise ValueError("Downloaded archive failed SHA-256 verification.")

                GLib.idle_add(self.emit, "download-progress", -1.0, "Extracting update…")
                self._extract_archive(archive_path, extract_dir)
                try:
                    os.remove(archive_path)
                except OSError:
                    pass

                exe_name = os.path.basename(sys.executable)
                payload_dir = self._find_payload_root(extract_dir, exe_name)
                if not payload_dir:
                    raise ValueError(f"Archive did not contain expected {exe_name} and _internal folder.")

                self._prepared_payload_dir = payload_dir
                self._prepared_staging_root = staging_root
                GLib.idle_add(self.emit, "ready-to-apply", True, "")
            except Exception as e:
                shutil.rmtree(staging_root, ignore_errors=True)
                GLib.idle_add(self.emit, "ready-to-apply", False, str(e))

        threading.Thread(target=task, daemon=True).start()

    @staticmethod
    def _validate_member_paths(dest_abs: str, names):
        for name in names:
            target = os.path.realpath(os.path.join(dest_abs, name))
            if os.path.commonpath([dest_abs, target]) != dest_abs:
                raise ValueError(f"Unsafe archive path: {name}")

    def _extract_archive(self, archive_path: str, dest_dir: str):
        dest_abs = os.path.realpath(dest_dir)
        if archive_path.lower().endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                self._validate_member_paths(dest_abs, zf.namelist())
                zf.extractall(dest_abs)
        else:
            import py7zr
            with py7zr.SevenZipFile(archive_path, mode="r") as zf:
                self._validate_member_paths(dest_abs, zf.getnames())
                zf.extractall(path=dest_abs)

    @staticmethod
    def _find_payload_root(extract_dir: str, exe_name: str) -> Optional[str]:
        if (
            os.path.isfile(os.path.join(extract_dir, exe_name))
            and os.path.isdir(os.path.join(extract_dir, "_internal"))
        ):
            return extract_dir
        for entry in os.scandir(extract_dir):
            if entry.is_dir():
                if (
                    os.path.isfile(os.path.join(entry.path, exe_name))
                    and os.path.isdir(os.path.join(entry.path, "_internal"))
                ):
                    return entry.path
        return None

    def launch_swapper_and_prepare_exit(self):
        """Spawns a detached PowerShell swapper in %TEMP%."""
        if not self._prepared_payload_dir or not self._prepared_staging_root:
            raise RuntimeError("No staged update ready to apply.")

        app_dir = self.get_app_dir()
        exe_name = os.path.basename(sys.executable)
        log_path = os.path.join(GLib.get_user_cache_dir(), "commodus", "update_error.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        ps_script = r'''param(
    [Parameter(Mandatory=$true)][int]$TargetPid,
    [Parameter(Mandatory=$true)][string]$AppDir,
    [Parameter(Mandatory=$true)][string]$PayloadDir,
    [Parameter(Mandatory=$true)][string]$StagingRoot,
    [Parameter(Mandatory=$true)][string]$ExeName,
    [Parameter(Mandatory=$true)][string]$LogPath
)

$ErrorActionPreference = "Stop"

try {
    $proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if ($proc) { $proc.WaitForExit(30000) | Out-Null }
} catch {}
Start-Sleep -Milliseconds 600

$BackupDir = Join-Path $AppDir "_update_backup"
if (Test-Path -LiteralPath $BackupDir) {
    Remove-Item -LiteralPath $BackupDir -Recurse -Force
}
New-Item -ItemType Directory -Path $BackupDir | Out-Null

$MovedBackups = @()
$MovedNew = @()

try {
    $PayloadItems = Get-ChildItem -LiteralPath $PayloadDir -Force
    $NamesToReplace = @($PayloadItems | ForEach-Object { $_.Name })
    if ($NamesToReplace -notcontains $ExeName) { $NamesToReplace += $ExeName }
    if ($NamesToReplace -notcontains "_internal") { $NamesToReplace += "_internal" }

    foreach ($name in ($NamesToReplace | Select-Object -Unique)) {
        $oldPath = Join-Path $AppDir $name
        if (Test-Path -LiteralPath $oldPath) {
            $bakPath = Join-Path $BackupDir $name
            $moved = $false
            for ($i = 0; $i -lt 15; $i++) {
                try {
                    Move-Item -LiteralPath $oldPath -Destination $bakPath -Force
                    $moved = $true
                    break
                } catch {
                    Start-Sleep -Milliseconds 400
                }
            }
            if (-not $moved) { throw "Timed out waiting for lock release on $name" }
            $MovedBackups += $name
        }
    }

    foreach ($item in $PayloadItems) {
        $destPath = Join-Path $AppDir $item.Name
        Move-Item -LiteralPath $item.FullName -Destination $destPath -Force
        $MovedNew += $item.Name
    }

    Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force -ErrorAction SilentlyContinue
} catch {
    $_.Exception.Message | Out-File -LiteralPath $LogPath -Encoding utf8
    foreach ($name in $MovedNew) {
        $p = Join-Path $AppDir $name
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    foreach ($name in $MovedBackups) {
        $bakPath = Join-Path $BackupDir $name
        $origPath = Join-Path $AppDir $name
        if ((Test-Path -LiteralPath $bakPath) -and -not (Test-Path -LiteralPath $origPath)) {
            Move-Item -LiteralPath $bakPath -Destination $origPath -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

$NewExe = Join-Path $AppDir $ExeName
if (Test-Path -LiteralPath $NewExe) {
    Start-Process -FilePath $NewExe -WorkingDirectory $AppDir
}
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
'''

        fd, script_path = tempfile.mkstemp(prefix="commodus_upd_", suffix=".ps1")
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(ps_script)

        # Strip PyInstaller/GTK runtime env vars so the relaunched exe initializes cleanly
        clean_env = os.environ.copy()
        for var in ("_MEIPASS2", "FONTCONFIG_PATH", "FONTCONFIG_FILE", "PYTHONHOME", "PYTHONPATH"):
            clean_env.pop(var, None)

        powershell_exe = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )
        subprocess.Popen(
            [
                powershell_exe,
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", script_path,
                "-TargetPid", str(os.getpid()),
                "-AppDir", app_dir,
                "-PayloadDir", self._prepared_payload_dir,
                "-StagingRoot", self._prepared_staging_root,
                "-ExeName", exe_name,
                "-LogPath", log_path,
            ],
            env=clean_env,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
