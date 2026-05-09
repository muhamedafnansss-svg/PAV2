"""
VAL Tool Execution Framework
=============================
Secure, schema-validated, sandboxed tool loader.
Inspired by Claude Code's StreamingToolExecutor and tool security model.

Architecture:
  - ToolSchema: validates tool inputs before execution
  - BaseTool: abstract base all tools implement
  - ToolRegistry: dynamic loader + security gate
  - Built-in tools: filesystem, system info, log reader, calculator
"""

import os
import re
import json
import time
import platform
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from val.utils.logger import get_logger, LogCategory
from val.security.sandbox import (
    validate_file_path,
    validate_shell_command,
    validate_network_access,
    PermissionDeniedError,
    SandboxViolationError,
)
from val.config.settings import get_config, VAL_ROOT

logger = get_logger("tools", LogCategory.SYSTEM)


# ─── Tool Schema ──────────────────────────────────────────────────────────────

class ToolSchema:
    """Validates tool arguments against a declared schema."""

    def __init__(self, name: str, description: str, parameters: Dict[str, dict]):
        self.name = name
        self.description = description
        self.parameters = parameters  # {param_name: {type, required, description}}

    def validate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and coerce args. Raises ValueError on invalid input."""
        validated = {}
        for param_name, spec in self.parameters.items():
            required = spec.get("required", False)
            param_type = spec.get("type", "string")
            value = args.get(param_name)

            if value is None:
                if required:
                    raise ValueError(f"Tool '{self.name}': required parameter '{param_name}' missing.")
                continue

            # Type coercion
            if param_type == "string":
                validated[param_name] = str(value)
            elif param_type == "integer":
                validated[param_name] = int(value)
            elif param_type == "boolean":
                validated[param_name] = bool(value)
            elif param_type == "number":
                validated[param_name] = float(value)
            else:
                validated[param_name] = value

        return validated

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


# ─── Base Tool ────────────────────────────────────────────────────────────────

class BaseTool(ABC):
    """Abstract base class for all VAL tools."""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """Return the tool's schema."""
        ...

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Execute the tool with validated arguments. Returns string result."""
        ...

    def __call__(self, **kwargs) -> str:
        """Validates args via schema, then executes."""
        try:
            validated = self.schema.validate(kwargs)
            result = self.execute(**validated)
            logger.info(f"Tool '{self.schema.name}' executed successfully")
            return result
        except (ValueError, PermissionDeniedError, SandboxViolationError) as e:
            logger.security(f"Tool '{self.schema.name}' denied: {e}")
            raise
        except Exception as e:
            logger.error(f"Tool '{self.schema.name}' error: {e}", exc_info=True)
            raise


# ─── Built-in Tools ───────────────────────────────────────────────────────────

class ReadFileTool(BaseTool):
    """Safely read a file within the allowed directory."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="read_file",
            description="Read the contents of a file. Path must be within the workspace.",
            parameters={
                "path": {
                    "type": "string",
                    "required": True,
                    "description": "Absolute or relative path to the file to read",
                },
                "max_lines": {
                    "type": "integer",
                    "required": False,
                    "description": "Maximum number of lines to return (default: 100)",
                },
            },
        )

    def execute(self, path: str, max_lines: int = 100) -> str:
        file_path = validate_file_path(Path(path), operation="read")
        if not file_path.exists():
            return f"[ERROR] File not found: {path}"
        if not file_path.is_file():
            return f"[ERROR] Not a file: {path}"

        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            lines = lines[:max_lines]
            result = "\n".join(lines)
            if total > max_lines:
                result += f"\n... [{total - max_lines} more lines not shown]"
            return f"[FILE: {path}]\n{result}"
        except Exception as e:
            return f"[ERROR] Cannot read file: {e}"


class WriteFileTool(BaseTool):
    """Write content to a file (within allowed directory)."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="write_file",
            description="Write content to a file within the workspace.",
            parameters={
                "path": {"type": "string", "required": True, "description": "Path to write"},
                "content": {"type": "string", "required": True, "description": "Content to write"},
                "append": {"type": "boolean", "required": False, "description": "Append to file (default: false)"},
            },
        )

    def execute(self, path: str, content: str, append: bool = False) -> str:
        file_path = validate_file_path(Path(path), operation="write")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        try:
            with open(file_path, mode, encoding="utf-8") as f:
                f.write(content)
            action = "Appended to" if append else "Wrote"
            return f"[OK] {action} {file_path} ({len(content)} chars)"
        except Exception as e:
            return f"[ERROR] Write failed: {e}"


class ListDirTool(BaseTool):
    """List directory contents."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="list_dir",
            description="List files and directories in a given path.",
            parameters={
                "path": {"type": "string", "required": False, "description": "Directory path (default: workspace root)"},
            },
        )

    def execute(self, path: str = ".") -> str:
        dir_path = validate_file_path(Path(path), operation="read")
        if not dir_path.exists():
            return f"[ERROR] Directory not found: {path}"
        if not dir_path.is_dir():
            return f"[ERROR] Not a directory: {path}"

        entries = []
        try:
            for entry in sorted(dir_path.iterdir()):
                icon = "D" if entry.is_dir() else "F"
                size = entry.stat().st_size if entry.is_file() else "-"
                entries.append(f"  [{icon}] {entry.name} ({size})")
            return f"[DIR: {path}]\n" + "\n".join(entries[:100])
        except Exception as e:
            return f"[ERROR] Cannot list directory: {e}"


