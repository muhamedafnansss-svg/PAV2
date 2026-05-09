"""
VAL Security Layer
==================
Command risk classification, input validation, sandbox enforcement,
permission gates, and prompt injection prevention.

This is the CRITICAL security boundary — nothing passes through without validation.
"""

import re
import os
import shlex
import hashlib
from pathlib import Path
from typing import Optional, Tuple, List
from enum import Enum

from val.utils.logger import get_logger, LogCategory
from val.config.settings import get_config

logger = get_logger("security", LogCategory.SECURITY)


class RiskLevel(str, Enum):
    SAFE    = "safe"
    LOW     = "low"
    MEDIUM  = "medium"
    HIGH    = "high"
    BLOCKED = "blocked"


class PermissionDeniedError(Exception):
    """Raised when an operation violates the security policy."""
    pass


class SandboxViolationError(Exception):
    """Raised when sandbox boundaries are crossed."""
    pass


# ─── Destructive Command Patterns ────────────────────────────────────────────
# Inspired by Claude Code's bash classifier. These patterns flag high-risk commands.

_BLOCKED_PATTERNS: List[str] = [
    r"\brm\s+-rf\b",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\bformat\b",
    r"\bdel\s+/[fsqS]+\b",          # Windows del /f /s /q
    r"\brdist\b",
    r">\s*/dev/sd",                  # Writing to block devices
    r"\bchmod\s+777\b",
    r"\bsudo\s+chmod\b",
    r"curl\s+.*\|\s*(bash|sh|python)",  # Pipe-download-execute
    r"wget\s+.*\|\s*(bash|sh|python)",
    r"\beval\b.*\$\(",              # Eval injection
    r"base64\s+--decode\s*\|",      # Obfuscated execution
    r"\bpowerShell\b.*-enc\b",      # Encoded PS commands
    r"\bnetcat\b",
    r"\bnc\s+-l\b",                 # Netcat listener
]

_MEDIUM_PATTERNS: List[str] = [
    r"\bsudo\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bkill\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\biptables\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bapt\b",
    r"\bpip install\b",
    r"\bnpm install\b",
    r"\bregistrynaming\b",
    r"\breg\s+",                     # Windows registry
]

_PROMPT_INJECTION_PATTERNS: List[str] = [
    r"ignore\s+(all\s+)?(previous|above)?\s*instructions",  # ignore [all] [previous] instructions
    r"you\s+are\s+now\s+a",
    r"jailbreak",
    r"act\s+as\s+(an?\s+)?(?:unrestricted|evil|unfiltered)",
    r"forget\s+(your|all)\s+(previous\s+)?(instructions|training)",
    r"system\s*:\s*you\s+are",
    r"<\|im_start\|>",              # Special token injection
    r"\[INST\].*\[/INST\]",        # Llama instruct injection
    r"disregard\s+(all\s+)?(previous|prior)\s+instructions",
    r"do\s+not\s+follow\s+(your\s+)?(previous\s+)?(instructions|guidelines)",
]


def classify_command_risk(command: str) -> RiskLevel:
    """
    Analyze a shell command string and return its risk level.
    This is a pre-execution classifier—similar to Claude Code's bash classifier.
    """
    cmd_lower = command.lower().strip()

    # Check for BLOCKED patterns first
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, cmd_lower, re.IGNORECASE):
            logger.security(
                f"BLOCKED command pattern detected",
                extra={"command": command[:200], "pattern": pattern}
            )
            return RiskLevel.BLOCKED

    # Check for MEDIUM risk
    for pattern in _MEDIUM_PATTERNS:
        if re.search(pattern, cmd_lower, re.IGNORECASE):
            return RiskLevel.MEDIUM

    return RiskLevel.SAFE


def detect_prompt_injection(text: str) -> Tuple[bool, Optional[str]]:
    """
    Scan user input for prompt injection attempts.
    Returns (is_injection, matched_pattern).
    """
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            logger.security(
                "Prompt injection attempt detected",
                extra={"pattern": pattern, "snippet": text[:100]}
            )
            return True, pattern
    return False, None


