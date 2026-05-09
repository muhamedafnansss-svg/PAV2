"""
VAL — Repo Intelligence v13.0
Merged from PA/backend/repo/repo_knowledge_engine.py + PA/backend/self_evolution/evolution_engine.py.
Provides: repo cloning, code indexing, semantic search, AST structure extraction, self-improvement proposals.
"""
from __future__ import annotations
import ast, hashlib, logging, re, subprocess
from pathlib import Path
from val.utils.logger import get_logger, LogCategory

logger = get_logger("repo_intel", LogCategory.TOOL)
_embedder = None; _faiss_index = None; _chunks: list[dict] = []; _indexed: set[str] = set()
SUPPORTED_EXT = {".py":"python",".js":"javascript",".jsx":"javascript",
    ".ts":"typescript",".tsx":"typescript",".md":"markdown",".json":"json"}
SKIP = {"node_modules",".git","__pycache__",".venv","venv","dist","build",".cache"}

def _get_embedder():
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError: pass
    return _embedder

def _get_index(dim=384):
    global _faiss_index
    if _faiss_index is None:
        try:
            import faiss; _faiss_index = faiss.IndexFlatL2(dim)
        except ImportError: pass
    return _faiss_index

# ── Repo Cloning ──────────────────────────────────────────────────────────────
def clone_repo(url: str, dest: Path) -> bool:
    if dest.exists(): return True
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git","clone","--depth=1","--quiet",url,str(dest)],
            check=True, timeout=120, capture_output=True)
        return True
    except Exception as e:
        logger.warning("[RepoIntel] Clone failed: %s", e); return False

# ── Code Indexing ─────────────────────────────────────────────────────────────
def index_repo(repo_dir: Path, name: str) -> int:
    emb = _get_embedder(); idx = _get_index()
    if not emb or not idx: return 0
    import numpy as np; count = 0
    for fpath in repo_dir.rglob("*"):
        if not fpath.is_file() or any(s in fpath.parts for s in SKIP): continue
        lang = SUPPORTED_EXT.get(fpath.suffix.lower())
        if not lang or fpath.stat().st_size > 200_000: continue
        try:
            code = fpath.read_text("utf-8", errors="replace")
            rel = str(fpath.relative_to(repo_dir))
            struct = _extract_structure(code, lang)
            if struct:
                _add(emb, idx, f"[{name}/{rel}] Structure: {struct}", name, rel, lang)
                count += 1
            words = code.split()
            for i in range(0, len(words), 320):
                chunk = " ".join(words[i:i+400])
                _add(emb, idx, f"[{name}/{rel}] {chunk}", name, rel, lang)
                count += 1
        except Exception: pass
    _indexed.add(name)
    logger.info("[RepoIntel] Indexed %d chunks from %s", count, name)
    return count

def _add(emb, idx, text, repo, file, lang):
    import numpy as np
    vec = emb.encode([text], convert_to_numpy=True).astype("float32")
    idx.add(vec); _chunks.append({"text":text,"repo":repo,"file":file,"lang":lang})

def _extract_structure(code: str, lang: str) -> str:
    lines = []
    if lang == "python":
        for m in re.finditer(r"^(class|def|async def)\s+(\w+)", code, re.MULTILINE):
            lines.append(f"{m.group(1)} {m.group(2)}")
    elif lang in ("javascript","typescript"):
        for m in re.finditer(r"(function\s+\w+|const\s+\w+\s*=|class\s+\w+|export\s+(default\s+)?(function|class)\s+\w*)", code, re.MULTILINE):
            lines.append(m.group(0)[:80])
    return " | ".join(lines[:20])

# ── Semantic Search ───────────────────────────────────────────────────────────
def search(query: str, top_k: int = 5) -> list[dict]:
    emb = _get_embedder(); idx = _get_index()
    if not emb or not idx or not _chunks: return []
    try:
        import numpy as np
        q = emb.encode([query], convert_to_numpy=True).astype("float32")
        k = min(top_k, len(_chunks))
        dists, idxs = idx.search(q, k)
        return [{**_chunks[i],"score":float(d)} for d,i in zip(dists[0],idxs[0]) if i<len(_chunks) and d<3.0]
    except Exception as e:
        logger.warning("[RepoIntel] Search error: %s", e); return []

# ── Code Parser (AST) ────────────────────────────────────────────────────────
def parse_python_file(file_path: str) -> dict:
    path = Path(file_path)
    if not path.exists() or path.suffix != ".py": return {"error": f"Not found: {file_path}"}
    try:
        source = path.read_text("utf-8", errors="replace"); tree = ast.parse(source)
        classes, functions, imports = [], [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append({"name":node.name,"methods":[m.name for m in ast.walk(node) if isinstance(m,ast.FunctionDef)],"line":node.lineno})
            elif isinstance(node, ast.FunctionDef):
                functions.append({"name":node.name,"line":node.lineno})
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom): imports.append(f"from {node.module}")
                else: imports.extend(a.name for a in node.names)
        return {"file":str(path),"classes":classes,"functions":functions[:20],"imports":list(set(imports))[:20],"lines":source.count("\n")}
    except SyntaxError as e: return {"file":str(path),"error":f"SyntaxError: {e}"}

# ── Repo Analyzer (GitHub API) ────────────────────────────────────────────────
def analyze_github_repo(repo_url: str) -> dict:
    m = re.search(r"github\.com/([^/]+)/([^/\?#]+)", repo_url)
    if not m: return {"error": f"Cannot parse: {repo_url}"}
    owner, repo = m.group(1), m.group(2).rstrip(".git")
    try:
        import urllib.request
        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1"
        req = urllib.request.Request(url, headers={"User-Agent":"Val-AI/13.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read()) if (import_json := __import__("json")) else {}
        files = [i["path"] for i in data.get("tree",[]) if i["type"]=="blob"]
        return {"repo":f"{owner}/{repo}","file_count":len(files),
            "patterns":_detect_patterns(files),"languages":_detect_langs(files)}
    except Exception as e: return {"repo":f"{owner}/{repo}","error":str(e)}

def _detect_patterns(files: list[str]) -> list[str]:
    detected = []; fl = [f.lower() for f in files]
    checks = [
        (["agent","brain","planner","executor"],"agent-loop"),
        (["tool","tools","registry"],"tool-registry"),
        (["memory","vector","faiss","embed"],"vector-memory"),
        (["router","routing"],"llm-routing"),
        (["socket","websocket","ws"],"websocket-streaming"),
        (["rag","retrieval","embedding"],"rag"),
        (["plugin","extension","addon"],"plugin-system"),
    ]
    for keywords, pattern in checks:
        if any(kw in f for f in fl for kw in keywords): detected.append(pattern)
    return detected

def _detect_langs(files: list[str]) -> dict[str,int]:
    langs: dict[str,int] = {}
    ext_map = {".py":"Python",".ts":"TypeScript",".js":"JavaScript",".go":"Go",".rs":"Rust"}
    for f in files:
        ext = Path(f).suffix.lower()
        if ext in ext_map: langs[ext_map[ext]] = langs.get(ext_map[ext],0)+1
    return langs

def get_status() -> dict:
    return {"indexed_repos":list(_indexed),"total_chunks":len(_chunks),
        "embedder_ready":_embedder is not None,"index_ready":_faiss_index is not None}

import json
