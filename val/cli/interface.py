"""
VAL CLI Interface
=================
Rich terminal interface for VAL.
Commands:
  val chat          - Enter interactive chat mode
  val run <prompt>  - Run a single prompt and exit
  val agents        - List active agents
  val tasks         - List tasks
  val status        - Show system status
  val models        - Show model status
  val logs [cat]    - View logs
  val serve         - Start API server
  val reset         - Reset conversation memory
  val version       - Show VAL version
"""

import sys
import json
import time
import argparse
import shutil
from typing import Optional

# Force UTF-8 on Windows so box-drawing/arrow chars don't crash
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from val.utils.logger import get_logger, LogCategory
from val.config.settings import get_config, validate_config
from val.core.engine import get_kernel
from val.agents.agent import get_orchestrator
from val.state.store import get_state
from val.tools.executor import get_tool_registry

logger = get_logger("cli", LogCategory.SYSTEM)

# ─── Terminal Helpers ─────────────────────────────────────────────────────────

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_BLUE   = "\033[34m"
_MAGENTA= "\033[35m"

def _c(text: str, color: str) -> str:
    """Colorize text if terminal supports it."""
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{_RESET}"

def _header() -> str:
    w = shutil.get_terminal_size((80, 24)).columns
    border = "=" * w
    lines = [
        border,
        "  VAL -- Virtual Autonomous Logic  v" + get_config().val_version,
        "  Local-first AI Agent OS  |  Mistral 7B / Gemma 2B / TinyLLaMA",
        border,
    ]
    return _c("\n".join(lines), _CYAN)

def _print_val(text: str) -> None:
    """Print a VAL response with formatting."""
    print(f"\n{_c('VAL', _CYAN + _BOLD)} > {text}\n")

def _print_info(text: str) -> None:
    print(_c(f"  [i] {text}", _BLUE))

def _print_ok(text: str) -> None:
    print(_c(f"  [OK] {text}", _GREEN))

def _print_warn(text: str) -> None:
    print(_c(f"  [!] {text}", _YELLOW))

def _print_error(text: str) -> None:
    print(_c(f"  [X] {text}", _RED), file=sys.stderr)

def _print_json(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))


# ─── VAL Initialization ───────────────────────────────────────────────────────

def _initialize_val(verbose: bool = False, skip_model_check: bool = False) -> bool:
    """Boot the VAL system: validate config, initialize state, register tools."""
    try:
        cfg = get_config()
        if verbose:
            _print_info(f"Config loaded. Default model: {cfg.default_model}")

        if not skip_model_check:
            try:
                validate_config(cfg)
                if verbose:
                    _print_ok("Config validation passed")
            except RuntimeError as rte:
                # Non-fatal: model paths may not exist yet (lazy loading)
                _print_warn(f"Config note: {rte}")

        # Initialize state store
        state = get_state()
        state.mark_initialized()

        # Pre-initialize tool registry
        tool_reg = get_tool_registry()
        if verbose:
            tools = [t["name"] for t in tool_reg.list_tools()]
            _print_ok(f"Tools loaded: {', '.join(tools)}")

        return True
    except Exception as e:
        _print_error(f"VAL initialization failed: {e}")
        logger.error(f"Initialization error: {e}", exc_info=True)
        return False


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_chat(args) -> None:
    """Interactive multi-turn chat mode."""
    print(_header())
    print(_c("  Type your message and press Enter. Use /quit to exit.\n", _DIM))
    print(_c("  Commands: /reset  /status  /models  /quit\n", _DIM))

    if not _initialize_val(verbose=True):
        return

    orch = get_orchestrator()
    agent = orch.get_core()

    while True:
        try:
            raw = input(_c("YOU", _YELLOW + _BOLD) + " › ").strip()
        except (KeyboardInterrupt, EOFError):
            print(_c("\n[VAL] Goodbye.", _CYAN))
            break

        if not raw:
            continue

        # Built-in slash commands
        if raw.lower() in ("/quit", "/exit", "/q"):
            print(_c("\n[VAL] Session ended.", _CYAN))
            break
        elif raw.lower() == "/reset":
            agent.reset()
            _print_ok("Conversation memory cleared.")
            continue
        elif raw.lower() == "/status":
            _print_json(agent.status_report())
            continue
        elif raw.lower() == "/models":
            from val.models.orchestrator_v6 import MODEL_REGISTRY
            from val.models.governor import get_governor
            _active = get_governor().active_model
            _print_json({
                k: {"ram_gb": e.ram_gb, "kind": e.kind,
                    "enabled": e.enabled, "loaded": (_active == k)}
                for k, e in MODEL_REGISTRY.items()
            })
            continue
        elif raw.lower() == "/help":
            print("  Commands: /reset  /status  /models  /quit")
            continue

        # Rate-limit check (applies to the terminal user, using key "cli")
        from val.security.rate_limiter import get_rate_limiter, RateLimitError
        try:
            remaining = get_rate_limiter().enforce("cli")
        except RateLimitError as rl_err:
            _print_error(str(rl_err))
            continue

        # Inference with streaming
        print(_c("\nVAL", _CYAN + _BOLD) + " › ", end="", flush=True)
        t0 = time.time()
        collected = []
        try:
            for chunk in agent.stream(raw):
                print(chunk, end="", flush=True)
                collected.append(chunk)
        except Exception as e:
            _print_error(f"Error: {e}")
            logger.error(f"Chat error: {e}", exc_info=True)

        latency = time.time() - t0
        print(_c(f"\n  [{latency:.2f}s]", _DIM))