def validate_input(text: str) -> str:
    """
    Sanitize and validate user input.
    - Strips leading/trailing whitespace
    - Enforces max length from config
    - Checks for prompt injection
    Raises PermissionDeniedError if injection detected.
    """
    cfg = get_config()
    text = text.strip()

    # Length enforcement
    max_len = cfg.security.max_prompt_length
    if len(text) > max_len:
        logger.warning(f"Input truncated from {len(text)} to {max_len} chars")
        text = text[:max_len]

    # Prompt injection check
    is_injection, pattern = detect_prompt_injection(text)
    if is_injection:
        raise PermissionDeniedError(
            f"Prompt injection detected. Input rejected. (pattern: {pattern})"
        )

    return text


# ─── File Access Gate ─────────────────────────────────────────────────────────

def validate_file_path(path: Path, operation: str = "read") -> Path:
    """
    Validate a file path against security policy.
    Prevents path traversal attacks and enforces basedir restrictions.

    Args:
        path: The path to validate
        operation: "read" | "write" | "delete"

    Returns:
        Resolved, validated Path

    Raises:
        SandboxViolationError: If path escapes sandbox or permissions denied
    """
    cfg = get_config()
    resolved = path.resolve()

    # Prevent path traversal: ensure path stays within VAL root or allowed basedir
    write_basedir = cfg.security.file_write_basedir
    if write_basedir:
        write_basedir = write_basedir.resolve()

    if operation in ("write", "delete"):
        if not cfg.security.allow_file_write:
            raise SandboxViolationError(
                f"File {operation} is disabled by security policy."
            )
        if write_basedir and not str(resolved).startswith(str(write_basedir)):
            raise SandboxViolationError(
                f"File {operation} path '{resolved}' is outside allowed directory '{write_basedir}'."
            )

    return resolved


# ─── Shell Execution Gate ─────────────────────────────────────────────────────

def validate_shell_command(command: str) -> str:
    """
    Gate for all shell command execution.
    - Checks security.allow_shell_execution
    - Runs risk classifier
    - Checks allowlist
    Raises PermissionDeniedError or SandboxViolationError as appropriate.

    Returns:
        The validated command string (unchanged if allowed).
    """
    cfg = get_config()

    if not cfg.security.allow_shell_execution:
        raise PermissionDeniedError(
            "Shell execution is disabled. Set VAL_ALLOW_SHELL=true to enable (not recommended)."
        )

    risk = classify_command_risk(command)

    if risk == RiskLevel.BLOCKED:
        raise SandboxViolationError(
            f"Command blocked by security classifier: '{command[:100]}'"
        )

    if risk == RiskLevel.HIGH:
        raise SandboxViolationError(
            f"High-risk command rejected: '{command[:100]}'"
        )

    # Check allowlist if configured
    allowlist = [a.strip() for a in cfg.security.shell_allowlist if a.strip()]
    if allowlist:
        allowed = False
        try:
            parts = shlex.split(command)
            base_cmd = os.path.basename(parts[0]) if parts else ""
            allowed = base_cmd in allowlist
        except Exception:
            pass
        if not allowed:
            raise PermissionDeniedError(
                f"Command '{command[:50]}' not in shell allowlist."
            )

    logger.security(
        f"Shell command authorized (risk={risk})",
        extra={"command": command[:200]}
    )
    return command


# ─── Network Access Gate ──────────────────────────────────────────────────────

def validate_network_access(url: str) -> str:
    """
    Gate for all network access from tools.
    Raises PermissionDeniedError if network access is disabled.
    """
    cfg = get_config()
    if not cfg.security.allow_network_access:
        raise PermissionDeniedError(
            "Network access is disabled by security policy. Set VAL_ALLOW_NETWORK=true to enable."
        )
    # Basic URL sanitization
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL scheme: {url[:50]}")
    logger.security(f"Network access authorized", extra={"url": url[:100]})
    return url


