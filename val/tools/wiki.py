"""
VAL — Wikipedia + RAG Engine v13.0
Merged from PA/backend/wiki/wikipedia_engine.py + PA/backend/wiki/rag_engine.py.
Provides Wikipedia fetching with local caching and optional FAISS semantic retrieval.
Gracefully degrades if sentence-transformers/faiss are not installed.
"""
from __future__ import annotations
import hashlib, json, logging, re
from pathlib import Path
from val.utils.logger import get_logger, LogCategory

logger = get_logger("wiki", LogCategory.TOOL)

_embedder = None; _faiss_index = None; _chunks: list[dict] = []
_CACHE_DIR = Path("data/wiki_cache")

def _cache_path(q: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{hashlib.md5(q.lower().encode()).hexdigest()[:12]}.json"

# ── Wikipedia Fetch ───────────────────────────────────────────────────────────
def wiki_fetch(query: str, sentences: int = 5) -> str:
    cache = _cache_path(query)
    if cache.exists():
        try:
            data = json.loads(cache.read_text("utf-8"))
            return _format(data)
        except Exception: pass
    try:
        import wikipediaapi
        wiki = wikipediaapi.Wikipedia(language="en",
            extract_format=wikipediaapi.ExtractFormat.WIKI,
            user_agent="Val-AI/13.0")
        page = wiki.page(query)
        if not page.exists(): return _search_fallback(query)
        summary = ". ".join(page.summary.split(". ")[:sentences]).strip()
        if summary and not summary.endswith("."): summary += "."
        sections = {s.title: s.text[:500] for s in list(page.sections)[:5] if s.text}
        data = {"title":page.title,"summary":summary,"url":page.fullurl,"sections":sections}
        cache.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        return _format(data)
    except ImportError: return "Wikipedia library not installed. Run: pip install wikipedia-api"
    except Exception as e: return f"Wikipedia fetch failed: {e}"

def _search_fallback(query: str) -> str:
    try:
        import urllib.request, urllib.parse
        url = f"https://en.wikipedia.org/api/rest_v1/page/search/title?q={urllib.parse.quote(query)}&limit=3"
        req = urllib.request.Request(url, headers={"User-Agent": "Val-AI/13.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("pages"):
                p = data["pages"][0]
                return f"**{p.get('title',query)}**\n{p.get('excerpt','No excerpt.')}"
    except Exception: pass
    return f"No Wikipedia article found for '{query}'."

def _format(d: dict) -> str:
    lines = [f"**{d['title']}**\n", d["summary"], f"\n🔗 {d.get('url','')}"]
    for t, txt in list(d.get("sections", {}).items())[:3]:
        lines.append(f"\n**{t}:** {txt[:200].strip()}...")
    return "\n".join(lines)

# ── RAG (Optional FAISS) ─────────────────────────────────────────────────────
def _get_embedder():
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("[RAG] Embedder loaded: all-MiniLM-L6-v2")
        except ImportError:
            logger.debug("[RAG] sentence-transformers not installed — RAG disabled")
    return _embedder

def _get_index():
    global _faiss_index
    if _faiss_index is None:
        try:
            import faiss
            _faiss_index = faiss.IndexFlatL2(384)
        except ImportError:
            logger.debug("[RAG] faiss-cpu not installed — RAG disabled")
    return _faiss_index

def rag_add(text: str, source: str, url: str = "") -> bool:
    emb = _get_embedder(); idx = _get_index()
    if not emb or not idx: return False
    import numpy as np
    for chunk in [text[i:i+300].strip() for i in range(0, len(text), 300)]:
        if not chunk: continue
        vec = emb.encode([chunk], convert_to_numpy=True).astype("float32")
        idx.add(vec); _chunks.append({"text":chunk,"source":source,"url":url})
    return True

def rag_retrieve(query: str, top_k: int = 5) -> list[dict]:
    emb = _get_embedder(); idx = _get_index()
    if not emb or not idx or not _chunks: return []
    try:
        import numpy as np
        q = emb.encode([query], convert_to_numpy=True).astype("float32")
        k = min(top_k, len(_chunks))
        dists, idxs = idx.search(q, k)
        return [{**_chunks[i], "score":float(d)} for d, i in zip(dists[0], idxs[0])
                if i < len(_chunks) and d < 2.0]
    except Exception as e:
        logger.warning("[RAG] Retrieve error: %s", e); return []

def wiki_search(query: str) -> tuple[str, list[str]]:
    """Fetch Wikipedia, add to RAG index, retrieve relevant context."""
    text = wiki_fetch(query)
    rag_add(text, source=query, url=f"https://en.wikipedia.org/wiki/{query.replace(' ','_')}")
    results = rag_retrieve(query)
    if not results: return text[:1500], [f"https://en.wikipedia.org/wiki/{query.replace(' ','_')}"]
    ctx = "\n\n".join(r["text"] for r in results)
    cites = list({r.get("url") or f"Wikipedia: {r['source']}" for r in results})
    return ctx, cites

def rag_status() -> dict:
    return {"available": _get_embedder() is not None and _get_index() is not None,
            "chunks": len(_chunks)}
