"""In-app auto-update against GitHub Releases.

Flow (packaged builds only):
1. :func:`check` asks the GitHub API for the latest release and compares its
   tag to the running version.
2. If newer, :func:`download` streams the release's ``.exe`` asset to a file
   next to the current executable.
3. :func:`apply_and_restart` writes a tiny batch script that waits for this
   process to exit, swaps in the new exe, relaunches it, and deletes itself.

Everything is best-effort and stdlib-only (``urllib``) so it works inside the
frozen build without extra dependencies. Running from source is a no-op — there
is no single exe to replace.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = "jason2071/gift-drop"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
_TIMEOUT = 15


@dataclass(frozen=True)
class Update:
    version: str            # e.g. "1.1.0"
    tag: str                # e.g. "v1.1.0"
    exe_url: str            # browser_download_url of the .exe asset
    size: int               # bytes


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)) or (0,)


def _get(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "GiftDrop-updater", "Accept": "application/vnd.github+json"}
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
        return resp.read()


def check(current_version: str) -> Update | None:
    """Return an :class:`Update` if the latest release is newer, else ``None``.
    Never raises — any error (offline, rate-limited, malformed) yields ``None``."""
    try:
        data = json.loads(_get(API_LATEST))
        tag = data.get("tag_name") or ""
        latest = tag.lstrip("vV")
        if _version_tuple(latest) <= _version_tuple(current_version):
            return None
        exe = next(
            (a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")),
            None,
        )
        if not exe:
            return None
        return Update(
            version=latest,
            tag=tag,
            exe_url=exe["browser_download_url"],
            size=int(exe.get("size", 0)),
        )
    except Exception:  # noqa: BLE001 - update check must never crash the app
        return None


def download(update: "Update", dest: Path, progress=None) -> bool:
    """Stream the new exe to ``dest``. ``progress(fraction)`` is called 0..1.
    Returns True on success. Never raises."""
    try:
        req = urllib.request.Request(update.exe_url, headers={"User-Agent": "GiftDrop-updater"})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            total = int(resp.headers.get("Content-Length") or update.size or 0)
            done = 0
            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(min(1.0, done / total))
        return True
    except Exception:  # noqa: BLE001
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def new_exe_path() -> Path:
    """Where to stage the downloaded exe: beside the current one (same volume,
    same permissions, so the swap ``move`` succeeds)."""
    cur = Path(sys.executable)
    return cur.with_name(cur.stem + ".new.exe")


def apply_and_restart(new_exe: Path) -> None:
    """Swap ``new_exe`` in for the running executable and relaunch. Spawns a
    detached batch script that waits for this process to exit first. The caller
    should close the app immediately after."""
    cur = Path(sys.executable)
    pid = os.getpid()
    bat = cur.with_name("giftdrop_update.bat")
    script = (
        "@echo off\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>nul | findstr /I "{pid}" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  ping -n 2 127.0.0.1 >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        f'move /Y "{new_exe}" "{cur}" >nul\r\n'
        f'start "" "{cur}"\r\n'
        'del "%~f0"\r\n'
    )
    bat.write_text(script, encoding="ascii")
    DETACHED = 0x00000008  # DETACHED_PROCESS
    NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        creationflags=DETACHED | NO_WINDOW,
        close_fds=True,
    )