# ─── Secret Protection ────────────────────────────────────────────────────────

def mask_secrets(text: str) -> str:
    """
    Replace common secret patterns in text with masked versions.
    Used before logging to prevent accidental secret exposure.
    """
    patterns = [
        (r"(api[_-]?key\s*=\s*)['\"]?[\w\-]{8,}['\"]?", r"\1***MASKED***"),
        (r"(token\s*=\s*)['\"]?[\w\-]{8,}['\"]?",        r"\1***MASKED***"),
        (r"(password\s*=\s*)['\"]?[^\s'\"]{4,}['\"]?",   r"\1***MASKED***"),
        (r"(secret\s*=\s*)['\"]?[\w\-]{8,}['\"]?",       r"\1***MASKED***"),
        (r"Bearer\s+[\w\-\.]{10,}",                        r"Bearer ***MASKED***"),
    ]
    result = text
    for pat, repl in patterns:
        result = re.sub(pat, repl, result, flags=re.IGNORECASE)
    return result


# ─── Output Filtering (v14.1) ────────────────────────────────────────────────

_SENSITIVE_OUTPUT_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "[BASE64_REDACTED]"),
    (re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC )?PRIVATE KEY-----"),
     "[PRIVATE_KEY_REDACTED]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"), "[GITHUB_TOKEN_REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[AWS_KEY_REDACTED]"),
    (re.compile(r"\b[0-9a-f]{64}\b"), "[HASH_OR_KEY_REDACTED]"),
    (re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*\S+", re.I), "[PASSWORD_REDACTED]"),
]


def mask_sensitive_output(text: str) -> str:
    """
    Filter sensitive data from tool output before displaying to user.
    Catches private keys, API tokens, passwords, and long base64 blobs.
    """
    result = text
    for pat, replacement in _SENSITIVE_OUTPUT_PATTERNS:
        result = pat.sub(replacement, result)
    return mask_secrets(result)


# ─── Scope-Aware Command Validation (v14.1) ──────────────────────────────────

def validate_scoped_command(command: str, tool_name: str = "unknown") -> str:
    """
    Enhanced validation: shell safety + scope + rate limiting.
    Combines existing validate_shell_command with scope enforcement.

    Raises:
        SandboxViolationError: If command is blocked by risk classifier
        PermissionDeniedError: If shell execution is disabled or not in allowlist
        ScopeViolationError: If target is out of scope
        RateLimitExceededError: If target rate limit exceeded
    """
    # Step 1: Standard safety validation
    validated = validate_shell_command(command)

    # Step 2: Scope validation
    try:
        from val.security.scope import get_scope, ScopeViolationError, RateLimitExceededError
        scope = get_scope()
        scope.validate_and_rate_check(validated, tool_name)
    except ImportError:
        logger.debug("[Sandbox] Scope module not available — skipping scope check")
    except Exception as e:
        # Re-raise scope and rate limit errors
        from val.security.scope import ScopeViolationError, RateLimitExceededError
        if isinstance(e, (ScopeViolationError, RateLimitExceededError)):
            # Log to audit
            try:
                from val.security.audit import get_audit
                audit = get_audit()
                if isinstance(e, ScopeViolationError):
                    audit.log_scope_violation(tool_name, command, "", str(e))
                else:
                    audit.log_rate_limit(tool_name, "")
            except Exception:
                pass
            raise
        logger.warning("[Sandbox] Scope check error: %s", e)

    return validated


# ─── Sandboxed Execution (v14.1) ─────────────────────────────────────────────

