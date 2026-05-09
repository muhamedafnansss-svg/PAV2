"""
VAL Power Tools — Async Security & Recon Tool Adapters
=======================================================
Unified adapter layer for external security tools.
Each adapter:
  - Checks if the tool binary is installed (shutil.which)
  - Builds a subprocess command
  - Executes via asyncio.create_subprocess_exec for streaming
  - Returns structured output

Supports: nmap, shodan, hashcat, whois, nslookup, dig, curl, ping,
          traceroute, netstat, ffuf, gobuster, sqlmap, nikto, subfinder, amass
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, List, Optional, Tuple

logger = logging.getLogger("val.power_tools")

IS_WINDOWS = platform.system() == "Windows"

# ─── Hard-blocked patterns (never execute regardless of operator mode) ────────

_DESTRUCTIVE_RE = re.compile(
    r"(rm\s+-rf\s+/|format\s+[cC]:|del\s+/[sS].*system32|"
    r"mkfs|dd\s+if=.*of=/dev/sd|shutdown|reboot|"
    r":()\s*\{|fork\s*bomb|while\s+true.*rm)",
    re.IGNORECASE,
)


def is_destructive(command: str) -> bool:
    """Check if command matches hard-blocked destructive patterns."""
    return bool(_DESTRUCTIVE_RE.search(command))


# ─── Tool Result ──────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    tool: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_s: float
    installed: bool = True
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.error is None

    @property
    def output(self) -> str:
        """Formatted output string for chat display."""
        parts = [f"$ {self.command}"]
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr and self.exit_code != 0:
            parts.append(f"[stderr] {self.stderr[:1000]}")
        if self.exit_code != 0:
            parts.append(f"[exit {self.exit_code}]")
        if self.error:
            parts.append(f"[error] {self.error}")
        parts.append(f"[{self.tool} · {self.duration_s:.1f}s]")
        return "\n".join(parts)


# ─── WSL Detection ────────────────────────────────────────────────────────────

_WSL_DISTRO = os.environ.get("VAL_WSL_DISTRO", "kali-linux")
_WSL_AVAILABLE: Optional[bool] = None  # lazy-checked


def _check_wsl() -> bool:
    """Check if WSL with the target distro is available."""
    global _WSL_AVAILABLE
    if _WSL_AVAILABLE is not None:
        return _WSL_AVAILABLE
    if not IS_WINDOWS:
        _WSL_AVAILABLE = False
        return False
    try:
        import subprocess
        result = subprocess.run(
            ["wsl", "-d", _WSL_DISTRO, "--", "echo", "ok"],
            capture_output=True, text=True, timeout=5,
        )
        _WSL_AVAILABLE = result.returncode == 0 and "ok" in result.stdout
    except Exception:
        _WSL_AVAILABLE = False
    if _WSL_AVAILABLE:
        logger.info("[PowerTools] WSL '%s' detected — routing Linux tools through WSL", _WSL_DISTRO)
    return _WSL_AVAILABLE


def _wsl_has_binary(binary: str) -> bool:
    """Check if a binary exists in WSL."""
    try:
        import subprocess
        result = subprocess.run(
            ["wsl", "-d", _WSL_DISTRO, "--", "which", binary],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


# ─── Base Adapter ─────────────────────────────────────────────────────────────

class ToolAdapter(ABC):
    """Abstract base for all power tool adapters."""

    name: str = "unknown"
    binary: str = "unknown"          # binary name for shutil.which()
    win_binary: Optional[str] = None # Windows alternative binary name
    timeout: int = 120               # default timeout in seconds
    max_output: int = 16000          # max stdout chars
    wsl_capable: bool = True         # can this tool run in WSL?

    def is_installed(self) -> bool:
        """Check if the tool binary is available — natively or via WSL."""
        binary = self.win_binary if IS_WINDOWS and self.win_binary else self.binary
        if shutil.which(binary) is not None:
            return True
        # Fallback: check WSL
        if IS_WINDOWS and self.wsl_capable and _check_wsl():
            return _wsl_has_binary(self.binary)
        return False

    def _use_wsl(self) -> bool:
        """Should this command be routed through WSL?"""
        if not IS_WINDOWS or not self.wsl_capable:
            return False
        binary = self.win_binary if self.win_binary else self.binary
        if shutil.which(binary) is not None:
            return False  # native binary exists, use it
        return _check_wsl() and _wsl_has_binary(self.binary)

    @abstractmethod
    def build_args(self, user_args: str) -> List[str]:
        """Build the subprocess argument list from user input."""
        ...

    def _wrap_wsl(self, args: List[str]) -> List[str]:
        """Wrap command args for WSL execution."""
        return ["wsl", "-d", _WSL_DISTRO, "--"] + args

    async def execute(self, user_args: str) -> ToolResult:
        """Execute the tool with given arguments."""
        use_wsl = self._use_wsl()

        if not self.is_installed():
            wsl_hint = " (WSL not available — install Kali WSL: wsl --install -d kali-linux)" if IS_WINDOWS else ""
            return ToolResult(
                tool=self.name, command=f"{self.binary} {user_args}",
                stdout="", stderr="", exit_code=-1, duration_s=0.0,
                installed=False,
                error=f"'{self.binary}' not found.{wsl_hint}",
            )

        full_cmd = f"{self.binary} {user_args}".strip()
        if is_destructive(full_cmd):
            return ToolResult(
                tool=self.name, command=full_cmd,
                stdout="", stderr="", exit_code=-1, duration_s=0.0,
                error="⛔ Blocked: destructive command pattern detected.",
            )

        args = self.build_args(user_args)
        if use_wsl:
            args = self._wrap_wsl(args)
            full_cmd = f"[WSL:{_WSL_DISTRO}] {full_cmd}"
        t0 = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
            duration = time.monotonic() - t0

            stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")

            # Truncate
            if len(stdout) > self.max_output:
                stdout = stdout[:self.max_output] + f"\n... [truncated — {len(stdout)} chars total]"

            return ToolResult(
                tool=self.name, command=full_cmd,
                stdout=stdout.strip(), stderr=stderr.strip(),
                exit_code=proc.returncode or 0, duration_s=round(duration, 2),
            )

        except asyncio.TimeoutError:
            return ToolResult(
                tool=self.name, command=full_cmd,
                stdout="", stderr="", exit_code=-1,
                duration_s=round(time.monotonic() - t0, 2),
                error=f"⏱ Timeout: exceeded {self.timeout}s limit.",
            )
        except FileNotFoundError:
            return ToolResult(
                tool=self.name, command=full_cmd,
                stdout="", stderr="", exit_code=-1, duration_s=0.0,
                installed=False,
                error=f"'{self.binary}' binary not found on PATH.",
            )
        except Exception as exc:
            return ToolResult(
                tool=self.name, command=full_cmd,
                stdout="", stderr="", exit_code=-1,
                duration_s=round(time.monotonic() - t0, 2),
                error=f"Execution error: {exc}",
            )

    async def stream_execute(self, user_args: str) -> AsyncIterator[str]:
        """Stream stdout lines as they arrive."""
        if not self.is_installed():
            yield f"[error] '{self.binary}' not found on PATH."
            return

        use_wsl = self._use_wsl()
        full_cmd = f"{self.binary} {user_args}".strip()
        if is_destructive(full_cmd):
            yield "⛔ Blocked: destructive command pattern detected."
            return

        args = self.build_args(user_args)
        if use_wsl:
            args = self._wrap_wsl(args)
            yield f"$ [WSL:{_WSL_DISTRO}] {full_cmd}\n"
        else:
            yield f"$ {full_cmd}\n"

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            total_chars = 0
            async for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace")
                total_chars += len(decoded)
                if total_chars > self.max_output:
                    yield f"\n... [truncated at {self.max_output} chars]"
                    break
                yield decoded

            await asyncio.wait_for(proc.wait(), timeout=30.0)

            if proc.returncode and proc.returncode != 0:
                stderr = await proc.stderr.read()
                err_text = stderr.decode("utf-8", errors="replace").strip()
                if err_text:
                    yield f"\n[stderr] {err_text[:1000]}"
                yield f"\n[exit {proc.returncode}]"

        except asyncio.TimeoutError:
            yield f"\n[timeout after {self.timeout}s]"
        except Exception as exc:
            yield f"\n[error] {exc}"


# ─── Concrete Adapters ───────────────────────────────────────────────────────

class NmapAdapter(ToolAdapter):
    name = "nmap"
    binary = "nmap"
    timeout = 300  # scans can be slow

    def build_args(self, user_args: str) -> List[str]:
        from val.soc.soc_engine import is_target_safe
        # Simple safety extract: check if the target string in args is allowed
        # Fallback to localhost if denied.
        safe_args = []
        for arg in user_args.split():
            if not arg.startswith("-") and not is_target_safe(arg):
                safe_args.append("127.0.0.1")
            else:
                safe_args.append(arg)
        return ["nmap"] + safe_args


class ShodanAdapter(ToolAdapter):
    name = "shodan"
    binary = "shodan"
    timeout = 60

    def build_args(self, user_args: str) -> List[str]:
        return ["shodan"] + user_args.split()


class HashcatAdapter(ToolAdapter):
    name = "hashcat"
    binary = "hashcat"
    timeout = 3600  # cracking can take a long time

    def build_args(self, user_args: str) -> List[str]:
        return ["hashcat"] + user_args.split()


class WhoisAdapter(ToolAdapter):
    name = "whois"
    binary = "whois"
    win_binary = "whois"  # SysInternals whois on Windows
    timeout = 30

    def build_args(self, user_args: str) -> List[str]:
        return ["whois"] + user_args.split()


class NslookupAdapter(ToolAdapter):
    name = "nslookup"
    binary = "nslookup"
    timeout = 15

    def build_args(self, user_args: str) -> List[str]:
        return ["nslookup"] + user_args.split()


class DigAdapter(ToolAdapter):
    name = "dig"
    binary = "dig"
    timeout = 15

    def build_args(self, user_args: str) -> List[str]:
        return ["dig"] + user_args.split()


class CurlAdapter(ToolAdapter):
    name = "curl"
    binary = "curl"
    timeout = 30

    def build_args(self, user_args: str) -> List[str]:
        # Inject safety flags: no silent fail, follow redirects, max time
        base = ["curl", "-sS", "-L", "--max-time", "20"]
        return base + user_args.split()


class PingAdapter(ToolAdapter):
    name = "ping"
    binary = "ping"
    timeout = 15

    def build_args(self, user_args: str) -> List[str]:
        parts = user_args.split()
        # Limit ping count to prevent infinite ping
        has_count = any(p in parts for p in ["-c", "-n"])
        if not has_count:
            count_flag = "-n" if IS_WINDOWS else "-c"
            parts = [count_flag, "4"] + parts
        return ["ping"] + parts


class TracerouteAdapter(ToolAdapter):
    name = "traceroute"
    binary = "traceroute" if not IS_WINDOWS else "tracert"
    timeout = 60

    def build_args(self, user_args: str) -> List[str]:
        binary = "tracert" if IS_WINDOWS else "traceroute"
        return [binary] + user_args.split()


class NetstatAdapter(ToolAdapter):
    name = "netstat"
    binary = "netstat"
    timeout = 15

    def build_args(self, user_args: str) -> List[str]:
        args = user_args.split() if user_args.strip() else ["-an"]
        return ["netstat"] + args


class FfufAdapter(ToolAdapter):
    name = "ffuf"
    binary = "ffuf"
    timeout = 300

    def build_args(self, user_args: str) -> List[str]:
        return ["ffuf"] + user_args.split()


class GobusterAdapter(ToolAdapter):
    name = "gobuster"
    binary = "gobuster"
    timeout = 300

    def build_args(self, user_args: str) -> List[str]:
        return ["gobuster"] + user_args.split()


class SqlmapAdapter(ToolAdapter):
    name = "sqlmap"
    binary = "sqlmap"
    timeout = 600

    def build_args(self, user_args: str) -> List[str]:
        # Auto-add --batch to prevent interactive prompts
        parts = user_args.split()
        if "--batch" not in parts:
            parts.append("--batch")
        return ["sqlmap"] + parts


class NiktoAdapter(ToolAdapter):
    name = "nikto"
    binary = "nikto"
    timeout = 300

    def build_args(self, user_args: str) -> List[str]:
        return ["nikto"] + user_args.split()


class SubfinderAdapter(ToolAdapter):
    name = "subfinder"
    binary = "subfinder"
    timeout = 120

    def build_args(self, user_args: str) -> List[str]:
        return ["subfinder"] + user_args.split()


class AmassAdapter(ToolAdapter):
    name = "amass"
    binary = "amass"
    timeout = 300

    def build_args(self, user_args: str) -> List[str]:
        return ["amass"] + user_args.split()


class HydraAdapter(ToolAdapter):
    name = "hydra"
    binary = "hydra"
    timeout = 600

    def build_args(self, user_args: str) -> List[str]:
        return ["hydra"] + user_args.split()


# ─── Registry ────────────────────────────────────────────────────────────────

TOOL_ADAPTERS: Dict[str, ToolAdapter] = {
    "nmap":       NmapAdapter(),
    "shodan":     ShodanAdapter(),
    "hashcat":    HashcatAdapter(),
    "whois":      WhoisAdapter(),
    "nslookup":   NslookupAdapter(),
    "dig":        DigAdapter(),
    "curl":       CurlAdapter(),
    "ping":       PingAdapter(),
    "traceroute": TracerouteAdapter(),
    "tracert":    TracerouteAdapter(),     # Windows alias
    "netstat":    NetstatAdapter(),
    "ffuf":       FfufAdapter(),
    "gobuster":   GobusterAdapter(),
    "sqlmap":     SqlmapAdapter(),
    "nikto":      NiktoAdapter(),
    "subfinder":  SubfinderAdapter(),
    "amass":      AmassAdapter(),
    "hydra":      HydraAdapter(),
}

# Set of tool names for intent detection
POWER_TOOL_NAMES = set(TOOL_ADAPTERS.keys())


def get_adapter(tool_name: str) -> Optional[ToolAdapter]:
    """Get a tool adapter by name."""
    return TOOL_ADAPTERS.get(tool_name.lower())


def get_tool_status() -> Dict[str, dict]:
    """Return install status for all power tools."""
    seen = set()
    status = {}
    for name, adapter in TOOL_ADAPTERS.items():
        if name in seen:
            continue
        seen.add(name)
        status[name] = {
            "installed": adapter.is_installed(),
            "binary": adapter.binary,
            "timeout": adapter.timeout,
        }
    return status


def parse_tool_command(message: str) -> Optional[Tuple[str, str]]:
    """
    Parse a user message to extract tool name and arguments.

    Handles patterns:
      - "run nmap scanme.nmap.org"
      - "nmap scanme.nmap.org -sV"
      - "scan target.com"  → nmap
      - "whois google.com"
      - "ping 8.8.8.8"
      - "crack hash abc123" → hashcat
      - "list ports 192.168.1.1" → nmap -p-

    Returns (tool_name, args) or None.
    """
    text = message.strip()
    lower = text.lower()

    # Strip command prefixes
    for prefix in ("run ", "exec ", "execute ", "$ ", "cmd ", "shell "):
        if lower.startswith(prefix):
            text = text[len(prefix):].strip()
            lower = text.lower()
            break

    # Direct tool name match: "nmap target.com -sV"
    first_word = lower.split()[0] if lower.split() else ""
    if first_word in POWER_TOOL_NAMES:
        args = text[len(first_word):].strip()
        return (first_word, args)

    # Semantic aliases
    if lower.startswith("scan "):
        target = text[5:].strip()
        return ("nmap", target)

    if lower.startswith("crack ") or lower.startswith("crack hash "):
        args = text.split(maxsplit=1)[1] if " " in text else ""
        return ("hashcat", args)

    if lower.startswith("list ports "):
        target = text[11:].strip()
        return ("nmap", f"-p- {target}")

    if lower.startswith("lookup ") or lower.startswith("dns "):
        target = text.split(maxsplit=1)[1] if " " in text else ""
        return ("nslookup", target)

    if lower.startswith("trace "):
        target = text[6:].strip()
        return ("traceroute", target)

    return None
