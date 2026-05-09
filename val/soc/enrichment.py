"""
VAL SOC Enrichment Engine v14.1 — Background Data Enrichment
==============================================================
Async enrichment for IOCs: WHOIS, DNS, reverse DNS, GeoIP.
Runs in background thread pool, results fed back via event bus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("val.soc.enrichment")


@dataclass
class EnrichmentResult:
    target: str
    enrichment_type: str
    data: Dict[str, Any]
    duration_ms: float
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "type": self.enrichment_type,
            "data": self.data,
            "duration_ms": round(self.duration_ms, 1),
            "success": self.success,
            "error": self.error,
        }


class EnrichmentEngine:
    """Background data enrichment for IOCs."""

    def __init__(self):
        self._cache: Dict[str, EnrichmentResult] = {}

    async def enrich_all(self, target: str) -> List[EnrichmentResult]:
        """Run all applicable enrichments for a target."""
        results = []
        tasks = [
            self.dns_resolve(target),
            self.reverse_dns(target),
        ]

        # WHOIS only for domains
        if not self._is_ip(target):
            tasks.append(self.whois_lookup(target))

        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for r in gathered:
            if isinstance(r, EnrichmentResult):
                results.append(r)
            elif isinstance(r, Exception):
                logger.debug("[Enrichment] Error: %s", r)

        return results

    async def dns_resolve(self, domain: str) -> EnrichmentResult:
        """Resolve domain to IP addresses."""
        t0 = time.time()
        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: socket.getaddrinfo(domain, None)),
                timeout=5.0,
            )
            ips = list(set(r[4][0] for r in result))
            return EnrichmentResult(
                target=domain, enrichment_type="dns",
                data={"ips": ips, "count": len(ips)},
                duration_ms=(time.time() - t0) * 1000,
                success=True,
            )
        except Exception as e:
            return EnrichmentResult(
                target=domain, enrichment_type="dns",
                data={}, duration_ms=(time.time() - t0) * 1000,
                success=False, error=str(e),
            )

    async def reverse_dns(self, ip: str) -> EnrichmentResult:
        """Reverse DNS lookup for an IP."""
        t0 = time.time()
        try:
            loop = asyncio.get_running_loop()
            hostname = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: socket.gethostbyaddr(ip)),
                timeout=5.0,
            )
            return EnrichmentResult(
                target=ip, enrichment_type="reverse_dns",
                data={"hostname": hostname[0], "aliases": hostname[1]},
                duration_ms=(time.time() - t0) * 1000,
                success=True,
            )
        except Exception as e:
            return EnrichmentResult(
                target=ip, enrichment_type="reverse_dns",
                data={}, duration_ms=(time.time() - t0) * 1000,
                success=False, error=str(e),
            )

    async def whois_lookup(self, domain: str) -> EnrichmentResult:
        """WHOIS lookup for a domain (uses python-whois if available)."""
        t0 = time.time()
        try:
            import subprocess
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["whois", domain],
                        capture_output=True, text=True, timeout=10,
                    )
                ),
                timeout=15.0,
            )
            output = result.stdout[:2000] if result.returncode == 0 else result.stderr[:500]
            return EnrichmentResult(
                target=domain, enrichment_type="whois",
                data={"raw": output, "available": result.returncode == 0},
                duration_ms=(time.time() - t0) * 1000,
                success=result.returncode == 0,
                error=result.stderr[:200] if result.returncode != 0 else None,
            )
        except Exception as e:
            return EnrichmentResult(
                target=domain, enrichment_type="whois",
                data={}, duration_ms=(time.time() - t0) * 1000,
                success=False, error=str(e),
            )

    def _is_ip(self, target: str) -> bool:
        try:
            socket.inet_aton(target)
            return True
        except socket.error:
            return False


# ─── Singleton ────────────────────────────────────────────────────────────────

_enrichment: Optional[EnrichmentEngine] = None


def get_enrichment() -> EnrichmentEngine:
    global _enrichment
    if _enrichment is None:
        _enrichment = EnrichmentEngine()
    return _enrichment