class SystemInfoTool(BaseTool):
    """Return system information."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="system_info",
            description="Get basic system information: OS, Python version, CPU, memory.",
            parameters={},
        )

    def execute(self) -> str:
        import sys
        info = {
            "os": platform.system(),
            "os_version": platform.version()[:50],
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "cwd": str(Path.cwd()),
        }
        try:
            import psutil
            mem = psutil.virtual_memory()
            info["memory_gb"] = round(mem.total / 1e9, 1)
            info["memory_used_pct"] = mem.percent
            info["cpu_count"] = psutil.cpu_count()
            info["cpu_pct"] = psutil.cpu_percent(interval=0.5)
        except ImportError:
            info["note"] = "Install psutil for memory/CPU stats"
        return json.dumps(info, indent=2)


class LogReaderTool(BaseTool):
    """Read VAL system logs."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="read_logs",
            description="Read VAL system logs. Category: system|agent|errors|security|inference",
            parameters={
                "category": {
                    "type": "string",
                    "required": False,
                    "description": "Log category (default: system)",
                },
                "tail": {
                    "type": "integer",
                    "required": False,
                    "description": "Number of lines from end (default: 50)",
                },
            },
        )

    def execute(self, category: str = "system", tail: int = 50) -> str:
        from val.config.settings import LOGS_DIR
        valid_categories = ["system", "agent", "errors", "security", "inference"]
        if category not in valid_categories:
            return f"[ERROR] Invalid category '{category}'. Valid: {valid_categories}"

        log_path = LOGS_DIR / f"{category}.jsonl"
        if not log_path.exists():
            return f"[LOG:{category}] No log file yet."

        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
            lines = lines[-tail:]
            return f"[LOG:{category}] Last {len(lines)} entries:\n" + "\n".join(lines)
        except Exception as e:
            return f"[ERROR] Cannot read log: {e}"


class CalculatorTool(BaseTool):
    """Safe arithmetic calculator."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="calculate",
            description="Evaluate a safe arithmetic expression.",
            parameters={
                "expression": {
                    "type": "string",
                    "required": True,
                    "description": "Arithmetic expression, e.g. '(2 + 3) * 4'",
                },
            },
        )

    def execute(self, expression: str) -> str:
        # Only allow safe arithmetic characters
        if not re.match(r'^[\d\s\+\-\*\/\.\(\)\%]+$', expression):
            return f"[ERROR] Expression contains invalid characters: {expression[:50]}"
        try:
            import ast
            import operator
            _OPS = {
                ast.Add: operator.add, ast.Sub: operator.sub,
                ast.Mult: operator.mul, ast.Div: operator.truediv,
                ast.Mod: operator.mod, ast.Pow: operator.pow,
                ast.USub: operator.neg, ast.UAdd: operator.pos,
            }
            def _safe_eval(node):
                if isinstance(node, ast.Expression):
                    return _safe_eval(node.body)
                elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                    return node.value
                elif isinstance(node, ast.BinOp) and type(node.op) in _OPS:
                    return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
                elif isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
                    return _OPS[type(node.op)](_safe_eval(node.operand))
                else:
                    raise ValueError(f"Unsupported operation: {ast.dump(node)}")
            tree = ast.parse(expression.strip(), mode='eval')
            result = _safe_eval(tree)
            return f"{expression} = {result}"
        except Exception as e:
            return f"[ERROR] Calculation failed: {e}"


class ValStatusTool(BaseTool):
    """Return VAL runtime status."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="val_status",
            description="Get current VAL system status: models, metrics, tasks.",
            parameters={},
        )

    def execute(self) -> str:
        info = {}
        try:
            from val.models.governor import get_governor
            g = get_governor()
            info["model"] = g.active_model_name
            info["model_loaded"] = g.is_loaded
            info["device"] = g.device
            info.update(g.status())
        except Exception as e:
            info["error"] = str(e)
        try:
            import psutil
            mem = psutil.virtual_memory()
            info["ram_pct"] = round(mem.percent, 1)
            info["ram_used_gb"] = round(mem.used / 1e9, 2)
            info["cpu_pct"] = round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            pass
        return json.dumps(info, indent=2, default=str)


