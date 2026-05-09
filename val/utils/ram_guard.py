"""
VAL RAM Guard v7 — Configurable Limits
========================================
Configurable RAM ceiling + pressure tiers + pre-load safety check.
Supports LOW_RAM_MODE for aggressive memory optimization.
"""
from __future__ import annotations
import gc
import os
from dataclasses import dataclass
from typing import Optional

try:
    import psutil; PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False

try:
    import torch; TORCH_OK = True
except ImportError:
    TORCH_OK = False

from val.utils.logger import get_logger, LogCategory
logger = get_logger('ram_guard', LogCategory.SYSTEM)

# Hard limits — configurable from environment
TOTAL_RAM_GB = 16.0
MAX_RAM_GB   = float(os.environ.get('VAL_MAX_MEMORY_GB', '14.2'))
WARN_PCT     = 90.0
SAFE_PCT     = 82.0
REJECT_PCT   = 95.0
LOW_RAM_MODE = os.environ.get('LOW_RAM_MODE', 'true').lower() in ('true', '1', 'yes')

# Resource usage targets
CPU_USAGE_TARGET = float(os.environ.get('CPU_USAGE_TARGET', '0.75'))
GPU_USAGE_TARGET = float(os.environ.get('GPU_USAGE_TARGET', '0.92'))

# Context limits (tighter in LOW_RAM_MODE)
CTX_ULTRA_LOW = 96  if LOW_RAM_MODE else 256
CTX_LOW       = 192 if LOW_RAM_MODE else 512
CTX_NORMAL    = 384 if LOW_RAM_MODE else 768

MODEL_RAM_COSTS = {
    'tinyllama': {'q4': 1.5,  'q2': 0.9},
    'phi-mini':  {'q4': 2.5,  'q2': 1.4},
    'gemma':     {'q4': 4.0,  'q2': 2.2},
    'qwen':      {'q4': 5.0,  'q2': 2.8},
    'mistral':   {'q4': 7.0,  'q2': 3.8},
}


def ram_used_gb() -> float:
    if not PSUTIL_OK: return 0.0
    try: return psutil.virtual_memory().used / (1024**3)
    except: return 0.0


def ram_pct() -> float:
    if not PSUTIL_OK: return 0.0
    try: return psutil.virtual_memory().percent
    except: return 0.0


def ram_free_gb() -> float:
    return max(0.0, MAX_RAM_GB - ram_used_gb())


def pressure_tier() -> str:
    pct = ram_pct()
    if pct >= REJECT_PCT: return 'reject'
    if pct >= WARN_PCT:   return 'ultra_low'
    if pct >= SAFE_PCT:   return 'low'
    return 'normal'


def ctx_limit() -> int:
    t = pressure_tier()
    if t == 'ultra_low': return CTX_ULTRA_LOW
    if t == 'low':       return CTX_LOW
    return CTX_NORMAL


def enforce_ctx(requested: int) -> int:
    lim = ctx_limit()
    if requested > lim:
        logger.debug(f'Token cap: {requested} -> {lim} (tier={pressure_tier()})')
        return lim
    return requested


@dataclass
class LoadDecision:
    allowed:    bool
    model:      str
    quant:      str
    reason:     str
    ram_used:   float
    ram_pct_:   float
    headroom:   float
    ctx_limit_: int


def can_load(desired_model: str, current_loaded_cost: float = 0.0) -> LoadDecision:
    """
    Constraint #1+#9: check RAM before every model load.
    Returns LoadDecision with allowed=True/False and possibly dowgraded model.
    """
    used     = ram_used_gb()
    pct      = ram_pct()
    tier     = pressure_tier()
    ctx      = ctx_limit()
    headroom = max(0.0, MAX_RAM_GB - used + current_loaded_cost)

    def ok(model, quant, reason=''):
        return LoadDecision(
            allowed=True, model=model, quant=quant, reason=reason,
            ram_used=used, ram_pct_=pct, headroom=headroom, ctx_limit_=ctx,
        )

    def deny(reason):
        return LoadDecision(
            allowed=False, model=desired_model, quant='q4', reason=reason,
            ram_used=used, ram_pct_=pct, headroom=headroom, ctx_limit_=ctx,
        )

    if tier == 'reject':
        logger.warning(f'LOAD REJECTED: RAM at {pct:.1f}% (>= {REJECT_PCT}%)')
        return deny(f'RAM critical ({pct:.1f}%) -- reject tier')

    order = ['mistral', 'gemma', 'phi-mini', 'tinyllama']
    start = order.index(desired_model) if desired_model in order else 0

    for candidate in order[start:]:
        costs = MODEL_RAM_COSTS.get(candidate, {'q4': 1.5, 'q2': 0.9})
        if tier == 'ultra_low' and candidate != 'tinyllama':
            continue
        if costs['q4'] <= headroom:
            r = '' if candidate == desired_model else f'downgraded from {desired_model}'
            return ok(candidate, 'q4', r)
        if costs['q2'] <= headroom:
            return ok(candidate, 'q2', f'Q2 fallback (headroom={headroom:.1f}GB)')

    logger.error(f'No model fits: used={used:.1f}GB headroom={headroom:.1f}GB tier={tier}')
    return deny(f'No model fits in {headroom:.1f}GB headroom')


