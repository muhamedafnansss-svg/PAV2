"""
VAL Cache System v14.1 — Multi-Layer Cache with Tool-Aware Invalidation
========================================================================
L1: Routing cache     — intent classification results (infinite TTL)
L2: Response cache    — LLM responses (short TTL, tool-aware invalidation)
L3: KV cache          — per-session KV state (managed by Governor)
L4: Vector DB         — FAISS RAG cache (placeholder for future)

Cache invalidation:
  - Scan tools ALWAYS bypass L2 cache
  - Tool results keyed by hash(tool + args + timestamp_bucket)
  - L2 TTL: 5 min for tool outputs, 30 min for LLM responses
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("val.cache")

# Tools whose results should never be cached (output changes each run)
_UNCACHEABLE_TOOLS = {
    "nmap", "ffuf", "gobuster", "sqlmap", "nikto", "subfinder", "amass",
    "hydra", "masscan", "hashcat", "burpsuite", "metasploit",
    "tcpdump", "wireshark",
}

# ─── Cache Entry ──────────────────────────────────────────────────────────────

@dataclass
class CacheEntry:
    key: str
    value: Any
    layer: str
    created_at: float
    ttl: float           # seconds, 0 = infinite
    hits: int = 0
    tool: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        if self.ttl <= 0:
            return False
        return (time.time() - self.created_at) > self.ttl


# ─── L1: Routing Cache ───────────────────────────────────────────────────────

class L1RoutingCache:
    """
    Caches routing decisions by normalized input.
    Infinite TTL — routing is deterministic (same input → same route).
    """

    def __init__(self, max_size: int = 1024):
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._max = max_size
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def _normalize(self, text: str) -> str:
        return text.strip().lower()

    def get(self, message: str) -> Optional[Any]:
        key = self._normalize(message)
        with self._lock:
            if key in self._cache:
                self._hits += 1
                self._cache.move_to_end(key)
                return self._cache[key]
            self._misses += 1
            return None

    def put(self, message: str, decision: Any) -> None:
        key = self._normalize(message)
        with self._lock:
            self._cache[key] = decision
            self._cache.move_to_end(key)
            if len(self._cache) > self._max:
                self._cache.popitem(last=False)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "layer": "L1_routing",
            "size": len(self._cache),
            "max_size": self._max,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
        }


# ─── L2: Response Cache ──────────────────────────────────────────────────────

class L2ResponseCache:
    """
    LLM response cache with TTL and tool-aware invalidation.
    Key: hash(message + model + mode) for LLM, hash(tool + args + time_bucket) for tools.
    """

    LLM_TTL = 1800.0       # 30 minutes for LLM responses
    TOOL_TTL = 300.0        # 5 minutes for tool outputs
    TIME_BUCKET = 300       # 5-minute timestamp bucketing

    def __init__(self, max_size: int = 256):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max = max_size
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def _llm_key(self, message: str, model: str, mode: str) -> str:
        raw = f"{message}|{model}|{mode}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _tool_key(self, tool: str, args: str) -> str:
        bucket = math.floor(time.time() / self.TIME_BUCKET)
        raw = f"{tool}|{args}|{bucket}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get_llm(self, message: str, model: str, mode: str) -> Optional[str]:
        key = self._llm_key(message, model, mode)
        return self._get(key)

    def put_llm(self, message: str, model: str, mode: str, response: str) -> None:
        key = self._llm_key(message, model, mode)
        entry = CacheEntry(
            key=key, value=response, layer="L2_llm",
            created_at=time.time(), ttl=self.LLM_TTL,
        )
        self._put(key, entry)

    def get_tool(self, tool: str, args: str) -> Optional[str]:
        if tool in _UNCACHEABLE_TOOLS:
            return None
        key = self._tool_key(tool, args)
        return self._get(key)

    def put_tool(self, tool: str, args: str, output: str) -> None:
        if tool in _UNCACHEABLE_TOOLS:
            return
        key = self._tool_key(tool, args)
        entry = CacheEntry(
            key=key, value=output, layer="L2_tool",
            created_at=time.time(), ttl=self.TOOL_TTL, tool=tool,
        )
        self._put(key, entry)

    def invalidate_tool(self, tool: str) -> int:
        """Invalidate all cached results for a specific tool."""
        removed = 0
        with self._lock:
            keys_to_remove = [
                k for k, v in self._cache.items()
                if v.tool == tool
            ]
            for k in keys_to_remove:
                del self._cache[k]
                removed += 1
        if removed:
            logger.info("[Cache] Invalidated %d entries for tool '%s'", removed, tool)
        return removed

    def _get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired:
                del self._cache[key]
                self._misses += 1
                return None
            entry.hits += 1
            self._hits += 1
            self._cache.move_to_end(key)
            return entry.value

    def _put(self, key: str, entry: CacheEntry) -> None:
        with self._lock:
            self._cache[key] = entry
            self._cache.move_to_end(key)
            # Evict expired + overflow
            self._evict_expired()
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)

    def _evict_expired(self) -> None:
        expired = [k for k, v in self._cache.items() if v.is_expired]
        for k in expired:
            del self._cache[k]

    def stats(self) -> dict:
        total = self._hits + self._misses
        with self._lock:
            size = len(self._cache)
        return {
            "layer": "L2_response",
            "size": size,
            "max_size": self._max,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
            "llm_ttl_s": self.LLM_TTL,
            "tool_ttl_s": self.TOOL_TTL,
        }


# ─── Unified Cache System ────────────────────────────────────────────────────

class CacheSystem:
    """
    Unified 4-layer cache interface.
    L3 (KV cache) and L4 (Vector DB) are managed externally.
    """

    def __init__(self):
        self.l1 = L1RoutingCache(max_size=1024)
        self.l2 = L2ResponseCache(max_size=256)
        self._l3_stats = {"layer": "L3_kv", "note": "managed by Governor"}
        self._l4_stats = {"layer": "L4_vector", "note": "placeholder for FAISS/ChromaDB"}
        logger.info("[Cache] System initialized — L1(1024) + L2(256)")

    def stats(self) -> dict:
        l1 = self.l1.stats()
        l2 = self.l2.stats()
        total_hits = l1["hits"] + l2["hits"]
        total_misses = l1["misses"] + l2["misses"]
        total = total_hits + total_misses
        return {
            "layers": {
                "L1": l1,
                "L2": l2,
                "L3": self._l3_stats,
                "L4": self._l4_stats,
            },
            "aggregate": {
                "total_hits": total_hits,
                "total_misses": total_misses,
                "overall_hit_rate": round(total_hits / total, 3) if total else 0.0,
            },
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_cache: Optional[CacheSystem] = None
_cache_lock = threading.Lock()


def get_cache() -> CacheSystem:
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = CacheSystem()
    return _cache