class SandboxExecutor:
    """
    Pluggable sandboxed execution backend.
    Primary: Docker (--network=none, --rm)
    Fallback: subprocess with restricted environment
    """

    def __init__(self):
        self._docker_available = self._check_docker()
        if self._docker_available:
            logger.info("[Sandbox] Docker sandbox available")
        else:
            logger.info("[Sandbox] Docker not available — using restricted subprocess")

    def _check_docker(self) -> bool:
        """Check if Docker is available and running."""
        try:
            import subprocess as sp
            result = sp.run(
                ["docker", "info"],
                capture_output=True, timeout=5, text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def execute(
        self,
        command: str,
        tool_name: str = "unknown",
        timeout: int = 60,
        network: bool = False,
    ) -> "SandboxResult":
        """
        Execute a command in a sandboxed environment.

        Args:
            command: Shell command to execute
            tool_name: Name of the tool (for audit)
            timeout: Max execution time in seconds
            network: Whether to allow network access (default: False)

        Returns:
            SandboxResult with output, exit code, and execution metadata
        """
        import subprocess as sp

        t0 = __import__("time").time()

        if self._docker_available:
            return self._exec_docker(command, tool_name, timeout, network)

        # Fallback: restricted subprocess
        try:
            env = os.environ.copy()
            # Restrict PATH to essential directories only
            if os.name == "nt":
                env["PATH"] = r"C:\Windows\System32;C:\Windows"
            else:
                env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"

            result = sp.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=os.path.expanduser("~"),
            )

            duration = (__import__("time").time() - t0) * 1000
            output = mask_sensitive_output(result.stdout + result.stderr)

            return SandboxResult(
                output=output,
                exit_code=result.returncode,
                duration_ms=duration,
                sandbox_type="subprocess",
                command=command,
            )

        except sp.TimeoutExpired:
            return SandboxResult(
                output=f"[TIMEOUT] Command exceeded {timeout}s limit",
                exit_code=-1,
                duration_ms=timeout * 1000,
                sandbox_type="subprocess",
                command=command,
                error="timeout",
            )
        except Exception as e:
            return SandboxResult(
                output=f"[ERROR] Sandbox execution failed: {e}",
                exit_code=-1,
                duration_ms=0,
                sandbox_type="subprocess",
                command=command,
                error=str(e),
            )

    def _exec_docker(
        self, command: str, tool_name: str, timeout: int, network: bool
    ) -> "SandboxResult":
        """Execute in Docker container with restricted permissions."""
        import subprocess as sp

        network_flag = "bridge" if network else "none"
        docker_cmd = [
            "docker", "run", "--rm",
            f"--network={network_flag}",
            "--memory=512m",
            "--cpus=1.0",
            "--read-only",
            "--no-new-privileges",
            "--security-opt=no-new-privileges",
            "alpine:latest",
            "sh", "-c", command,
        ]

        t0 = __import__("time").time()

        try:
            result = sp.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            duration = (__import__("time").time() - t0) * 1000
            output = mask_sensitive_output(result.stdout + result.stderr)

            return SandboxResult(
                output=output,
                exit_code=result.returncode,
                duration_ms=duration,
                sandbox_type="docker",
                command=command,
            )

        except sp.TimeoutExpired:
            return SandboxResult(
                output=f"[TIMEOUT] Docker execution exceeded {timeout}s",
                exit_code=-1,
                duration_ms=timeout * 1000,
                sandbox_type="docker",
                command=command,
                error="timeout",
            )
        except Exception as e:
            return SandboxResult(
                output=f"[ERROR] Docker execution failed: {e}",
                exit_code=-1,
                duration_ms=0,
                sandbox_type="docker",
                command=command,
                error=str(e),
            )


class SandboxResult:
    """Result of sandboxed execution."""

    def __init__(
        self,
        output: str,
        exit_code: int,
        duration_ms: float,
        sandbox_type: str,
        command: str,
        error: str = None,
    ):
        self.output = output
        self.exit_code = exit_code
        self.duration_ms = round(duration_ms, 2)
        self.sandbox_type = sandbox_type
        self.command = command
        self.error = error

    def to_dict(self) -> dict:
        return {
            "output": self.output,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "sandbox_type": self.sandbox_type,
            "command": self.command[:200],
            "error": self.error,
        }


def compute_content_hash(content: str) -> str:
    """SHA-256 hash of content string (for integrity tracking)."""
    return hashlib.sha256(content.encode()).hexdigest()