def run_gc(passes: int = 3, label: str = '') -> float:
    before = ram_used_gb()
    for _ in range(passes):
        gc.collect()
    if TORCH_OK and torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    freed = max(0.0, before - ram_used_gb())
    if freed > 0.05:
        logger.debug(f'GC[{label or "gc"}] freed {freed:.2f}GB ({passes} passes)')
    return freed


def maybe_gc_between_requests() -> None:
    """Constraint #8: GC between requests when RAM > 90%."""
    if ram_pct() > WARN_PCT:
        logger.info(f'Inter-request GC (RAM > {WARN_PCT}%)')
        run_gc(3, 'inter-req')


@dataclass
class RamSnapshot:
    used_gb:  float
    free_gb:  float
    pct:      float
    headroom: float
    tier:     str
    ctx_lim:  int

    def as_dict(self):
        return {
            'ram_used_gb':  round(self.used_gb, 2),
            'ram_free_gb':  round(self.free_gb, 2),
            'ram_pct':      self.pct,
            'ram_headroom': round(self.headroom, 2),
            'ram_tier':     self.tier,
            'ctx_limit':    self.ctx_lim,
            'max_ram_gb':   MAX_RAM_GB,
        }


def snapshot(current_model_gb: float = 0.0) -> RamSnapshot:
    used = ram_used_gb()
    pct  = ram_pct()
    head = max(0.0, MAX_RAM_GB - used + current_model_gb)
    return RamSnapshot(
        used_gb=used, free_gb=round(MAX_RAM_GB - used, 2),
        pct=pct, headroom=head, tier=pressure_tier(), ctx_lim=ctx_limit(),
    )


def get_resource_config() -> dict:
    """Return current resource configuration for status reporting."""
    return {
        'cpu_usage_target': CPU_USAGE_TARGET,
        'gpu_usage_target': GPU_USAGE_TARGET,
        'max_ram_gb':       MAX_RAM_GB,
        'low_ram_mode':     LOW_RAM_MODE,
        'warn_pct':         WARN_PCT,
        'reject_pct':       REJECT_PCT,
        'ctx_normal':       CTX_NORMAL,
        'ctx_low':          CTX_LOW,
        'ctx_ultra_low':    CTX_ULTRA_LOW,
    }


def apply_resource_limits():
    """Apply CPU/GPU resource limits at startup."""
    try:
        import psutil
        p = psutil.Process()
        if os.name == 'nt':
            # ABOVE_NORMAL for GPU inference workloads — BELOW_NORMAL throttles GPU
            p.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
        else:
            p.nice(-5)  # Slightly elevated priority for inference
        logger.info('Process priority set for inference workloads')
    except Exception:
        pass

    try:
        import torch
        cpu_cores = os.cpu_count() or 8
        threads = max(4, int(cpu_cores * CPU_USAGE_TARGET))
        torch.set_num_threads(threads)
        torch.set_num_interop_threads(max(2, cpu_cores // 4))
        logger.info(f'Torch threads: {threads} infer + {max(2, cpu_cores // 4)} interop ({CPU_USAGE_TARGET * 100:.0f}% of {cpu_cores} cores)')

        # Enable TF32 on Ampere+ GPUs for faster matmul
        if torch.cuda.is_available():
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True
            logger.info('CUDA optimizations: TF32 + cuDNN benchmark enabled')
    except Exception:
        pass

    logger.info(
        f'Resource limits: CPU={CPU_USAGE_TARGET * 100:.0f}% GPU={GPU_USAGE_TARGET * 100:.0f}% RAM_CAP={MAX_RAM_GB:.1f}GB LOW_RAM={LOW_RAM_MODE}'
    )

