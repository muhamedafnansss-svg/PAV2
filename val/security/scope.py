"""
VAL Scope Validator — CIDR/Domain Allowlist + Rate Limiting
============================================================
Enforces target scope for all cyber tool execution.
Prevents accidental or malicious out-of-scope operations.

Usage:
    scope = get_scope()
    scope.validate_target("192.168.1.100")   # OK if in allowed CIDRs
    scope.validate_target("evil.com")        # Raises ScopeViolationError
    scope.check_rate("192.168.1.100", "nmap") # Raises if rate exceeded
"""

from __future__ import annotations

import fnmatch
import ipaddress
import logging
import os
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("val.security.scope")


class ScopeViolationError(Exception):
    """Raised when a target is outside the allowed scope."""
    pass


class RateLimitExceededError(Exception):
    """Raised when a target has exceeded its rate limit."""
    pass


# ─── Scope Configuration ─────────────────────────────────────────────────────

@dataclass
class ScopeConfig:
    """
    Defines the allowed target scope for tool execution.

    Defaults:
      - RFC1918 private ranges allowed (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
      - Loopback allowed (127.0.0.0/8)
      - No external domains allowed by default
    """
    allowed_cidrs: List[str] = field(default_factory=lambda: [
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
    ])
    allowed_domains: List[str] = field(default_factory=lambda: [
        "*.local",
        "*.internal",
        "*.test",
        "localhost",
    ])
    # Rate limits: max requests per target per minute
    rate_limit_per_target: int = 30
    # Tools exempt from scope validation (e.g., local-only tools)
    exempt_tools: List[str] = field(default_factory=lambda: [
        "system_info", "val_status", "read_file", "write_file",
        "list_dir", "calculate", "read_logs", "list_processes",
        "analyze_code", "cleanup_scan", "wiki_search",
    ])

    def __post_init__(self):
        """Parse CIDRs into network objects for fast matching."""
        self._networks = []
        for cidr in self.allowed_cidrs:
            try:
                self._networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError as e:
                logger.warning("[Scope] Invalid CIDR '%s': %s", cidr, e)

    def is_ip_allowed(self, ip_str: str) -> bool:
        """Check if an IP address falls within any allowed CIDR."""
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        return any(addr in net for net in self._networks)

    def is_domain_allowed(self, domain: str) -> bool:
        """Check if a domain matches any allowed pattern (supports globs)."""
        domain_lower = domain.lower().strip(".")
        for pattern in self.allowed_domains:
            if fnmatch.fnmatch(domain_lower, pattern.lower()):
                return True
        return False

    def is_tool_exempt(self, tool_name: str) -> bool:
        """Check if a tool is exempt from scope validation."""
        return tool_name in self.exempt_tools


# ─── Target Extractor ─────────────────────────────────────────────────────────

_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_DOMAIN_RE = re.compile(r"\b([a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?(?:\.[a-zA-Z]{2,})+)\b")
_CIDR_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\b")


def extract_targets(text: str) -> Tuple[List[str], List[str]]:
    """
    Extract IP addresses and domains from command text.

    Returns:
        (ips, domains) — deduplicated lists
    """
    ips = list(set(_IP_RE.findall(text)))
    # Filter out common false positives
    ips = [ip for ip in ips if _is_valid_ip(ip)]

    domains = list(set(_DOMAIN_RE.findall(text)))
    # Remove domains that are actually IPs or common file extensions
    false_positives = {"e.g", "i.e", "etc.com", "example.com"}
    domains = [d for d in domains if d.lower() not in false_positives and not _is_valid_ip(d)]

    # Also extract CIDR targets → expand to check the network
    cidrs = _CIDR_RE.findall(text)
    for cidr in cidrs:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            ips.append(str(net.network_address))
        except ValueError:
            pass

    return ips, domains


