/**
 * VAL — Structured API Client
 * Uses relative URLs so Vite proxy handles routing to http://127.0.0.1:8765
 * No CORS issues.
 */

const BASE = '';  // Vite dev proxy forwards all /api-paths to the backend


async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Health & Status ──────────────────────────────────────────────────────────
export const getHealth  = () => request('/health');
export const getStatus  = () => request('/status');
export const getModels  = () => request('/models/status');
export const loadModel  = () => request('/models/load',  { method: 'POST' });
export const unloadModel= () => request('/models/unload',{ method: 'POST' });
export const selectModel= (model) => request('/models/select', {
  method: 'POST',
  body: JSON.stringify({ model }),
});

// ─── Chat ─────────────────────────────────────────────────────────────────────
export async function* streamChat({ message, sessionId = 'val-session', maxTokens = 512, temperature = 0.7 }) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, stream: true, max_tokens: maxTokens, temperature }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') return;
        try {
          yield JSON.parse(raw);
        } catch {
          // ignore malformed lines
        }
      }
    }
  }
}

export const queryChat = (message, sessionId = 'val-session') =>
  request('/query', {
    method: 'POST',
    body: JSON.stringify({ message, session_id: sessionId, stream: false }),
  });

export const resetSession = (sessionId = 'val-session') =>
  request('/memory/reset', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  });

// ─── Memory ───────────────────────────────────────────────────────────────────
export const getMemory = (sessionId = 'val-session') =>
  request(`/memory?session_id=${sessionId}`);

// ─── SOC ──────────────────────────────────────────────────────────────────────
export const socScan    = (logPath, text) =>
  request('/soc/scan', {
    method: 'POST',
    body: JSON.stringify({ log_path: logPath || 'PA/app.log', text: text || null }),
  });

export const socAnalyze = (text) =>
  request('/soc/analyze', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });

export const getSocMetrics = () => request('/soc/metrics');

// ─── OSINT ────────────────────────────────────────────────────────────────────
export const osintGather = (target) =>
  request('/osint/gather', {
    method: 'POST',
    body: JSON.stringify({ target }),
  });

// ─── Terminal ─────────────────────────────────────────────────────────────────
export const runTerminal = (command) =>
  request('/terminal', {
    method: 'POST',
    body: JSON.stringify({ command }),
  });

// ─── Voice Pipeline v15.0 ─────────────────────────────────────────────────────
export const getVoiceStatus = () => request('/voice/status');
export const voiceSpeak     = (text) =>
  request('/voice/speak', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
export const voiceInterrupt = () =>
  request('/voice/interrupt', { method: 'POST' });
export const voiceSetMode   = (mode) =>
  request('/voice/mode', {
    method: 'POST',
    body: JSON.stringify({ mode }),
  });
export const voiceAuthStatus = () => request('/voice/auth/status');
export const systemControl   = (command) =>
  request('/system/control', {
    method: 'POST',
    body: JSON.stringify({ command }),
  });

// ─── Logs ─────────────────────────────────────────────────────────────────────
export const getLogs = (category = 'system', tail = 50) =>
  request(`/logs/${category}?tail=${tail}`);

export const readLogs = getLogs;

// ─── Code Analysis (merged from PA) ───────────────────────────────────────────
export const analyzeCode = (path = '') =>
  request('/analyze', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });

// ─── Project Cleanup (merged from PA) ─────────────────────────────────────────
export const cleanupProject = (path = '', safeOnly = true) =>
  request('/cleanup', {
    method: 'POST',
    body: JSON.stringify({ path, safe_only: safeOnly }),
  });

// ─── Wiki Search (merged from PA) ─────────────────────────────────────────────
export const wikiSearch = (query) =>
  request('/wiki', {
    method: 'POST',
    body: JSON.stringify({ query }),
  });

// ─── Agent (merged from PA) ───────────────────────────────────────────────────
export const runAgent = (query, maxSteps = 8) =>
  request('/agent/run', {
    method: 'POST',
    body: JSON.stringify({ query, max_steps: maxSteps }),
  });

// ─── Firewall Builder (v14.0) ─────────────────────────────────────────────────
export const firewallAction = (text, execute = false) =>
  request('/firewall', {
    method: 'POST',
    body: JSON.stringify({ text, execute }),
  });

// ─── System Stats ─────────────────────────────────────────────────────────────
export const getSystemStats = () => request('/system').catch(() => null);
export const getGpuStats    = () => request('/gpu').catch(() => ({ available: false }));

// ─── Security Mode ────────────────────────────────────────────────────────────
export const setMode = (mode, sessionId = 'default') =>
  request('/mode', {
    method: 'POST',
    body: JSON.stringify({ mode, session_id: sessionId }),
  });

export const getMode = (sessionId = 'default') =>
  request(`/mode?session_id=${sessionId}`).catch(() => ({ mode: 'SAFE' }));

// ─── Model Switching ──────────────────────────────────────────────────────────
export const switchModel = (modelName) =>
  request('/models/select', {
    method: 'POST',
    body: JSON.stringify({ model: modelName }),
  });

// ─── Terminal ─────────────────────────────────────────────────────────────────
export const getTerminalAllowed = (sessionId = 'default') =>
  request(`/terminal/allowed?session_id=${sessionId}`).catch(() => ({ allowed: [] }));

// ─── Settings ─────────────────────────────────────────────────────────────────
export const updateSettings = (payload) =>
  request('/settings', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

// ─── Normalize Status ─────────────────────────────────────────────────────────
export function normalizeStatus(s) {
  return {
    activeModel:     s.active_model  || null,
    ramPct:          s.ram_pct       ?? 0,
    ramUsedGb:       s.ram_gb        ?? 0,
    ramFreeGb:       s.ram_free_gb   ?? 0,
    cpuPct:          s.cpu_pct       ?? 0,
    gpuVramUsedGb:   s.gpu_vram_used_gb  ?? 0,
    gpuVramTotalGb:  s.gpu_vram_total_gb ?? 0,
    gpuVramPct:      s.gpu_vram_pct      ?? 0,
    version:         s.val_version    || '?',
  };
}

// ─── SSE Callback-style streaming chat (used by Chat.jsx) ─────────────────────
let _inflight = false;
export const isInflight = () => _inflight;

export async function streamChatSSE(message, sessionId, options = {}, callbacks = {}) {
  if (_inflight) throw new Error('A request is already in progress');
  _inflight = true;
  const { onStatus, onMeta, onChunk, onDone } = callbacks;
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: sessionId, stream: true, ...options }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `Server error ${res.status}`);
    }
    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') return;
        try {
          const pkt = JSON.parse(raw);
          if (pkt.status && onStatus) onStatus(pkt.status);
          if (pkt.meta   && onMeta)   onMeta(pkt.meta);
          if (pkt.chunk  && onChunk)  onChunk(pkt.chunk, pkt);
          if (pkt.done   && onDone)   onDone(pkt);
          if (pkt.error)              throw new Error(pkt.error);
        } catch (e) {
          if (e.message && !e.message.startsWith('JSON')) throw e;
        }
      }
    }
  } finally { _inflight = false; }
}