# ─── Code Analyzer Tool (from PA/backend/core/system_analyzer.py) ─────────────

class CodeAnalyzerTool(BaseTool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="analyze_code",
            description="Scan a project directory for Python code issues, vulnerabilities, and bugs.",
            parameters={"path": {"type": "string", "required": False,
                "description": "Project path to scan (defaults to VAL root)"}},
        )

    def execute(self, path: str = "") -> str:
        try:
            from val.tools.analyzer import analyze_project
            target = path or str(VAL_ROOT)
            result = analyze_project(target)
            return result.to_text()
        except Exception as e:
            return f"Analysis error: {e}"


# ─── Cleanup Scan Tool (from PA/backend/core/cleanup_manager.py) ──────────────

class CleanupScanTool(BaseTool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="cleanup_scan",
            description="Scan project for temp files, caches, and duplicates that can be cleaned.",
            parameters={"path": {"type": "string", "required": False,
                "description": "Project path to scan (defaults to VAL root)"}},
        )

    def execute(self, path: str = "") -> str:
        try:
            from val.tools.cleanup import scan_project
            target = path or str(VAL_ROOT)
            report = scan_project(target)
            return report.to_report()
        except Exception as e:
            return f"Cleanup scan error: {e}"


# ─── Wiki Search Tool (from PA/backend/wiki/) ────────────────────────────────

class WikiSearchTool(BaseTool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="wiki_search",
            description="Search Wikipedia for information on a topic.",
            parameters={"query": {"type": "string", "required": True,
                "description": "Topic to search for"}},
        )

    def execute(self, query: str = "") -> str:
        if not query.strip():
            return "Please provide a search query."
        try:
            from val.tools.wiki import wiki_fetch
            return wiki_fetch(query.strip())
        except Exception as e:
            return f"Wikipedia search error: {e}"


# ─── Process Monitor Tool (from PA/backend/tools/extra_tools.py) ──────────────

class ProcessMonitorTool(BaseTool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="list_processes",
            description="List top 15 running processes sorted by CPU usage.",
            parameters={},
        )

    def execute(self) -> str:
        try:
            import psutil
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    procs.append(p.info)
                except Exception:
                    pass
            top = sorted(procs, key=lambda x: x.get("cpu_percent", 0), reverse=True)[:15]
            lines = [
                f"PID {p['pid']:6} | CPU {p['cpu_percent']:5.1f}% | "
                f"MEM {p['memory_percent']:4.1f}% | {p['name']}"
                for p in top
            ]
            return "\n".join(lines) or "No processes found."
        except Exception as e:
            return f"Process list error: {e}"


# ─── Tool Registry ────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    Dynamic tool registry with schema validation and sandboxed execution.
    All tool calls pass through security validation before execution.
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._load_builtins()

    def _load_builtins(self) -> None:
        """Register all built-in tools."""
        builtins = [
            ReadFileTool(),
            WriteFileTool(),
            ListDirTool(),
            SystemInfoTool(),
            LogReaderTool(),
            CalculatorTool(),
            ValStatusTool(),
            CodeAnalyzerTool(),
            CleanupScanTool(),
            WikiSearchTool(),
            ProcessMonitorTool(),
        ]
        for tool in builtins:
            self.register(tool)
        logger.info(f"Loaded {len(builtins)} built-in tools")

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        name = tool.schema.name
        self._tools[name] = tool
        from val.state.store import get_state
        get_state().register_tool(name, tool.schema.to_dict())
        logger.debug(f"Tool registered: {name}")

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def execute(self, name: str, args: Dict[str, Any]) -> str:
        """Execute a tool by name with given args."""
        tool = self._tools.get(name)
        if tool is None:
            return f"[ERROR] Unknown tool: '{name}'"
        return tool(**args)

    def list_tools(self) -> List[dict]:
        return [t.schema.to_dict() for t in self._tools.values()]

    def get_callable(self, name: str) -> Optional[Callable]:
        """Return a simple callable wrapper for a tool (for ValEngine registration)."""
        tool = self._tools.get(name)
        if tool is None:
            return None
        return lambda **kwargs: tool(**kwargs)

    def register_all_with_engine(self, engine) -> None:
        """Register all tools with a ValEngine instance."""
        for name, tool in self._tools.items():
            engine.register_tool(name, lambda t=tool, **kw: t(**kw))


# ─── Singleton ────────────────────────────────────────────────────────────────

_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Return the singleton ToolRegistry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


# Fix missing import
from typing import Callable
