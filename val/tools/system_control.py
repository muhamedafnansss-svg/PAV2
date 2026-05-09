"""
VAL System Control v15.0 — OS-Level Command Execution
=======================================================
Voice-driven system control:
  - Open/close applications
  - Volume control (Windows API)
  - File search
  - Clipboard read/write
  - System info queries
"""

from __future__ import annotations
import logging, os, subprocess, platform, threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("val.tools.sysctl")

IS_WINDOWS = platform.system() == "Windows"

# ─── App Control ──────────────────────────────────────────────────────────────

_APP_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "browser": "start https://google.com",
    "chrome": "start chrome",
    "firefox": "start firefox",
    "explorer": "explorer.exe",
    "file manager": "explorer.exe",
    "terminal": "wt.exe" if IS_WINDOWS else "gnome-terminal",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "paint": "mspaint.exe",
    "word": "start winword",
    "excel": "start excel",
    "vscode": "code",
    "code": "code",
}

def open_app(app_name: str) -> str:
    """Open an application by name."""
    name = app_name.strip().lower()
    cmd = _APP_ALIASES.get(name)
    if not cmd:
        # Try direct execution
        cmd = name
    try:
        if IS_WINDOWS:
            subprocess.Popen(cmd, shell=True)
        else:
            subprocess.Popen(cmd.split(), start_new_session=True)
        logger.info("[SysCtl] Opened: %s", app_name)
        return f"Opened {app_name}."
    except Exception as e:
        return f"Could not open {app_name}: {e}"

def close_app(app_name: str) -> str:
    """Close an application by name."""
    name = app_name.strip().lower()
    try:
        if IS_WINDOWS:
            # Try graceful close first
            result = subprocess.run(
                ["taskkill", "/IM", f"{name}.exe", "/F"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return f"Closed {app_name}."
            # Try without .exe
            result = subprocess.run(
                ["taskkill", "/IM", name, "/F"],
                capture_output=True, text=True, timeout=5,
            )
            return f"Closed {app_name}." if result.returncode == 0 else f"Could not find {app_name}."
        else:
            subprocess.run(["pkill", "-f", name], timeout=5)
            return f"Closed {app_name}."
    except Exception as e:
        return f"Could not close {app_name}: {e}"


# ─── Volume Control ──────────────────────────────────────────────────────────

def set_volume(level: int) -> str:
    """Set system volume (0-100). Windows only via nircmd or PowerShell."""
    level = max(0, min(100, level))
    try:
        if IS_WINDOWS:
            # Use PowerShell to set volume
            ps_cmd = f"""
            $wshShell = New-Object -ComObject WScript.Shell
            # Mute first, then set volume
            1..50 | ForEach-Object {{ $wshShell.SendKeys([char]174) }}
            1..{level // 2} | ForEach-Object {{ $wshShell.SendKeys([char]175) }}
            """
            # Alternative: use pycaw if available
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                volume.SetMasterVolumeLevelScalar(level / 100.0, None)
                return f"Volume set to {level}%."
            except ImportError:
                pass

            # Fallback: nircmd
            subprocess.run(["nircmd", "setsysvolume", str(int(65535 * level / 100))],
                           capture_output=True, timeout=3)
            return f"Volume set to {level}%."
        return "Volume control not supported on this OS."
    except Exception as e:
        return f"Could not set volume: {e}"

def mute_toggle() -> str:
    """Toggle system mute."""
    try:
        if IS_WINDOWS:
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
                current = volume.GetMute()
                volume.SetMute(not current, None)
                return "Unmuted." if current else "Muted."
            except ImportError:
                subprocess.run(["nircmd", "mutesysvolume", "2"], capture_output=True, timeout=3)
                return "Toggled mute."
    except Exception as e:
        return f"Mute toggle failed: {e}"
    return "Not supported."


# ─── Clipboard ────────────────────────────────────────────────────────────────

def clipboard_read() -> str:
    """Read from system clipboard."""
    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=3,
            )
            return result.stdout.strip() or "(clipboard empty)"
        return "(clipboard not supported)"
    except Exception as e:
        return f"Clipboard read failed: {e}"

def clipboard_write(text: str) -> str:
    """Write to system clipboard."""
    try:
        if IS_WINDOWS:
            process = subprocess.Popen(
                ["powershell", "-Command", f"Set-Clipboard -Value '{text}'"],
                stdin=subprocess.PIPE,
            )
            process.communicate(timeout=3)
            return f"Copied to clipboard ({len(text)} chars)."
        return "(clipboard not supported)"
    except Exception as e:
        return f"Clipboard write failed: {e}"


# ─── File Search ──────────────────────────────────────────────────────────────

def search_files(query: str, root: str = ".", max_results: int = 20) -> str:
    """Search for files matching a pattern."""
    root_path = Path(root).resolve()
    results = []
    try:
        for p in root_path.rglob(f"*{query}*"):
            if len(results) >= max_results:
                break
            # Skip hidden, node_modules, venv, __pycache__
            parts = p.parts
            if any(x.startswith(".") or x in ("node_modules", "venv", "__pycache__", ".git") for x in parts):
                continue
            results.append(str(p.relative_to(root_path)))
    except PermissionError:
        pass
    except Exception as e:
        return f"Search error: {e}"

    if not results:
        return f"No files matching '{query}' found."
    return f"Found {len(results)} files:\n" + "\n".join(f"  {r}" for r in results)


# ─── System Control Router ───────────────────────────────────────────────────

def execute_system_command(command: str) -> str:
    """Parse and execute a system control command from natural language."""
    cmd = command.strip().lower()

    # Open app
    import re
    m = re.match(r"(?:open|launch|start|run)\s+(.+)", cmd)
    if m:
        return open_app(m.group(1))

    # Close app
    m = re.match(r"(?:close|quit|exit|kill|stop)\s+(.+)", cmd)
    if m:
        return close_app(m.group(1))

    # Volume
    m = re.match(r"(?:set\s+)?volume\s+(?:to\s+)?(\d+)", cmd)
    if m:
        return set_volume(int(m.group(1)))
    if "mute" in cmd:
        return mute_toggle()
    if "volume up" in cmd:
        return set_volume(80)
    if "volume down" in cmd:
        return set_volume(30)

    # Clipboard
    if "clipboard" in cmd and ("read" in cmd or "show" in cmd or "paste" in cmd):
        return clipboard_read()
    m = re.match(r"copy\s+(.+)\s+to\s+clipboard", cmd)
    if m:
        return clipboard_write(m.group(1))

    # File search
    m = re.match(r"(?:find|search|locate)\s+(?:file[s]?\s+)?(.+)", cmd)
    if m:
        return search_files(m.group(1))

    return f"System command not recognized: {command}"
