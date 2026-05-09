"""
VAL API Server v14.0 — Unified Operator Console
=================================================
Security-hardened. CORS locked to localhost. Rate-limited.
SAFE/POWER/LAB security modes. Mistral+Qwen smart routing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections import defaultdict
from typing import AsyncIterator, List, Optional

logger = logging.getLogger("val.api")

try:
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import StreamingResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    import uvicorn
    _OK = True
except ImportError:
    _OK = False

_llm_executor   = ThreadPoolExecutor(max_workers=1, thread_name_prefix="val-llm")
_tools_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="val-tools")

_sessions: dict = {}
MAX_HISTORY = 12

# LRU response cache for repeated queries (128 entries max)
from functools import lru_cache
import hashlib

_response_cache: dict = {}
_CACHE_MAX = 128

def _cache_key(message: str, model: str, mode: str) -> str:
    return hashlib.md5(f"{message}|{model}|{mode}".encode()).hexdigest()

def _cache_get(message: str, model: str, mode: str) -> Optional[str]:
    key = _cache_key(message, model, mode)
    return _response_cache.get(key)

def _cache_put(message: str, model: str, mode: str, response: str) -> None:
    key = _cache_key(message, model, mode)
    _response_cache[key] = response
    # Evict oldest if over limit
    if len(_response_cache) > _CACHE_MAX:
        oldest = next(iter(_response_cache))
        del _response_cache[oldest]

def _get_hist(sid: str) -> list:
    return _sessions.setdefault(sid, [])[-MAX_HISTORY * 2:]

def _add_turn(sid: str, role: str, content: str) -> None:
    h = _sessions.setdefault(sid, [])
    h.append({"role": role, "content": content})
    if len(h) > MAX_HISTORY * 2:
        h[:] = h[-(MAX_HISTORY * 2):]

_FAST_REPLIES = {
    "hi":"Hey! How can I assist?", "hello":"Hello! What do you need?",
    "hey":"Hey! What can I do?",  "thanks":"You're welcome!",
    "thank you":"Happy to help!", "ty":"Of course!", "thx":"No problem!",
    "bye":"Goodbye!", "ok":"Got it.", "okay":"Got it.", "k":"Got it.",
    "how are you":"Operating at full capacity. What do you need?",
    "good morning":"Good morning! What can I help with?",
    "good evening":"Good evening! How can I help?",
}

def _fast_reply(msg: str) -> Optional[str]:
    return _FAST_REPLIES.get(msg.lower().strip().rstrip("!.,?"))

VAL_SYSTEM_PROMPT = (
    "You are VAL, a fast local AI operating system. "
    "Behave like an elite Linux operator, software engineer, analyst, and assistant. "
    "When users enter commands, execute or explain them. "
    "When asked questions, answer accurately and concisely. "
    "Be concise, fast, technical, and useful. Use markdown for code."
)

if _OK:
    class ChatRequest(BaseModel):
        message:      str = Field(..., min_length=1, max_length=8192)
        session_id:   str = "default"
        model:        Optional[str] = None
        stream:       Optional[bool] = True
        max_tokens:   Optional[int]  = Field(default=256, ge=32, le=2048)
        temperature:  Optional[float]= Field(default=0.4, ge=0.0, le=2.0)
        response_mode:Optional[str]  = "brief"   # brief | deep

    class ModeRequest(BaseModel):
        mode:       str = Field(..., description="safe | power | lab")
        session_id: str = "default"

    class TerminalRequest(BaseModel):
        command:    str = Field(..., description="Shell command")
        session_id: str = "default"

    class ModelSelectRequest(BaseModel):
        model: str = Field(..., description="mistral | qwen | tiny")

    class SocScanRequest(BaseModel):
        log_path:   str = "d:/PAV2/PA/app.log"
        tail_lines: int = 500
        text:       Optional[str] = None

    class OsintRequest(BaseModel):
        target: str = Field(..., description="Domain, IP, or URL")

    class MemoryResetRequest(BaseModel):
        session_id: str = "default"

    class VoiceSpeakRequest(BaseModel):
        text: str = Field(..., min_length=1, max_length=1000)

    def build_app() -> "FastAPI":
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app):
            logger.info("[VAL] Server v14.0 starting — Operator Console")
            loop = asyncio.get_running_loop()
            loop.run_in_executor(_llm_executor, _preload_model)
            yield
            logger.info("[VAL] Shutting down")
            from val.models.governor import get_governor
            _llm_executor.shutdown(wait=False)
            _tools_executor.shutdown(wait=False)

        app = FastAPI(
            title="VAL AI Platform",
            description="Virtual Autonomous Logic — Local AI Operating System",
            version="14.0.0",
            lifespan=lifespan,
            docs_url="/docs",
            redoc_url=None,
        )

        # ── Rate limiter (60 req/min per IP) ──────────────────────────────
        _rate_buckets: dict = defaultdict(list)
        RATE_LIMIT = 60
        RATE_WINDOW = 60.0

        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()
            bucket = _rate_buckets[client_ip]
            # Purge old entries
            bucket[:] = [t for t in bucket if now - t < RATE_WINDOW]
            if len(bucket) >= RATE_LIMIT:
                return JSONResponse({"detail": "Rate limit exceeded. Try again shortly."}, status_code=429)
            bucket.append(now)
            return await call_next(request)

        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8765",
                "http://127.0.0.1:8765",
            ],
            allow_methods=["GET","POST","OPTIONS"],
            allow_headers=["*"],
        )

        # ── Health ────────────────────────────────────────────────────────────
        @app.get("/health")
        async def health():
            from val.models.governor import get_governor
            g = get_governor()
            return {"status":"ok","version":"14.0.0",
                    "model_loaded":g.is_loaded,"active_model":g.active_model_name,
                    "device":g.device,"backend":getattr(g, '_backend', 'hf')}

        # ── Status ────────────────────────────────────────────────────────────
        @app.get("/status")
        async def status():
            return JSONResponse(await _system_info())

        # ── System (fast stats for right panel) ───────────────────────────────
        @app.get("/system")
        async def system_stats():
            return JSONResponse(await _system_info())

        # ── GPU stats ─────────────────────────────────────────────────────────
        @app.get("/gpu")
        async def gpu_stats():
            info = {"available": False}
            try:
                import torch
                if torch.cuda.is_available():
                    alloc = torch.cuda.memory_allocated(0)
                    total = torch.cuda.get_device_properties(0).total_memory
                    reserved = torch.cuda.memory_reserved(0)
                    info = {
                        "available":    True,
                        "name":         torch.cuda.get_device_name(0),
                        "vram_total_gb":round(total   / 1e9, 2),
                        "vram_used_gb": round(alloc   / 1e9, 2),
                        "vram_resv_gb": round(reserved/ 1e9, 2),
                        "vram_pct":     round(alloc   / total * 100, 1),
                    }
            except Exception:
                pass
            return JSONResponse(info)

        # ── Security Mode ─────────────────────────────────────────────────────
        @app.post("/mode")
        async def set_security_mode(body: ModeRequest):
            from val.tools.terminal import set_mode
            mode = set_mode(body.session_id, body.mode)
            descriptions = {
                "SAFE":  "Standard restrictions — safe commands only",
                "POWER": "Extended tools enabled — nmap, hashcat, gobuster…",
                "LAB":   "⚠️ Unrestricted local testing mode",
            }
            return JSONResponse({
                "success":     True,
                "mode":        mode,
                "session_id":  body.session_id,
                "description": descriptions.get(mode, ""),
            })

        @app.get("/mode")
        async def get_security_mode(session_id: str = "default"):
            from val.tools.terminal import get_mode
            return JSONResponse({"mode": get_mode(session_id), "session_id": session_id})

        # ── Models ────────────────────────────────────────────────────────────
        @app.get("/models/status")
        async def models_status():
            from val.models.governor import get_governor
            return JSONResponse(get_governor().status())

        @app.post("/models/load")
        async def load_model(body: ModelSelectRequest):
            from val.models.governor import get_governor
            g = get_governor()
            loop = asyncio.get_running_loop()
            ok = await loop.run_in_executor(_llm_executor, lambda: g.load(body.model))
            return JSONResponse({"success":ok,"active_model":g.active_model_name,"device":g.device})

        @app.post("/models/select")
        async def select_model(body: ModelSelectRequest):
            from val.models.governor import get_governor
            g = get_governor()
            loop = asyncio.get_running_loop()
            ok = await loop.run_in_executor(_llm_executor, lambda: g.load(body.model))
            return JSONResponse({
                "success":ok,"active_model":g.active_model_name,"device":g.device,
                "message": f"Switched to {g.active_model_name}" if ok else f"Failed to load {body.model}",
            })

        @app.post("/switch_model")
        async def switch_model_legacy(body: ModelSelectRequest):
            return await select_model(body)

        # ── Chat (SSE streaming) ──────────────────────────────────────────────
        @app.post("/chat")
        async def chat(body: ChatRequest, request: Request):
            t0 = time.time()

            # Fast-path greetings
            fast = _fast_reply(body.message)
            if fast:
                _add_turn(body.session_id, "user", body.message)
                _add_turn(body.session_id, "assistant", fast)
                if body.stream:
                    async def _fast_sse():
                        yield f"data: {json.dumps({'status':'ok','meta':{'model':'fast-path'}})}\n\n"
                        yield f"data: {json.dumps({'chunk':fast})}\n\n"
                        yield f"data: {json.dumps({'done':True,'model_used':'fast-path','latency_s':0.0})}\n\n"
                        yield "data: [DONE]\n\n"
                    return StreamingResponse(_fast_sse(), media_type="text/event-stream",
                                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
                return JSONResponse({"text":fast,"model_used":"fast-path","latency_s":0.0})

            # Mode-set command in chat
            import re as _re
            mode_m = _re.search(r"\bmode\s+(safe|power|lab)\b", body.message, _re.I)
            if mode_m:
                from val.tools.terminal import set_mode
                mode = set_mode(body.session_id, mode_m.group(1))
                icons = {"SAFE":"🟢","POWER":"🟡","LAB":"🔴"}
                reply = f"{icons.get(mode,'◉')} **{mode} MODE** activated.\n" + {
                    "SAFE":  "Standard restrictions. Safe commands only.",
                    "POWER": "Extended tools enabled. nmap, hashcat, gobuster, sqlmap…",
                    "LAB":   "⚠️ Unrestricted local testing. Catastrophic ops still blocked.",
                }.get(mode,"")
                if body.stream:
                    async def _mode_sse():
                        yield f"data: {json.dumps({'chunk':reply,'mode':mode})}\n\n"
                        yield f"data: {json.dumps({'done':True,'model_used':'system','latency_s':round(time.time()-t0,3),'mode':mode})}\n\n"
                        yield "data: [DONE]\n\n"
                    return StreamingResponse(_mode_sse(), media_type="text/event-stream",
                                             headers={"Cache-Control":"no-cache"})
                return JSONResponse({"text":reply,"model_used":"system","mode":mode})

            # Power tool detection
            try:
                from val.tools.power_tools import parse_tool_command, get_adapter
                parsed = parse_tool_command(body.message)
                if parsed:
                    tool_name, tool_args = parsed
                    adapter = get_adapter(tool_name)
                    if adapter:
                        if body.stream:
                            async def _tool_sse():
                                yield f"data: {json.dumps({'status':f'Executing {tool_name}...','meta':{'model':tool_name}})}\n\n"
                                result = await adapter.execute(tool_args)
                                _add_turn(body.session_id,"user",body.message)
                                _add_turn(body.session_id,"assistant",result.output)
                                yield f"data: {json.dumps({'chunk':result.output,'terminal':True,'command':result.command})}\n\n"
                                yield f"data: {json.dumps({'done':True,'model_used':tool_name,'latency_s':round(time.time()-t0,3)})}\n\n"
                                yield "data: [DONE]\n\n"
                            return StreamingResponse(_tool_sse(), media_type="text/event-stream",
                                                     headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
                        result = await adapter.execute(tool_args)
                        return JSONResponse({"text":result.output,"model_used":tool_name,
                                             "latency_s":round(time.time()-t0,3),"terminal":True})
            except Exception:
                pass

            # Terminal command detection
            from val.tools.terminal import is_terminal_request, handle_terminal_request, stream_execute
            if is_terminal_request(body.message):
                if body.stream:
                    async def _term_sse():
                        yield f"data: {json.dumps({'status':'Executing...','meta':{'model':'terminal'}})}\n\n"
                        accumulated = []
                        async for line in stream_execute(body.message, body.session_id):
                            accumulated.append(line)
                            yield f"data: {json.dumps({'chunk':line+chr(10),'terminal':True})}\n\n"
                        full = "\n".join(accumulated)
                        _add_turn(body.session_id,"user",body.message)
                        _add_turn(body.session_id,"assistant",full)
                        yield f"data: {json.dumps({'done':True,'model_used':'terminal','latency_s':round(time.time()-t0,3)})}\n\n"
                        yield "data: [DONE]\n\n"
                    return StreamingResponse(_term_sse(), media_type="text/event-stream",
                                             headers={"Cache-Control":"no-cache"})
                output = handle_terminal_request(body.message, body.session_id)
                return JSONResponse({"text":output,"model_used":"terminal","latency_s":round(time.time()-t0,3),"terminal":True})

            # LLM inference
            from val.models.governor import get_governor, model_path_exists
            g = get_governor()
            if not model_path_exists():
                raise HTTPException(503, detail="No model weights found. Add Mistral or Qwen to d:/PAV2/models/")

            if not g.is_loaded:
                target = body.model or None
                loop = asyncio.get_running_loop()
                ok = await loop.run_in_executor(_llm_executor, lambda: g.load(target))
                if not ok:
                    raise HTTPException(503, detail=f"Model failed to load: {g.status().get('error','unknown')}")

            hist = _get_hist(body.session_id)
            messages = [{"role":"system","content":VAL_SYSTEM_PROMPT}]
            messages.extend(hist[-8:])
            messages.append({"role":"user","content":body.message})
            model_name = g.active_model_name or "unknown"
            resp_mode  = body.response_mode or "brief"

            if body.stream:
                chunk_q: queue.Queue = queue.Queue()
                collected = []

                async def event_stream() -> AsyncIterator[str]:
                    yield f"data: {json.dumps({'status':'Generating...','meta':{'model':model_name}})}\n\n"

                    def _run():
                        try:
                            for chunk in g.stream_sync(messages, body.max_tokens or 256,
                                                       body.temperature or 0.4, resp_mode):
                                chunk_q.put(chunk)
                        except Exception as e:
                            chunk_q.put(Exception(str(e)))
                        finally:
                            chunk_q.put(None)

                    loop = asyncio.get_running_loop()
                    fut  = loop.run_in_executor(_llm_executor, _run)

                    while True:
                        try:
                            item = await asyncio.wait_for(
                                loop.run_in_executor(None, chunk_q.get), timeout=300.0)
                        except asyncio.TimeoutError:
                            yield f"data: {json.dumps({'error':'Inference timeout'})}\n\n"
                            break
                        if item is None:
                            break
                        if isinstance(item, Exception):
                            yield f"data: {json.dumps({'error':str(item)})}\n\n"
                            break
                        collected.append(item)
                        yield f"data: {json.dumps({'chunk':item})}\n\n"

                    await fut
                    full = "".join(collected).strip()
                    if full:
                        _add_turn(body.session_id,"user",body.message)
                        _add_turn(body.session_id,"assistant",full)
                    yield f"data: {json.dumps({'done':True,'latency_s':round(time.time()-t0,3),'model_used':model_name,'session_id':body.session_id})}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(event_stream(), media_type="text/event-stream",
                                         headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
            else:
                # Check response cache first
                cached = _cache_get(body.message, model_name, resp_mode)
                if cached:
                    _add_turn(body.session_id,"user",body.message)
                    _add_turn(body.session_id,"assistant",cached)
                    return JSONResponse({"text":cached,"model_used":f"{model_name}(cached)",
                                         "latency_s":round(time.time()-t0,3),"session_id":body.session_id,"cached":True})

                loop = asyncio.get_running_loop()
                text = await loop.run_in_executor(
                    _llm_executor,
                    lambda: g.generate(messages, body.max_tokens or 256,
                                       body.temperature or 0.4, resp_mode),
                )
                _add_turn(body.session_id,"user",body.message)
                _add_turn(body.session_id,"assistant",text)
                # Cache the response
                _cache_put(body.message, model_name, resp_mode, text)
                return JSONResponse({"text":text,"model_used":model_name,
                                     "latency_s":round(time.time()-t0,3),"session_id":body.session_id})

        @app.post("/query")
        async def query(body: ChatRequest, request: Request):
            body.stream = False
            return await chat(body, request)

        # ── Terminal ──────────────────────────────────────────────────────────
        @app.post("/terminal")
        async def terminal(body: TerminalRequest):
            from val.tools.terminal import execute_async
            r = await execute_async(body.command, body.session_id)
            return JSONResponse({"command":r.command,"output":r.output,
                                  "blocked":r.blocked,"exit_code":r.exit_code,
                                  "duration_ms":round(r.duration_ms,1)})

        @app.get("/terminal/allowed")
        async def terminal_allowed(session_id: str = "default"):
            from val.tools.terminal import SAFE_COMMANDS, POWER_COMMANDS, LAB_COMMANDS, get_mode
            mode = get_mode(session_id)
            cmds = {"SAFE":SAFE_COMMANDS,"POWER":POWER_COMMANDS,"LAB":LAB_COMMANDS}.get(mode, SAFE_COMMANDS)
            return JSONResponse({"mode":mode,"allowed":sorted(cmds)})

        @app.get("/terminal/tools")
        async def terminal_tools():
            try:
                from val.tools.power_tools import get_tool_status
                return JSONResponse({"tools":get_tool_status(),"operator_mode":True})
            except Exception:
                return JSONResponse({"tools":{},"operator_mode":True})

        # ── Memory ────────────────────────────────────────────────────────────
        @app.get("/memory")
        async def memory_stats(session_id: str = "default"):
            hist = _sessions.get(session_id,[])
            return JSONResponse({"session_id":session_id,"turn_count":len(hist)//2,
                                  "message_count":len(hist),"sessions_total":len(_sessions),
                                  "history":hist[-10:]})

        @app.post("/memory/reset")
        async def memory_reset(body: MemoryResetRequest):
            _sessions.pop(body.session_id, None)
            return JSONResponse({"success":True,"session_id":body.session_id})

        @app.post("/reset")
        async def reset_legacy(request: Request, session_id: str = "default"):
            _sessions.pop(session_id, None)
            return JSONResponse({"status":"ok"})

        # ── SOC ───────────────────────────────────────────────────────────────
        @app.post("/soc/scan")
        async def soc_scan(body: SocScanRequest):
            from val.soc.soc_engine import scan_log_file, analyze_text, generate_report, get_metrics, extract_iocs
            loop = asyncio.get_running_loop()
            def _do():
                if body.text:
                    threats = analyze_text(body.text); iocs = extract_iocs(body.text)
                else:
                    threats = scan_log_file(body.log_path, body.tail_lines)
                    iocs = extract_iocs(" ".join(t["matched"] for t in threats))
                return threats, iocs
            threats, iocs = await loop.run_in_executor(_tools_executor, _do)
            return JSONResponse({"success":True,"threats":threats[:100],"threat_count":len(threats),
                                  "metrics":get_metrics(threats),"iocs":iocs,"report":generate_report(threats)})

        @app.post("/soc/analyze")
        async def soc_analyze(body: SocScanRequest):
            from val.soc.soc_engine import analyze_text, generate_report, get_metrics, extract_iocs
            loop = asyncio.get_event_loop()
            threats, iocs = await loop.run_in_executor(
                _tools_executor,
                lambda: (analyze_text(body.text or ""), extract_iocs(body.text or "")))
            return JSONResponse({"threats":threats,"metrics":get_metrics(threats),
                                  "iocs":iocs,"report":generate_report(threats)})

        @app.get("/soc/metrics")
        async def soc_metrics():
            import psutil
            from val.soc.soc_engine import scan_log_file, get_metrics
            loop    = asyncio.get_event_loop()
            threats = await loop.run_in_executor(
                _tools_executor, lambda: scan_log_file("d:/PAV2/PA/app.log", 1000))
            m = get_metrics(threats) if threats else {"total":0,"critical":0,"high":0,"medium":0,"low":0,"risk_score":0}
            return JSONResponse({**m,"system":{"cpu_pct":psutil.cpu_percent(interval=None),
                                               "ram_pct":psutil.virtual_memory().percent}})

        # ── OSINT ─────────────────────────────────────────────────────────────
        @app.post("/osint/gather")
        async def osint_gather(body: OsintRequest):
            from val.osint.osint_engine import gather
            result = await gather(body.target)
            return JSONResponse(result.to_dict())

        # ── Voice ─────────────────────────────────────────────────────────────
        @app.get("/voice/status")
        async def voice_status():
            try:
                from val.voice.voice_bridge import get_voice_bridge
                return JSONResponse(get_voice_bridge().status())
            except Exception:
                return JSONResponse({"available":False})

        @app.post("/voice/speak")
        async def voice_speak(body: VoiceSpeakRequest):
            from val.voice.voice_bridge import get_voice_bridge
            get_voice_bridge().speak(body.text, async_mode=True)
            return JSONResponse({"success":True})

        @app.post("/voice/transcribe")
        async def voice_transcribe(request: Request):
            from val.voice.voice_bridge import get_voice_bridge
            bridge = get_voice_bridge()
            if not bridge.stt.available:
                raise HTTPException(503, detail="Whisper not installed")
            form = await request.form()
            audio = form.get("audio")
            if not audio:
                raise HTTPException(400, detail="No audio file")
            contents = await audio.read()
            if len(contents) > 10 * 1024 * 1024:
                raise HTTPException(413, detail="Audio too large")
            filename = getattr(audio, "filename", "rec.webm") or "rec.webm"
            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(
                _tools_executor, lambda: bridge.transcribe_bytes(contents, filename))
            if text is None:
                raise HTTPException(500, detail="Transcription failed")
            return JSONResponse({"text":text,"success":True})

        # ── Logs ──────────────────────────────────────────────────────────────
        @app.get("/logs/{category}")
        async def read_logs(category: str, tail: int = 50):
            log_file = Path("d:/PAV2/val/logs") / f"{category}.jsonl"
            if not log_file.exists():
                return JSONResponse({"category":category,"content":""})
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            return JSONResponse({"category":category,"content":"\n".join(lines[-tail:])})

        # ── Settings ──────────────────────────────────────────────────────────
        @app.post("/settings")
        async def update_settings(request: Request):
            body = await request.json()
            return JSONResponse({"success":True,"settings":body})

        @app.post("/unload")
        async def unload(body: MemoryResetRequest):
            _sessions.pop(body.session_id, None)
            return JSONResponse({"success":True})

        # ── Code Analysis (merged from PA) ─────────────────────────────────
        @app.post("/analyze")
        async def api_analyze(request: Request):
            req = await request.json()
            path = req.get("path", "")
            loop = asyncio.get_running_loop()
            from val.tools.analyzer import analyze_project
            from val.config.settings import VAL_ROOT
            result = await loop.run_in_executor(
                _tools_executor, analyze_project, path or str(VAL_ROOT)
            )
            return {"text": result.to_text(), "data": result.to_dict()}

        # ── Project Cleanup (merged from PA) ───────────────────────────────
        @app.post("/cleanup")
        async def api_cleanup(request: Request):
            req = await request.json()
            path = req.get("path", "")
            safe_only = req.get("safe_only", True)
            loop = asyncio.get_running_loop()
            if req.get("execute"):
                from val.tools.cleanup import execute_cleanup
                from val.config.settings import VAL_ROOT
                result = await loop.run_in_executor(
                    _tools_executor, execute_cleanup, path or str(VAL_ROOT), safe_only
                )
                return result
            else:
                from val.tools.cleanup import scan_project
                from val.config.settings import VAL_ROOT
                report = await loop.run_in_executor(
                    _tools_executor, scan_project, path or str(VAL_ROOT)
                )
                return {"text": report.to_report(), "data": report.to_dict()}

        # ── Wiki Search (merged from PA) ───────────────────────────────────
        @app.post("/wiki")
        async def api_wiki(request: Request):
            req = await request.json()
            query = req.get("query", "").strip()
            if not query:
                raise HTTPException(400, "query is required")
            loop = asyncio.get_running_loop()
            from val.tools.wiki import wiki_fetch
            text = await loop.run_in_executor(_tools_executor, wiki_fetch, query)
            return {"text": text, "query": query}

        # ── Agent (merged from PA) ─────────────────────────────────────────
        @app.post("/agent/run")
        async def api_agent_run(request: Request):
            req = await request.json()
            query = req.get("query", "").strip()
            if not query:
                raise HTTPException(400, "query is required")
            max_steps = req.get("max_steps", 8)
            loop = asyncio.get_running_loop()
            from val.agents.agent import ReActAgent
            agent = ReActAgent(max_steps=max_steps)
            result = await loop.run_in_executor(_tools_executor, agent.run, query)
            return result.to_dict()

        # ── Firewall Builder (v14.0) ───────────────────────────────────
        @app.post("/firewall")
        async def api_firewall(request: Request):
            req = await request.json()
            text = req.get("text", "").strip()
            if not text:
                raise HTTPException(400, "text is required")
            execute = req.get("execute", False)
            from val.tools.firewall import analyze_firewall_request, apply_firewall_rule
            if execute:
                result = await apply_firewall_rule(text)
            else:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    _tools_executor, analyze_firewall_request, text
                )
            return result

        # ── v14.1: Cache Stats ─────────────────────────────────────────
        @app.get("/cache/stats")
        async def cache_stats():
            from val.core.cache import get_cache
            return JSONResponse(get_cache().stats())

        # ── v14.1: Event Bus SSE Stream ────────────────────────────────
        @app.get("/events/stream")
        async def event_stream(request: Request):
            from val.core.event_bus import get_event_bus
            bus = get_event_bus()

            async def _stream():
                async for event in bus.stream(timeout=300.0):
                    if await request.is_disconnected():
                        break
                    yield event.to_sse()

            return StreamingResponse(
                _stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        @app.get("/events/recent")
        async def events_recent(count: int = 20, event_type: Optional[str] = None):
            from val.core.event_bus import get_event_bus
            return JSONResponse(get_event_bus().recent(count, event_type))

        @app.get("/events/stats")
        async def events_stats():
            from val.core.event_bus import get_event_bus
            return JSONResponse(get_event_bus().stats())

        # ── v14.1: Audit Log ───────────────────────────────────────────
        @app.get("/audit/recent")
        async def audit_recent(count: int = 50):
            from val.security.audit import get_audit
            return JSONResponse({"entries": get_audit().get_recent(count)})

        @app.get("/audit/violations")
        async def audit_violations(count: int = 50):
            from val.security.audit import get_audit
            return JSONResponse({"violations": get_audit().get_violations(count)})

        @app.get("/audit/stats")
        async def audit_stats():
            from val.security.audit import get_audit
            return JSONResponse(get_audit().stats())

        # ── v14.1: Scope Config ────────────────────────────────────────
        @app.get("/scope")
        async def scope_status():
            from val.security.scope import get_scope
            return JSONResponse(get_scope().status())

        @app.post("/scope/cidr")
        async def add_cidr(request: Request):
            req = await request.json()
            cidr = req.get("cidr", "").strip()
            if not cidr:
                raise HTTPException(400, "cidr is required")
            from val.security.scope import get_scope
            get_scope().add_allowed_cidr(cidr)
            return JSONResponse({"success": True, "cidr": cidr})

        @app.post("/scope/domain")
        async def add_domain(request: Request):
            req = await request.json()
            domain = req.get("domain", "").strip()
            if not domain:
                raise HTTPException(400, "domain is required")
            from val.security.scope import get_scope
            get_scope().add_allowed_domain(domain)
            return JSONResponse({"success": True, "domain": domain})

        # ── v14.1: Orchestrator Status ─────────────────────────────────
        @app.get("/orchestrator/status")
        async def orchestrator_status():
            from val.core.orchestrator import get_orchestrator
            return JSONResponse(get_orchestrator().status())

        # ── v14.1: Scheduler Metrics ───────────────────────────────────
        @app.get("/scheduler/stats")
        async def scheduler_stats():
            from val.core.scheduler import get_scheduler
            return JSONResponse(get_scheduler().stats())

        return app


async def _system_info() -> dict:
    info: dict = {"val_version":"14.0.0"}
    try:
        import psutil
        mem = psutil.virtual_memory()
        info.update({
            "ram_pct":     mem.percent,
            "ram_gb":      round(mem.used / 1e9, 2),
            "ram_total_gb":round(mem.total / 1e9, 2),
            "ram_free_gb": round(mem.available / 1e9, 2),
            "cpu_pct":     psutil.cpu_percent(interval=None),
            "sessions_active": len(_sessions),
        })
    except Exception:
        pass
    try:
        from val.models.governor import get_governor
        g = get_governor()
        info["active_model"]  = g.active_model_name
        info["model_loaded"]  = g.is_loaded
        info["model_device"]  = g.device
        info["model_ready"]   = g.model_path_exists()
        s = g.status()
        info["loader_status"] = s
        if "gpu_vram_used_gb" in s:
            info["gpu_vram_used_gb"]  = s["gpu_vram_used_gb"]
            info["gpu_vram_total_gb"] = s["gpu_vram_total_gb"]
            info["gpu_vram_pct"]      = s["gpu_vram_pct"]
    except Exception:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            info["gpu_name"]     = torch.cuda.get_device_name(0)
            info["gpu_vram_gb"]  = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2)
            info["gpu_used_gb"]  = round(torch.cuda.memory_allocated(0) / 1e9, 2)
    except Exception:
        pass
    return info





def _preload_model():
    from val.models.governor import get_governor, DEFAULT_MODEL, model_path_exists
    if model_path_exists():
        logger.info("[VAL] Preloading %s…", DEFAULT_MODEL)
        g = get_governor()
        if g.load(DEFAULT_MODEL):
            logger.info("[VAL] %s ready on %s", g.active_model_name, g.device)
        else:
            logger.warning("[VAL] Preload failed — retry on first request")
    else:
        logger.warning("[VAL] No model weights — skipping preload")


def start_api_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    if not _OK:
        print("[VAL] pip install fastapi uvicorn pydantic")
        return
    app = build_app()
    print(f"\n[VAL] API v14.0 - Operator Console")
    print(f"[VAL] Server -> http://{host}:{port}")
    print(f"[VAL] Docs   -> http://{host}:{port}/docs\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")