def cmd_run(args) -> None:
    """Run a single prompt and print response to stdout."""
    if not _initialize_val():
        sys.exit(1)

    prompt = " ".join(args.prompt)
    if not prompt:
        _print_error("No prompt provided. Usage: val run <your prompt>")
        sys.exit(1)

    # Rate-limit check for CLI usage
    from val.security.rate_limiter import get_rate_limiter, RateLimitError
    try:
        get_rate_limiter().enforce("cli")
    except RateLimitError as e:
        _print_error(str(e))
        sys.exit(1)

    import asyncio
    kernel = get_kernel()
    try:
        result = asyncio.run(kernel.process(
            prompt,
            session_id="cli",
        ))
        if args.json_output if hasattr(args, "json_output") else False:
            _print_json(result.as_dict())
        else:
            print(result.text)
    except Exception as e:
        _print_error(f"Run failed: {e}")
        sys.exit(1)


def cmd_status(args) -> None:
    """Display system status."""
    if not _initialize_val():
        sys.exit(1)

    state = get_state()
    snap = state.snapshot()
    cfg = get_config()

    print(_header())
    print(_c("\n  SYSTEM STATUS\n", _BOLD))
    print(f"  Version       : {cfg.val_version}")
    print(f"  Session       : {snap['session_id']}")
    print(f"  Default Model : {cfg.default_model}")
    print(f"  Sandbox       : {'ON' if cfg.security.sandbox_mode else 'OFF'}")
    print(f"  Shell Exec    : {'ALLOWED' if cfg.security.allow_shell_execution else 'BLOCKED'}")
    print(f"  Network       : {'ALLOWED' if cfg.security.allow_network_access else 'BLOCKED'}")

    print(_c("\n  MODELS\n", _BOLD))
    from val.models.governor import get_governor
    from val.models.orchestrator_v6 import MODEL_REGISTRY
    governor = get_governor()
    active = governor.active_model
    for name, entry in MODEL_REGISTRY.items():
        loaded  = active == name
        color   = _GREEN if loaded else _DIM
        label   = "loaded" if loaded else "not loaded"
        print(f"  {_c(label, color)}  {name}  ({entry.ram_gb}GB Q4, {entry.description})")

    print(_c("\n  METRICS\n", _BOLD))
    metrics = snap.get("metrics", {})
    print(f"  Requests      : {metrics.get('total_requests', 0)}")
    print(f"  Tokens In     : {metrics.get('total_tokens_in', 0)}")
    print(f"  Tokens Out    : {metrics.get('total_tokens_out', 0)}")
    print(f"  Avg Latency   : {metrics.get('avg_latency_s', 0):.2f}s")
    print(f"  Uptime        : {metrics.get('uptime_s', 0):.0f}s\n")


def cmd_agents(args) -> None:
    """List active agents."""
    if not _initialize_val():
        sys.exit(1)
    orch = get_orchestrator()
    agents = orch.list_agents()
    if not agents:
        _print_info("No agents registered yet.")
        return
    print(_c("\n  AGENTS\n", _BOLD))
    for a in agents:
        print(f"  [{a['status']:8s}] {a['name']} ({a['agent_id']}) — {a['type']}")
    print()


def cmd_tasks(args) -> None:
    """List tasks."""
    if not _initialize_val():
        sys.exit(1)
    state = get_state()
    tasks = state.list_tasks()
    if not tasks:
        _print_info("No tasks recorded.")
        return
    print(_c("\n  TASKS\n", _BOLD))
    for t in tasks:
        status_color = {
            "completed": _GREEN,
            "failed": _RED,
            "running": _YELLOW,
            "pending": _DIM,
            "cancelled": _DIM,
        }.get(t.status.value, _RESET)
        print(f"  [{_c(t.status.value, status_color):10s}] {t.task_id}  {t.name}")
    print()


