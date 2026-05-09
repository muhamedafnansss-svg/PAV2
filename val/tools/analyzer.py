"""
VAL — System Analyzer v13.0
Ported from PA/backend/core/system_analyzer.py + hardened for VAL architecture.

Provides:
  - AST-based Python syntax checking
  - 13-pattern vulnerability scanner (eval, secrets, injection, etc.)
  - Import chain validation
  - Log exception parsing
  - Structured severity-ranked findings

Usage:
  from val.tools.analyzer import analyze_project, analyze_file
  result = analyze_project("/path/to/project")
  print(result.to_text())
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from val.utils.logger import get_logger, LogCategory

logger = get_logger("analyzer", LogCategory.TOOL)

# ── Vulnerability / insecurity patterns ───────────────────────────────────────
VULN_PATTERNS: list[tuple[str, str, str]] = [
    (r"subprocess\.(call|run|Popen)\([^)]*shell\s*=\s*True",  "HIGH",     "subprocess with shell=True (code injection risk)"),
    (r"os\.system\(",                                          "HIGH",     "os.system() — use subprocess with allowlist"),
    (r"eval\(|exec\(",                                         "CRITICAL", "eval()/exec() — arbitrary code execution"),
    (r"(password|secret|api_key|token)\s*=\s*['\"][^'\"]{4,}", "HIGH",     "Hardcoded secret/password detected"),
    (r"open\(.*,\s*['\"]w['\"]",                               "MEDIUM",   "Unrestricted file write"),
    (r"pickle\.load|pickle\.loads",                            "HIGH",     "Unsafe deserialization (pickle)"),
    (r"yaml\.load\([^)]*Loader",                               "MEDIUM",   "yaml.load without SafeLoader"),
    (r"import \*",                                             "LOW",      "Wildcard import — namespace pollution"),
    (r"random\.(random|randint|choice)\(",                     "LOW",      "Use secrets module for security-sensitive RNG"),
    (r"md5|sha1\b",                                            "MEDIUM",   "Weak hash algorithm (MD5/SHA1)"),
    (r"#\s*(TODO|FIXME|HACK|XXX)",                             "INFO",     "Code smell annotation"),
    (r"DEBUG\s*=\s*True",                                      "MEDIUM",   "Debug mode enabled in code"),
    (r"allow_origins\s*=\s*\[\s*['\"]?\*",                     "HIGH",     "Wildcard CORS — all origins allowed"),
]


@dataclass
class Finding:
    file:        str
    line:        int
    severity:    Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    category:    Literal["syntax", "import", "security", "runtime", "style"]
    description: str
    snippet:     str = ""
    suggestion:  str = ""


@dataclass
class AnalysisResult:
    target:        str
    findings:      list[Finding] = field(default_factory=list)
    error_count:   int = 0
    warning_count: int = 0
    files_scanned: int = 0
    log_errors:    list[str] = field(default_factory=list)

    def add(self, f: Finding):
        self.findings.append(f)
        if f.severity in ("CRITICAL", "HIGH"):
            self.error_count += 1
        else:
            self.warning_count += 1

    def to_text(self) -> str:
        if not self.findings and not self.log_errors:
            return f"✅ No issues found in {self.files_scanned} file(s) scanned."
        lines = [
            f"## Analysis Report — {self.target}",
            f"📁 Files scanned: {self.files_scanned} | "
            f"🔴 Errors: {self.error_count} | ⚠️ Warnings: {self.warning_count}",
        ]
        sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
        sorted_f = sorted(self.findings, key=lambda x: sev_order.get(x.severity, 5))
        for f in sorted_f[:25]:
            icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡",
                    "LOW": "🟢", "INFO": "ℹ️"}.get(f.severity, "❓")
            lines.append(f"\n{icon} **{f.severity}** `{f.file}:{f.line}` — {f.description}")
            if f.snippet:
                lines.append(f"   ```\n   {f.snippet[:120]}\n   ```")
            if f.suggestion:
                lines.append(f"   💡 *{f.suggestion}*")
        if self.log_errors:
            lines.append("\n### Log Exceptions")
            for e in self.log_errors[:10]:
                lines.append(f"- `{e[:150]}`")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "target":        self.target,
            "files_scanned": self.files_scanned,
            "error_count":   self.error_count,
            "warning_count": self.warning_count,
            "findings": [
                {
                    "file": f.file, "line": f.line, "severity": f.severity,
                    "category": f.category, "description": f.description,
                    "snippet": f.snippet, "suggestion": f.suggestion,
                }
                for f in self.findings
            ],
            "log_errors": self.log_errors,
        }


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_project(root_path: str, log_file: str = "") -> AnalysisResult:
    """
    Scan a project directory for Python code issues.
    Returns a structured AnalysisResult with severity-ranked findings.
    """
    root = Path(root_path).resolve()
    result = AnalysisResult(target=str(root))

    skip = {"__pycache__", ".venv", "venv", "site-packages", "node_modules",
            ".git", "dist", "build", ".pytest_cache"}

    py_files = [
        f for f in root.rglob("*.py")
        if not any(s in f.parts for s in skip)
    ]
    result.files_scanned = len(py_files)

    for fpath in py_files:
        try:
            code = fpath.read_text(encoding="utf-8", errors="replace")
            rel = str(fpath.relative_to(root))
        except Exception:
            continue
        _check_syntax(code, rel, result)
        _check_imports(code, rel, result)
        _check_security(code, rel, result)

    # Parse log file for exceptions
    if log_file:
        _parse_log(Path(log_file), result)
    else:
        for candidate in [root / "app.log", root / "val.log"]:
            if candidate.exists():
                _parse_log(candidate, result)
                break

    logger.info("[Analyzer] Scanned %d files, %d findings",
                result.files_scanned, len(result.findings))
    return result


def analyze_file(file_path: str) -> AnalysisResult:
    """Analyze a single Python file."""
    path = Path(file_path)
    result = AnalysisResult(target=str(path))
    if not path.exists() or path.suffix != ".py":
        return result
    result.files_scanned = 1
    try:
        code = path.read_text(encoding="utf-8", errors="replace")
        rel = path.name
    except Exception:
        return result
    _check_syntax(code, rel, result)
    _check_imports(code, rel, result)
    _check_security(code, rel, result)
    return result


# ── Internal checks ───────────────────────────────────────────────────────────

def _check_syntax(code: str, rel: str, result: AnalysisResult):
    try:
        ast.parse(code)
    except SyntaxError as e:
        result.add(Finding(
            file=rel, line=e.lineno or 0,
            severity="HIGH", category="syntax",
            description=f"SyntaxError: {e.msg}",
            snippet=(e.text or "").strip(),
            suggestion="Fix the syntax error.",
        ))


def _check_imports(code: str, rel: str, result: AnalysisResult):
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else ([node.module] if node.module else [])
                )
                for mod in mods:
                    if mod and not _is_stdlib(mod) and not _check_importable(mod):
                        result.add(Finding(
                            file=rel, line=node.lineno,
                            severity="MEDIUM", category="import",
                            description=f"Possibly missing: `{mod}` (not importable)",
                            suggestion=f"Run: pip install {mod.split('.')[0]}",
                        ))
    except Exception:
        pass


def _check_security(code: str, rel: str, result: AnalysisResult):
    for line_no, line_text in enumerate(code.splitlines(), 1):
        for pattern, sev, desc in VULN_PATTERNS:
            if re.search(pattern, line_text, re.IGNORECASE):
                result.add(Finding(
                    file=rel, line=line_no,
                    severity=sev, category="security",
                    description=desc,
                    snippet=line_text.strip()[:120],
                    suggestion=_suggest_fix(desc),
                ))


def _parse_log(log_path: Path, result: AnalysisResult):
    if not log_path.exists():
        return
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"(ERROR|CRITICAL|Exception|Traceback).*", text):
            result.log_errors.append(m.group(0)[:200])
        result.log_errors = result.log_errors[-15:]
    except Exception:
        pass


def _is_stdlib(module: str) -> bool:
    top = module.split(".")[0]
    if hasattr(sys, "stdlib_module_names"):
        return top in sys.stdlib_module_names
    return top in {
        "os", "sys", "re", "json", "time", "math", "io", "abc", "ast",
        "asyncio", "collections", "contextlib", "copy", "dataclasses",
        "datetime", "enum", "functools", "gc", "hashlib", "html", "http",
        "importlib", "inspect", "itertools", "logging", "pathlib",
        "platform", "queue", "random", "shutil", "signal", "socket",
        "sqlite3", "ssl", "string", "struct", "subprocess", "tempfile",
        "textwrap", "threading", "traceback", "types", "typing",
        "unittest", "urllib", "uuid", "warnings", "weakref",
    }


def _check_importable(module: str) -> bool:
    top = module.split(".")[0]
    return importlib.util.find_spec(top) is not None


def _suggest_fix(desc: str) -> str:
    fixes = {
        "shell=True":       "Use subprocess.run(['cmd', 'arg']) without shell=True",
        "os.system":        "Use subprocess.run([...], check=True, timeout=30)",
        "eval()/exec()":    "Use ast.literal_eval() or explicit parsing",
        "Hardcoded secret": "Move to .env and read via os.environ.get()",
        "pickle":           "Use json.dumps/loads for safe serialization",
        "yaml.load":        "Use yaml.safe_load() instead",
        "MD5/SHA1":         "Use hashlib.sha256() or better",
        "Wildcard CORS":    "Lock CORS to explicit localhost origins",
    }
    for key, fix in fixes.items():
        if key.lower() in desc.lower():
            return fix
    return "Review and refactor this pattern for safety."
