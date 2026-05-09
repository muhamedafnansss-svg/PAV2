"""
VAL Memory Budget Engine
=========================
Single source of truth for memory budgeting and model-slot decisions.

Budget:
  Total installed RAM: 16 GB
  OS reserve:           2 GB
  Node/browser:         1.5 GB
  Usable for models:   ~12.5 GB   (capped at USABLE_RAM_GB)

Model RAM costs (loaded weight, 4-bit where available):
  tinyllama : 1.5 GB   → ultra_light mode
  gemma     : 4.0 GB   → balanced   mode
  mistral   : 7.0 GB   → full       mode

Execution modes:
  ultra_light  → tinyllama, max 256 tokens, no history
  light        → tinyllama, max 384 tokens, 2-turn history
  balanced     → gemma,     max 512 tokens, 4-turn history
  full         → mistral,   max 1024 tokens, 6-turn history

The engine:
  1. Reads live RAM usage via psutil
  2. Computes headroom = USABLE_RAM_GB − used_ram − current_model_cost
  3. Selects the heaviest model that fits in headroom
  4. If nothing fits → returns None  (caller returns graceful error)
"""

import gc
import time
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

try:
    import torch
    TORCH_OK = True
except ImportError:
    TORCH_OK = False

from val.utils.logger import get_logger, LogCategory

logger = get_logger("memory_budget", LogCategory.SYSTEM)

# ─── Budget constants ─────────────────────────────────────────────────────────

TOTAL_RAM_GB   = 16.0    # physical RAM
OS_RESERVE_GB  =  2.0    # OS + system services
NODE_RESERVE_GB =  1.5   # Node.js frontend + browser
USABLE_RAM_GB  = TOTAL_RAM_GB - OS_RESERVE_GB - NODE_RESERVE_GB   # 12.5 GB

# Safety headroom — never fill usable_ram entirely
SAFETY_BUFFER_GB = 1.0   # keep 1 GB free at all times

EFFECTIVE_BUDGET = USABLE_RAM_GB - SAFETY_BUFFER_GB   # 11.5 GB


# ─── Model cost table ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelSpec:
    name:        str
    ram_cost_gb: float    # RAM required to load (4-bit quantized where possible)
    max_tokens:  int      # hard token cap for this mode
    max_history: int      # context turns kept
    mode:        str      # execution mode label


MODEL_SPECS = [
    # Heaviest to lightest — we pick the heaviest that fits
    ModelSpec("mistral",   7.0, 1024, 6,  "full"),
    ModelSpec("gemma",     4.0,  512, 4,  "balanced"),
    ModelSpec("tinyllama", 1.5,  384, 2,  "light"),
    ModelSpec("tinyllama", 1.5,  256, 0,  "ultra_light"),
]

# Unique model names (for cache keys)
KNOWN_MODELS = ["mistral", "gemma", "tinyllama"]


def get_spec_for_mode(mode: str) -> Optional[ModelSpec]:
    for s in MODEL_SPECS:
        if s.mode == mode:
            return s
    return None


# ─── RAM measurement ──────────────────────────────────────────────────────────

def get_system_ram_used_gb() -> float:
    """System-wide RAM in use (GB). Fallback 0 if psutil missing."""
    if not PSUTIL_OK:
        return 0.0
    try:
        vm = psutil.virtual_memory()
        return round(vm.used / (1024 ** 3), 2)
    except Exception:
        return 0.0


def get_free_headroom_gb(current_model_cost: float = 0.0) -> float:
    """
    Effective free headroom for loading a NEW model.
    Subtracts the currently-loaded model cost so we don't double-count.
    """
    used = get_system_ram_used_gb()
    # headroom = budget − already_used_by_system − current_model_already_in_budget
    headroom = EFFECTIVE_BUDGET - used + current_model_cost
    return max(0.0, headroom)


def get_ram_pct() -> float:
    """Percent of TOTAL system RAM used (0-100)."""
    if not PSUTIL_OK:
        return 0.0
    try:
        return round(psutil.virtual_memory().percent, 1)
    except Exception:
        return 0.0


# ─── Model selection ──────────────────────────────────────────────────────────

def select_best_model(
    current_model_cost: float = 0.0,
    force_model: Optional[str] = None,
    mistral_enabled: bool = True,
) -> Optional["ModelSpec"]:
    """
    Select the heaviest model that fits within available RAM headroom.

    Args:
        current_model_cost: Cost (GB) of currently-loaded model (so we don't
                            penalise switching to a lighter model).
        force_model:        If set, try this model first, fall back lighter.
        mistral_enabled:    If False, skip Mistral entirely.

    Returns:
        ModelSpec of best fitting model, or None if nothing fits.
    """
    headroom = get_free_headroom_gb(current_model_cost)
    used_gb  = get_system_ram_used_gb()

    logger.debug(
        f"MemBudget: used={used_gb:.1f}GB headroom={headroom:.1f}GB",
        extra={"used_gb": used_gb, "headroom": headroom, "force": force_model}
    )

    candidates = [s for s in MODEL_SPECS if s.name in KNOWN_MODELS]

    if not mistral_enabled:
        candidates = [s for s in candidates if s.name != "mistral"]

    # If forced, reorder so forced model is tried first
    if force_model and force_model in KNOWN_MODELS:
        ordered = (
            [s for s in candidates if s.name == force_model] +
            [s for s in candidates if s.name != force_model]
        )
    else:
        ordered = candidates  # already heaviest-first

    for spec in ordered:
        if spec.ram_cost_gb <= headroom:
            logger.info(
                f"Selected model: {spec.name} ({spec.mode}) — "
                f"cost={spec.ram_cost_gb}GB headroom={headroom:.1f}GB",
                extra={"model": spec.name, "mode": spec.mode}
            )
            return spec

    logger.error(
        f"NO model fits: headroom={headroom:.1f}GB, smallest=1.5GB",
        extra={"used_gb": used_gb, "headroom": headroom}
    )
    return None   # graceful: caller will return overload message


# ─── Aggressive GC ────────────────────────────────────────────────────────────

def run_gc(passes: int = 3, label: str = "") -> float:
    """Multi-pass GC + VRAM flush. Returns GB freed."""
    before = get_system_ram_used_gb()
    for _ in range(passes):
        gc.collect()
        if TORCH_OK and torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    after = get_system_ram_used_gb()
    freed = max(0.0, before - after)
    if freed > 0.05:
        logger.debug(f"GC{f'[{label}]' if label else ''}: freed {freed:.2f}GB")
    return freed


# ─── Snapshot ─────────────────────────────────────────────────────────────────

@dataclass
class MemorySnapshot:
    used_gb:       float
    free_gb:       float
    pct:           float
    headroom_gb:   float
    budget_gb:     float  = EFFECTIVE_BUDGET
    usable_gb:     float  = USABLE_RAM_GB

    def as_dict(self) -> dict:
        return {
            "used_gb":     round(self.used_gb, 2),
            "free_gb":     round(self.free_gb, 2),
            "pct":         self.pct,
            "headroom_gb": round(self.headroom_gb, 2),
            "budget_gb":   self.budget_gb,
            "usable_gb":   self.usable_gb,
        }


def snapshot(current_model_cost: float = 0.0) -> MemorySnapshot:
    used = get_system_ram_used_gb()
    pct  = get_ram_pct()
    free = round(TOTAL_RAM_GB - used, 2)
    head = get_free_headroom_gb(current_model_cost)
    return MemorySnapshot(used_gb=used, free_gb=free, pct=pct, headroom_gb=head)
