import { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import useValStore from '../store';
import { streamChatSSE, resetSession, setMode } from '../api/client';
import Header from '../components/Header';
import ChatMessage, { TypingIndicator } from '../components/ChatMessage';

// Mode cycling
const MODES = ['SAFE', 'POWER', 'LAB'];
const MODE_STYLE = {
  SAFE:  { color: 'var(--green)',   bg: 'var(--green-dim)',   label: '🟢 SAFE'  },
  POWER: { color: 'var(--amber)',   bg: 'var(--amber-dim)',   label: '🟡 POWER' },
  LAB:   { color: 'var(--red)',     bg: 'var(--red-dim)',     label: '🔴 LAB'   },
};

// Suggested commands
const SUGGESTED = [
  'nmap scanme.nmap.org',     'whois google.com',
  'ping 8.8.8.8',             'ps aux',
  'write a Python port scanner','what is CVE-2024-3094?',
  'show open ports',           'find all .py files',
  'show gpu usage',            'grep password recursively',
  'mode power',                'switch model qwen',
];

// Detect if input looks like a direct command
const CMD_RE = /^(nmap|ping|curl|wget|whois|dig|grep|ls|cat|ps|kill|find|hashcat|gobuster|ffuf|sqlmap|nikto|subfinder|traceroute|netstat|ss|ip|uname|whoami|top|df|free|docker|git|python|node|\$\s)/i;

export default function Chat() {
  const {
    messages, isGenerating, sessionId,
    addMessage, updateLastMessage, setGenerating,
    online, activeModel, securityMode, responseMode,
    setSecurityMode, setResponseMode, setLatency,
  } = useValStore();

  const [input,   setInput]   = useState('');
  const [error,   setError]   = useState('');
  const [status,  setStatus]  = useState('');
  const [cmdHistory, setCmdHistory] = useState([]);
  const [histIdx,    setHistIdx]    = useState(-1);
  const endRef     = useRef(null);
  const inputRef   = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = useCallback(async (text) => {
    const msg = (text ?? input).trim();
    if (!msg || isGenerating) return;
    setInput('');
    setError('');
    setStatus('');

    // Add to command history
    setCmdHistory(prev => {
      const next = [msg, ...prev.filter(c => c !== msg)].slice(0, 50);
      return next;
    });
    setHistIdx(-1);

    addMessage({ role: 'user', content: msg, timestamp: Date.now() });
    setGenerating(true);
    addMessage({ id: Date.now() + 1, role: 'assistant', content: '', streaming: true, timestamp: Date.now() });

    let accumulated = '';
    let modelUsed   = activeModel || 'mistral';
    let latency     = null;
    let isTerminal  = false;
    let msgMode     = null;
    const t0 = Date.now();

    try {
      await streamChatSSE(
        msg,
        sessionId,
        {
          response_mode: responseMode,
          model: CMD_RE.test(msg) ? undefined : undefined,
        },
        {
          onStatus: (s)      => setStatus(s),
          onMeta:   (meta)   => { if (meta?.model) modelUsed = meta.model; },
          onChunk:  (chunk, pkt) => {
            accumulated += chunk;
            if (pkt?.terminal) isTerminal = true;
            if (pkt?.mode)     msgMode    = pkt.mode;
            updateLastMessage({ content: accumulated, terminal: isTerminal });
          },
          onDone: (pkt) => {
            modelUsed = pkt.model_used || modelUsed;
            latency   = pkt.latency_s ? Math.round(pkt.latency_s * 1000) : null;
            if (pkt.mode) { setSecurityMode(pkt.mode); msgMode = pkt.mode; }
          },
        }
      );
    } catch (e) {
      setError(e.message || 'Connection error');
    } finally {
      if (latency) setLatency(latency);
      updateLastMessage({
        content:   accumulated || error || '…',
        streaming: false,
        model:     modelUsed,
        latency,
        terminal:  isTerminal,
        mode:      msgMode,
      });
      setGenerating(false);
      setStatus('');
      setTimeout(() => inputRef.current?.focus(), 80);
    }
  }, [input, isGenerating, sessionId, activeModel, responseMode]);

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    // Command history navigation
    if (e.key === 'ArrowUp' && cmdHistory.length > 0) {
      e.preventDefault();
      const next = Math.min(histIdx + 1, cmdHistory.length - 1);
      setHistIdx(next);
      setInput(cmdHistory[next]);
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (histIdx <= 0) { setHistIdx(-1); setInput(''); }
      else { const next = histIdx - 1; setHistIdx(next); setInput(cmdHistory[next]); }
    }
  };

  const handleClear = async () => {
    try { await resetSession(sessionId); } catch {}
    useValStore.getState().clearMessages();
  };

  const cycleMode = async () => {
    const next = MODES[(MODES.indexOf(securityMode) + 1) % MODES.length];
    try {
      await setMode(next, sessionId);
      setSecurityMode(next);
    } catch {}
  };

  const modeStyle = MODE_STYLE[securityMode] || MODE_STYLE.SAFE;

  return (
    <div className="chat-layout">
      <Header
        title="J.A.R.V.I.S. TERMINAL"
        icon="◈"
        sub={`${(activeModel || 'MODEL').toUpperCase()} · ${online ? 'ONLINE' : 'OFFLINE'}`}
        right={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {/* Response mode toggle */}
            <button
              className="mode-pill"
              onClick={() => setResponseMode(responseMode === 'brief' ? 'deep' : 'brief')}
              style={{ color: responseMode === 'deep' ? 'var(--cyan)' : 'var(--text-muted)',
                       borderColor: responseMode === 'deep' ? 'var(--cyan)' : 'var(--border-hi)' }}
              title="Toggle brief/deep response"
            >
              {responseMode === 'deep' ? '⬛ DEEP' : '▪ BRIEF'}
            </button>
          </div>
        }
      />

      {/* Thinking status bar */}
      <AnimatePresence>
        {isGenerating && status && (
          <motion.div
            key="status-bar"
            initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            className="status-bar"
          >
            <span className="spinner-tiny" /> {status}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Messages */}
      <div className="chat-messages" id="chat-window">
        <AnimatePresence>
          {messages.length === 0 && (
            <motion.div
              key="welcome"
              initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="welcome-screen"
            >
              <div className="welcome-glyph">◈</div>
              <div className="welcome-title">J.A.R.V.I.S. ONLINE</div>
              <div className="welcome-sub">
                {online
                  ? `${(activeModel || 'Model').toUpperCase()} ready — ${securityMode} Mode`
                  : 'Initializing JARVIS systems…'}
              </div>
              <div className="hint-grid">
                {SUGGESTED.map((s, i) => (
                  <motion.button
                    key={i}
                    whileHover={{ scale: 1.03, borderColor: 'var(--border-glow)' }}
                    whileTap={{ scale: 0.97 }}
                    className="hint-chip"
                    onClick={() => send(s)}
                  >
                    <span className="hint-chip-icon">{CMD_RE.test(s) ? '⌨' : '◆'}</span>
                    {s}
                  </motion.button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {messages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} />
        ))}

        {isGenerating && messages[messages.length - 1]?.content === '' && <TypingIndicator />}

        {error && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            className="error-bar">⚠ {error}</motion.div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input area */}
      <div className="chat-input-area">
        {messages.length > 0 && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
            <button className="btn btn-ghost" onClick={handleClear} style={{ fontSize: 10, padding: '3px 10px' }}>
              ✕ Clear
            </button>
          </div>
        )}
        <div className="input-row">
          {/* Mode badge */}
          <button
            className="mode-badge"
            style={{ color: modeStyle.color, background: modeStyle.bg, borderColor: modeStyle.color }}
            onClick={cycleMode}
            title={`Security mode: ${securityMode} — click to cycle`}
          >
            {modeStyle.label}
          </button>

          <textarea
            ref={inputRef}
            className="chat-input"
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = 'auto';
              e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px';
            }}
            onKeyDown={handleKey}
            placeholder="Ask anything or run: nmap target · whois domain · write python script · mode power"
            disabled={isGenerating}
            rows={1}
          />

          <motion.button
            className="send-btn"
            onClick={() => send()}
            disabled={!input.trim() || isGenerating}
            whileTap={{ scale: 0.9 }}
          >
            {isGenerating ? '⏸' : '↑'}
          </motion.button>
        </div>

        <div className="input-hint">
          {(activeModel || 'MODEL').toUpperCase()} · {online ? 'ONLINE' : 'OFFLINE'} · {securityMode} MODE · {responseMode.toUpperCase()}
        </div>
      </div>
    </div>
  );
}
