"""
VAL Terminal v5.0 — Elite Command Shell
=========================================
~50 whitelisted commands.
Linux ↔ Windows auto-translation.
Session working-directory memory.
Background task support (append & to run detached).
Streamed output line-by-line for real-time chat display.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Dict, Optional

logger = logging.getLogger("val.terminal")

IS_WIN = platform.system() == "Windows"

# ─── Security mode registry ───────────────────────────────────────────────────
# Keyed by session_id; default SAFE
_session_modes: Dict[str, str] = {}
_mode_lock = threading.Lock()

def get_mode(session_id: str = "default") -> str:
    return _session_modes.get(session_id, "SAFE").upper()

def set_mode(session_id: str, mode: str) -> str:
    mode = mode.upper()
    if mode not in ("SAFE", "POWER", "LAB"):
        mode = "SAFE"
    with _mode_lock:
        _session_modes[session_id] = mode
    logger.info("[Terminal] Session %s → mode %s", session_id, mode)
    return mode

# ─── Working directory per session ───────────────────────────────────────────
_session_cwd: Dict[str, Path] = {}
_cwd_lock = threading.Lock()

def get_cwd(session_id: str = "default") -> Path:
    with _cwd_lock:
        return _session_cwd.get(session_id, Path.cwd())

def set_cwd(session_id: str, new_path: str) -> Optional[Path]:
    p = Path(new_path).expanduser().resolve()
    if p.is_dir():
        with _cwd_lock:
            _session_cwd[session_id] = p
        return p
    return None

# ─── Command allowlist ───────────────────────────────────────────────────────

# SAFE: read-only, no network attack tools
SAFE_COMMANDS = {
    "ls", "dir", "pwd", "cat", "type", "head", "tail", "echo",
    "whoami", "id", "hostname", "uname", "ver", "date", "uptime", "env",
    "ps", "tasklist", "top", "df", "du", "free", "lsblk",
    "ping", "traceroute", "tracert", "netstat", "ss", "ip", "ifconfig", "ipconfig",
    "nslookup", "dig", "whois", "host", "curl", "wget",
    "find", "grep", "findstr", "locate", "which", "where", "ls",
    "git", "python", "python3", "pip", "pip3", "node", "npm",
    "mkdir", "wc", "sort", "uniq", "awk", "sed",
    "zip", "unzip", "tar",
    "systeminfo", "ver",
}

# POWER: adds attack/recon tools
POWER_COMMANDS = SAFE_COMMANDS | {
    "nmap", "hashcat", "ffuf", "gobuster", "sqlmap", "nikto",
    "subfinder", "amass", "hydra", "masscan", "tcpdump",
    "chmod", "chown", "attrib",
    "mv", "move", "cp", "copy", "rm", "del", "rmdir",
    "kill", "pkill", "taskkill",
    "ssh", "scp", "rsync",
    "docker", "systemctl", "service",
    "watch", "screen", "tmux",
    "awk", "xargs",
}

# LAB: everything in POWER plus unrestricted (still blocks catastrophic)
LAB_COMMANDS = POWER_COMMANDS | {
    "nc", "netcat", "socat", "msfconsole", "msfvenom",
    "crackmapexec", "enum4linux", "ldapsearch", "snmpwalk",
}

# Commands that are ALWAYS blocked regardless of mode
BLOCKED_ALWAYS = {
    "format", "fdisk", "mkfs", "dd",
    "shutdown", "reboot", "halt", "poweroff",
    "passwd", "su", "sudo",
}
BLOCKED_ARGS = [
    re.compile(r"\brm\s+-rf\s+/", re.I),
    re.compile(r"\bdel\s+/f\s+/s\s+/q\s+[a-z]:\\", re.I),
    re.compile(r"\bformat\s+[a-z]:", re.I),
    re.compile(r":.*\{.*:.*\}", re.I),   # fork bomb
    re.compile(r"\bchmod\s+777\s+/", re.I),
]

# ─── Linux → Windows translation ─────────────────────────────────────────────
_LIN_WIN: dict[str, list[str]] = {
    "ls":         ["dir"],
    "cat":        ["type"],
    "grep":       ["findstr"],
    "find":       ["dir", "/s", "/b"],
    "whoami":     ["whoami"],
    "ps":         ["tasklist"],
    "kill":       ["taskkill", "/PID"],
    "rm":         ["del"],
    "mkdir":      ["mkdir"],
    "rmdir":      ["rmdir"],
    "mv":         ["move"],
    "cp":         ["copy"],
    "ifconfig":   ["ipconfig"],
    "uname":      ["ver"],
    "df":         ["wmic", "logicaldisk", "get", "size,freespace,caption"],
    "free":       ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize"],
    "traceroute": ["tracert"],
    "pkill":      ["taskkill", "/IM"],
    "which":      ["where"],
    "env":        ["set"],
}

# ─── Command result ───────────────────────────────────────────────────────────

@dataclass
class TerminalResult:
    command:     str
    output:      str
    exit_code:   int = 0
    blocked:     bool = False
    reason:      str = ""
    duration_ms: float = 0.0
    session_id:  str = "default"

# ─── Core execution ───────────────────────────────────────────────────────────

def _allowed(cmd_name: str, session_id: str = "default") -> bool:
    mode = get_mode(session_id)
    if cmd_name.lower() in BLOCKED_ALWAYS:
        return False
    if mode == "LAB":
        return cmd_name.lower() not in BLOCKED_ALWAYS
    if mode == "POWER":
        return cmd_name.lower() in POWER_COMMANDS
    return cmd_name.lower() in SAFE_COMMANDS

def _check_blocked_args(full_cmd: str) -> Optional[str]:
    for pat in BLOCKED_ARGS:
        if pat.search(full_cmd):
            return f"Blocked dangerous pattern: {pat.pattern}"
    return None

def _translate(parts: list[str]) -> list[str]:
    """Auto-translate Linux commands to Windows equivalents."""
    if not IS_WIN:
        return parts
    name = parts[0].lower()
    if name in _LIN_WIN:
        new_base = _LIN_WIN[name]
        return new_base + parts[1:]
    return parts

def execute(
    command: str,
    session_id: str = "default",
    timeout: int = 30,
) -> TerminalResult:
    """Execute a whitelisted command synchronously."""
    t0  = time.monotonic()
    cmd = command.strip()

    # Background task detection
    background = cmd.endswith("&")
    if background:
        cmd = cmd[:-1].strip()

    # Split safely
    try:
        parts = shlex.split(cmd, posix=not IS_WIN)
    except ValueError:
        parts = cmd.split()

    if not parts:
        return TerminalResult(command=command, output="Empty command.", blocked=True, reason="empty")

    cmd_name = parts[0].lower().lstrip("./")

    # cd is special — update session CWD, don't exec
    if cmd_name == "cd":
        target = parts[1] if len(parts) > 1 else str(Path.home())
        new_p  = set_cwd(session_id, target)
        if new_p:
            return TerminalResult(command=command, output=str(new_p),
                                   duration_ms=(time.monotonic() - t0) * 1000)
        return TerminalResult(command=command, output=f"cd: {target}: No such directory",
                               exit_code=1, duration_ms=(time.monotonic() - t0) * 1000)

    # pwd
    if cmd_name in ("pwd", "cd."):
        cwd = get_cwd(session_id)
        return TerminalResult(command=command, output=str(cwd),
                               duration_ms=(time.monotonic() - t0) * 1000)

    # Allowlist check
    if not _allowed(cmd_name, session_id):
        reason = f"'{cmd_name}' blocked in {get_mode(session_id)} mode"
        return TerminalResult(command=command, output=f"⛔ {reason}",
                               blocked=True, reason=reason,
                               duration_ms=(time.monotonic() - t0) * 1000)

    # Blocked argument patterns
    block_reason = _check_blocked_args(cmd)
    if block_reason:
        return TerminalResult(command=command, output=f"⛔ {block_reason}",
                               blocked=True, reason=block_reason,
                               duration_ms=(time.monotonic() - t0) * 1000)

    # Translate
    translated = _translate(parts)

    # Resolve cwd
    cwd = str(get_cwd(session_id))

    # Execute
    try:
        if background:
            subprocess.Popen(
                translated, cwd=cwd, shell=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            output = f"[Running in background: {' '.join(translated)}]"
            code   = 0
        else:
            result = subprocess.run(
                translated, capture_output=True, text=True,
                timeout=timeout, cwd=cwd, shell=False,
                encoding="utf-8", errors="replace",
            )
            output   = (result.stdout or result.stderr or "").strip()
            code     = result.returncode
            if not output:
                output = f"[Exit code: {code}]"

        # Cap output
        if len(output) > 32_000:
            output = output[:32_000] + "\n… [output truncated]"

    except FileNotFoundError:
        output, code = f"Command not found: {translated[0]}", 127
    except subprocess.TimeoutExpired:
        output, code = f"⏱ Timeout after {timeout}s", -1
    except Exception as e:
        output, code = f"[Error: {e}]", -1

    return TerminalResult(
        command=command,
        output=output,
        exit_code=code,
        duration_ms=(time.monotonic() - t0) * 1000,
        session_id=session_id,
    )


async def execute_async(
    command: str,
    session_id: str = "default",
    timeout: int = 30,
) -> TerminalResult:
    loop = asyncio.get_running_loop()
    from val.models.governor import tools_pool
    return await loop.run_in_executor(
        tools_pool, lambda: execute(command, session_id, timeout)
    )


async def stream_execute(
    command: str,
    session_id: str = "default",
    timeout: int = 60,
) -> AsyncIterator[str]:
    """Stream output line by line for real-time chat display."""
    cmd = command.strip()
    if cmd.endswith("&"):
        cmd = cmd[:-1].strip()

    try:
        parts = shlex.split(cmd, posix=not IS_WIN)
    except ValueError:
        parts = cmd.split()

    if not parts:
        yield "Empty command."
        return

    cmd_name = parts[0].lower().lstrip("./")

    if not _allowed(cmd_name, session_id):
        yield f"⛔ '{cmd_name}' blocked in {get_mode(session_id)} mode"
        return

    block_reason = _check_blocked_args(cmd)
    if block_reason:
        yield f"⛔ {block_reason}"
        return

    translated = _translate(parts)
    cwd = str(get_cwd(session_id))

    try:
        proc = await asyncio.create_subprocess_exec(
            *translated,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
        try:
            async with asyncio.timeout(timeout):
                async for line in proc.stdout:
                    yield line.decode("utf-8", errors="replace").rstrip()
        except asyncio.TimeoutError:
            proc.kill()
            yield f"⏱ Timeout after {timeout}s"
        await proc.wait()
    except FileNotFoundError:
        yield f"Command not found: {translated[0]}"
    except Exception as e:
        yield f"[Error: {e}]"


# ─── Natural language → command extraction ────────────────────────────────────

_NL_ALIASES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bshow\s+(?:all\s+)?(?:running\s+)?processes\b", re.I),    "ps aux"),
    (re.compile(r"\blist\s+(?:all\s+)?\.?py\s+files\b", re.I),              "find . -name '*.py'"),
    (re.compile(r"\bshow\s+(?:gpu|graphics)\s+usage\b", re.I),              "nvidia-smi"),
    (re.compile(r"\bshow\s+(?:open\s+)?ports\b", re.I),                     "netstat -tlnp"),
    (re.compile(r"\bkill\s+port\s+(\d+)\b", re.I),                         "kill_port_{1}"),
    (re.compile(r"\btop\s+processes\b", re.I),                              "ps aux --sort=-%cpu"),
    (re.compile(r"\bshow\s+(?:disk|storage)\s+usage\b", re.I),             "df -h"),
    (re.compile(r"\bshow\s+(?:memory|ram)\s+usage\b", re.I),               "free -h"),
    (re.compile(r"\bwatch\s+gpu\b", re.I),                                  "watch -n 2 nvidia-smi"),
    (re.compile(r"\btail\s+logs?\s+live\b", re.I),                          "tail -f"),
    (re.compile(r"\bfind\s+files?\s+(?:with\s+)?(?:name\s+)?(.+)\b", re.I), "find . -name '{1}'"),
    (re.compile(r"\bgrep\s+(.+?)\s+recursively\b", re.I),                  "grep -r '{1}' ."),
    (re.compile(r"\bzip\s+(?:project|folder)\b", re.I),                    "zip -r project.zip ."),
    (re.compile(r"\bshow\s+system\s+info\b", re.I),                        "uname -a"),
    (re.compile(r"\bshow\s+network\s+(?:info|interfaces)\b", re.I),        "ip addr"),
]

def nl_to_command(text: str) -> Optional[str]:
    """Try to extract a natural-language-described command."""
    for pat, template in _NL_ALIASES:
        m = pat.search(text)
        if m:
            try:
                cmd = template
                for i, g in enumerate(m.groups(), 1):
                    cmd = cmd.replace(f"{{{i}}}", g or "")
                return cmd
            except Exception:
                return template
    return None


def is_terminal_request(text: str) -> bool:
    """Detect if the text looks like a terminal command request."""
    t = text.strip().lstrip("$").strip()
    try:
        parts = shlex.split(t, posix=not IS_WIN)
    except ValueError:
        parts = t.split()
    if not parts:
        return False
    return parts[0].lower() in SAFE_COMMANDS | POWER_COMMANDS | LAB_COMMANDS


def handle_terminal_request(
    text: str,
    session_id: str = "default",
) -> str:
    """Convenience wrapper used by server.py."""
    # Try NL first
    cmd = nl_to_command(text)
    if not cmd:
        cmd = text.strip().lstrip("$").strip()
    r = execute(cmd, session_id)
    return r.output


# ─── Exported allowlist info ──────────────────────────────────────────────────
ALLOWED_COMMANDS = SAFE_COMMANDS
ALLOWED_BASE     = SAFE_COMMANDS
OPERATOR_MODE    = True