def _is_valid_ip(ip_str: str) -> bool:
    """Validate an IP address string."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False


# ─── Per-Target Rate Limiter ──────────────────────────────────────────────────

class TargetRateLimiter:
    """
    Sliding-window rate limiter keyed by (target, tool).
    Thread-safe.
    """

    def __init__(self, max_per_minute: int = 30):
        self._max = max_per_minute
        self._buckets: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, target: str, tool: str = "default") -> bool:
        """
        Check if a request to target from tool is within rate limits.
        Returns True if allowed, False if rate exceeded.
        Automatically records the request if allowed.
        """
        key = f"{target}:{tool}"
        now = time.time()
        window = 60.0

        with self._lock:
            bucket = self._buckets[key]
            # Purge expired entries
            bucket[:] = [t for t in bucket if now - t < window]

            if len(bucket) >= self._max:
                return False

            bucket.append(now)
            return True

    def get_usage(self, target: str, tool: str = "default") -> dict:
        """Get current rate limit usage for a target+tool."""
        key = f"{target}:{tool}"
        now = time.time()
        with self._lock:
            bucket = self._buckets.get(key, [])
            active = [t for t in bucket if now - t < 60.0]
            return {
                "target": target,
                "tool": tool,
                "requests_in_window": len(active),
                "limit": self._max,
                "remaining": max(0, self._max - len(active)),
            }


# ─── Scope Validator (main interface) ─────────────────────────────────────────

class ScopeValidator:
    """
    Central scope enforcement for all tool execution.

    Validates that:
      1. Target IPs are within allowed CIDRs
      2. Target domains match allowed patterns
      3. Per-target rate limits are respected
    """

    def __init__(self, config: Optional[ScopeConfig] = None):
        self._config = config or _build_scope_from_env()
        self._rate_limiter = TargetRateLimiter(
            max_per_minute=self._config.rate_limit_per_target
        )
        logger.info(
            "[Scope] Initialized — %d CIDRs, %d domain patterns, rate=%d/min",
            len(self._config.allowed_cidrs),
            len(self._config.allowed_domains),
            self._config.rate_limit_per_target,
        )

    @property
    def config(self) -> ScopeConfig:
        return self._config

    def validate_target(self, target: str) -> bool:
        """
        Validate a single target (IP or domain).

        Returns True if target is in scope.
        Raises ScopeViolationError if out of scope.
        """
        # Check if it's an IP
        if _is_valid_ip(target):
            if self._config.is_ip_allowed(target):
                return True
            raise ScopeViolationError(
                f"Target IP '{target}' is outside allowed scope. "
                f"Allowed CIDRs: {self._config.allowed_cidrs}"
            )

        # Check if it's a domain
        if self._config.is_domain_allowed(target):
            return True

        raise ScopeViolationError(
            f"Target domain '{target}' is outside allowed scope. "
            f"Allowed patterns: {self._config.allowed_domains}"
        )

    def validate_command(self, command: str, tool_name: str = "unknown") -> bool:
        """
        Validate all targets found in a command string.

        Args:
            command: The full command text (e.g., "nmap -sV 192.168.1.1")
            tool_name: Name of the tool being executed

        Returns True if all targets are in scope.
        Raises ScopeViolationError if any target is out of scope.
        """
        # Exempt tools skip scope validation
        if self._config.is_tool_exempt(tool_name):
            return True

        ips, domains = extract_targets(command)

        # If no targets found, allow (could be a local operation)
        if not ips and not domains:
            return True

        # Validate all IPs
        for ip in ips:
            self.validate_target(ip)

        # Validate all domains
        for domain in domains:
            self.validate_target(domain)

        return True

    def check_rate(self, target: str, tool_name: str = "default") -> bool:
        """
        Check rate limit for a target+tool combination.

        Returns True if within limits.
        Raises RateLimitExceededError if rate exceeded.
        """
        if not self._rate_limiter.check(target, tool_name):
            usage = self._rate_limiter.get_usage(target, tool_name)
            raise RateLimitExceededError(
                f"Rate limit exceeded for '{target}' via '{tool_name}'. "
                f"{usage['requests_in_window']}/{usage['limit']} requests in the last minute."
            )
        return True

    def validate_and_rate_check(
        self, command: str, tool_name: str = "unknown"
    ) -> bool:
        """
        Combined scope + rate limit validation.
        Call this before every tool execution.
        """
        self.validate_command(command, tool_name)

        ips, domains = extract_targets(command)
        for target in ips + domains:
            self.check_rate(target, tool_name)

        return True

    def add_allowed_cidr(self, cidr: str) -> None:
        """Dynamically add a CIDR to the allowlist."""
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            self._config.allowed_cidrs.append(cidr)
            self._config._networks.append(net)
            logger.info("[Scope] Added CIDR: %s", cidr)
        except ValueError as e:
            logger.error("[Scope] Invalid CIDR '%s': %s", cidr, e)

    def add_allowed_domain(self, pattern: str) -> None:
        """Dynamically add a domain pattern to the allowlist."""
        self._config.allowed_domains.append(pattern)
        logger.info("[Scope] Added domain pattern: %s", pattern)

    def status(self) -> dict:
        """Return current scope configuration."""
        return {
            "allowed_cidrs": self._config.allowed_cidrs,
            "allowed_domains": self._config.allowed_domains,
            "rate_limit_per_target": self._config.rate_limit_per_target,
            "exempt_tools": self._config.exempt_tools,
        }


# ─── Env-based Configuration ─────────────────────────────────────────────────

def _build_scope_from_env() -> ScopeConfig:
    """Build ScopeConfig from environment variables."""
    cidrs = os.environ.get("VAL_ALLOWED_CIDRS", "").strip()
    domains = os.environ.get("VAL_ALLOWED_DOMAINS", "").strip()
    rate = int(os.environ.get("VAL_TARGET_RATE_LIMIT", "30"))

    config = ScopeConfig(rate_limit_per_target=rate)

    if cidrs:
        config.allowed_cidrs.extend(
            [c.strip() for c in cidrs.split(",") if c.strip()]
        )
    if domains:
        config.allowed_domains.extend(
            [d.strip() for d in domains.split(",") if d.strip()]
        )

    return config


# ─── Singleton ────────────────────────────────────────────────────────────────

_scope: Optional[ScopeValidator] = None
_scope_lock = threading.Lock()


def get_scope() -> ScopeValidator:
    """Return the singleton ScopeValidator."""
    global _scope
    if _scope is None:
        with _scope_lock:
            if _scope is None:
                _scope = ScopeValidator()
    return _scope
