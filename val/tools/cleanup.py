"""
VAL — Cleanup Manager v13.0
Ported from PA/backend/core/cleanup_manager.py.
Safe project cleanup with protected paths, dupe detection, confirmation workflow.
"""
from __future__ import annotations
import hashlib, logging, shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from val.utils.logger import get_logger, LogCategory

logger = get_logger("cleanup", LogCategory.TOOL)

PROTECTED_DIRS = {"val","val-ui","models",".git","node_modules",".venv","venv",".env","src"}
PROTECTED_FILES = {".env",".env.example","package.json","package-lock.json","requirements.txt",
    "pyproject.toml","vite.config.js","README.md","run.bat","run.sh","main.py"}
PROTECTED_EXT = {".py",".js",".jsx",".ts",".tsx",".json",".md",".env",".toml",".yaml",".yml"}
SAFE_DIRS = {"__pycache__":"Python cache",".cache":"Build cache",".pytest_cache":"pytest cache",
    ".mypy_cache":"mypy cache",".ruff_cache":"ruff cache"}
SAFE_EXT = {".tmp",".pyc",".pyo",".bak",".swp",".DS_Store"}

@dataclass
class CleanupItem:
    path: str; size_bytes: int; reason: str; safe: bool; item_type: Literal["dir","file","duplicate"]

@dataclass
class CleanupReport:
    root: str; items: list[CleanupItem] = field(default_factory=list)
    total_bytes: int = 0; safe_bytes: int = 0; deleted: list[str] = field(default_factory=list)
    def add(self, item: CleanupItem):
        self.items.append(item); self.total_bytes += item.size_bytes
        if item.safe: self.safe_bytes += item.size_bytes
    def to_report(self) -> str:
        if not self.items: return "✅ Project is clean — no unnecessary files found."
        lines = [f"## 🧹 Cleanup Report — `{self.root}`",
            f"Found **{len(self.items)}** items · **{_fmt(self.total_bytes)}** total · **{_fmt(self.safe_bytes)}** auto-safe\n"]
        for i in [x for x in self.items if x.safe][:20]:
            lines.append(f"- ✅ `{i.path}` ({_fmt(i.size_bytes)}) — {i.reason}")
        for i in [x for x in self.items if not x.safe][:20]:
            lines.append(f"- ⚠️ `{i.path}` ({_fmt(i.size_bytes)}) — {i.reason}")
        lines.append("\n**Reply `confirm cleanup` to auto-delete safe files.**")
        return "\n".join(lines)
    def to_dict(self) -> dict:
        return {"root":self.root,"total_bytes":self.total_bytes,"safe_bytes":self.safe_bytes,
            "item_count":len(self.items),"items":[{"path":i.path,"size":i.size_bytes,
            "reason":i.reason,"safe":i.safe,"type":i.item_type} for i in self.items]}

def scan_project(root_path: str) -> CleanupReport:
    root = Path(root_path).resolve(); report = CleanupReport(root=str(root))
    seen: dict[str,str] = {}; skip = {"node_modules",".git",".venv","venv","models"}
    for path in root.rglob("*"):
        if any(s in path.parts[len(root.parts):] for s in skip): continue
        rel = str(path.relative_to(root))
        if path.is_dir():
            if path.name in SAFE_DIRS:
                report.add(CleanupItem(rel, _dsize(path), SAFE_DIRS[path.name], True, "dir"))
            continue
        if path.suffix.lower() in SAFE_EXT and path.name not in PROTECTED_FILES:
            try: report.add(CleanupItem(rel, path.stat().st_size, f"Temp ({path.suffix})", True, "file"))
            except OSError: pass
            continue
        if path.suffix.lower() in PROTECTED_EXT: continue
        try:
            sz = path.stat().st_size
            if 0 < sz < 10_000_000:
                h = _fhash(path)
                if h in seen: report.add(CleanupItem(rel, sz, f"Duplicate of `{seen[h]}`", False, "duplicate"))
                else: seen[h] = rel
            if sz > 5_000_000:
                report.add(CleanupItem(rel, sz, "Large file (>5MB)", False, "file"))
        except OSError: pass
    logger.info("[Cleanup] %d items, %s", len(report.items), _fmt(report.total_bytes))
    return report

def execute_cleanup(root_path: str, safe_only: bool = True) -> dict:
    root = Path(root_path).resolve(); report = scan_project(root_path)
    deleted, errors = [], []
    for item in report.items:
        if safe_only and not item.safe: continue
        p = root / item.path
        if not p.exists() or p.name in PROTECTED_FILES: continue
        try:
            if p.is_dir(): shutil.rmtree(p)
            else: p.unlink()
            deleted.append(item.path)
        except Exception as e: errors.append(f"{item.path}: {e}")
    return {"deleted":deleted,"errors":errors,"count":len(deleted),
        "message":f"Deleted {len(deleted)} item(s). {len(errors)} error(s)."}

def _dsize(p: Path) -> int:
    t = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                try: t += f.stat().st_size
                except: pass
    except: pass
    return t

def _fhash(p: Path) -> str:
    h = hashlib.md5()
    try:
        with open(p,"rb") as f:
            for c in iter(lambda: f.read(8192), b""): h.update(c)
    except: pass
    return h.hexdigest()

def _fmt(b: int) -> str:
    for u in ("B","KB","MB","GB"):
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"