def cmd_models(args) -> None:
    """Show model status."""
    if not _initialize_val():
        sys.exit(1)
    from val.models.orchestrator_v6 import MODEL_REGISTRY
    from val.models.governor import get_governor
    governor = get_governor()
    active   = governor.active_model
    print(_c("\n  MODEL REGISTRY\n", _BOLD))
    for name, entry in MODEL_REGISTRY.items():
        loaded  = active == name
        enabled = "enabled"    if entry.enabled else "disabled"
        status  = "loaded"     if loaded        else "not loaded"
        color   = _GREEN       if loaded        else _DIM
        print(f"  {name:12s}  {entry.kind:12s}  [{enabled:8s}] [{_c(status, color)}]")
        print(f"              RAM: {entry.ram_gb}GB (Q4) / {entry.ram_gb_q2}GB (Q2)")
        print(f"              {entry.description}")
    print()


def cmd_logs(args) -> None:
    """View system logs."""
    category = args.category if hasattr(args, "category") and args.category else "system"
    tail = args.tail if hasattr(args, "tail") and args.tail else 50
    from val.tools.executor import LogReaderTool
    tool = LogReaderTool()
    result = tool.execute(category=category, tail=tail)
    print(result)


def cmd_serve(args) -> None:
    """Start the VAL API server."""
    # skip_model_check=True: model paths validated at load time, not at startup
    if not _initialize_val(skip_model_check=True):
        sys.exit(1)
    from val.api.server import start_api_server
    cfg  = get_config()
    host = args.host if hasattr(args, "host") and args.host else cfg.api_host
    port = args.port if hasattr(args, "port") and args.port else cfg.api_port
    start_api_server(host=host, port=port)


def cmd_reset(args) -> None:
    """Reset conversation memory."""
    if not _initialize_val():
        sys.exit(1)
    from val.state.memory import get_memory_store
    get_memory_store().reset("default")
    get_memory_store().reset("cli")
    _print_ok("Conversation memory reset.")


def cmd_version(args) -> None:
    """Print VAL version."""
    cfg = get_config()
    print(f"VAL v{cfg.val_version}")


# ─── Argument Parser ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="val",
        description="VAL — Virtual Autonomous Logic | Local-first AI Agent OS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # chat
    subparsers.add_parser("chat", help="Enter interactive chat mode")

    # run
    run_p = subparsers.add_parser("run", help="Run a single prompt")
    run_p.add_argument("prompt", nargs="+", help="The prompt to run")
    run_p.add_argument("--model", help="Force model: mistral|gemma|tinyllama")
    run_p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    # status
    subparsers.add_parser("status", help="Show system status")

    # agents
    subparsers.add_parser("agents", help="List active agents")

    # tasks
    subparsers.add_parser("tasks", help="List tasks")

    # models
    subparsers.add_parser("models", help="Show model registry")

    # logs
    logs_p = subparsers.add_parser("logs", help="View system logs")
    logs_p.add_argument("category", nargs="?", default="system",
                        choices=["system", "agent", "errors", "security", "inference"])
    logs_p.add_argument("--tail", type=int, default=50)

    # serve
    serve_p = subparsers.add_parser("serve", help="Start API server")
    serve_p.add_argument("--host", default=None)
    serve_p.add_argument("--port", type=int, default=None)

    # reset
    subparsers.add_parser("reset", help="Reset conversation memory")

    # version
    subparsers.add_parser("version", help="Print version")

    return parser


def main() -> None:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    command_map = {
        "chat":    cmd_chat,
        "run":     cmd_run,
        "status":  cmd_status,
        "agents":  cmd_agents,
        "tasks":   cmd_tasks,
        "models":  cmd_models,
        "logs":    cmd_logs,
        "serve":   cmd_serve,
        "reset":   cmd_reset,
        "version": cmd_version,
    }

    if args.command is None:
        # Default: enter chat mode
        cmd_chat(args)
        return

    fn = command_map.get(args.command)
    if fn is None:
        parser.print_help()
        sys.exit(1)

    try:
        fn(args)
    except KeyboardInterrupt:
        print(_c("\n[VAL] Interrupted.", _CYAN))
    except Exception as e:
        _print_error(f"Unexpected error: {e}")
        logger.error(f"CLI crash: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
