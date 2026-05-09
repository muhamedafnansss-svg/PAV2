import { useState } from 'react';
import { motion } from 'framer-motion';

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString('en', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function renderContent(text) {
  // Detect code blocks
  const CODE_RE = /```(\w+)?\n([\s\S]*?)```/g;
  const parts = [];
  let last = 0;
  let m;
  while ((m = CODE_RE.exec(text)) !== null) {
    if (m.index > last) parts.push({ type: 'text', content: text.slice(last, m.index) });
    parts.push({ type: 'code', lang: m[1] || 'txt', content: m[2] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ type: 'text', content: text.slice(last) });

  return parts.map((p, i) =>
    p.type === 'code' ? (
      <CodeBlock key={i} lang={p.lang} code={p.content} />
    ) : (
      <span key={i} style={{ whiteSpace: 'pre-wrap' }}>{p.content}</span>
    )
  );
}

function CodeBlock({ lang, code }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="code-block" style={{ display: 'block' }}>
      <div className="code-header">
        <span className="code-lang">{lang.toUpperCase()}</span>
        <button className="code-copy" onClick={copy}>{copied ? '✓ Copied' : 'Copy'}</button>
      </div>
      <pre>{code}</pre>
    </div>
  );
}

function TerminalBlock({ content, command }) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  const lines = content.split('\n');
  const isLong = lines.length > 30;
  const displayContent = isLong && !expanded ? lines.slice(0, 25).join('\n') + '\n...' : content;

  return (
    <div style={{
      background: '#0a0e14',
      border: '1px solid #1a3a2a',
      borderRadius: 8,
      overflow: 'hidden',
      fontFamily: 'var(--font-mono)',
      fontSize: 12,
    }}>
      {command && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '6px 12px', background: '#0d1a14', borderBottom: '1px solid #1a3a2a',
        }}>
          <span style={{ color: '#33ff88', fontSize: 10, fontWeight: 700, letterSpacing: '0.08em' }}>$ {command}</span>
          <button
            onClick={copy}
            style={{
              background: '#1a2a1a', border: '1px solid #2a4a2a',
              borderRadius: 4, padding: '2px 8px',
              color: '#66ff99', fontSize: 10, cursor: 'pointer',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {copied ? '✓' : 'Copy'}
          </button>
        </div>
      )}
      <div style={{
        padding: '12px 16px',
        color: '#33ff88',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
        lineHeight: 1.6,
        maxHeight: expanded ? 'none' : 500,
        overflow: 'auto',
        position: 'relative',
      }}>
        {!command && (
          <button
            onClick={copy}
            style={{
              position: 'absolute', top: 8, right: 8,
              background: '#1a2a1a', border: '1px solid #2a4a2a',
              borderRadius: 4, padding: '2px 8px',
              color: '#66ff99', fontSize: 10, cursor: 'pointer',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {copied ? '✓' : 'Copy'}
          </button>
        )}
        {displayContent}
      </div>
      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            display: 'block', width: '100%', padding: '4px',
            background: '#0d1a14', border: 'none', borderTop: '1px solid #1a3a2a',
            color: '#33ff88', fontSize: 10, cursor: 'pointer',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {expanded ? '▲ Collapse' : `▼ Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}

export default function ChatMessage({ message }) {
  const isAI   = message.role === 'assistant';
  const isUser = message.role === 'user';

  return (
    <motion.div
      className="chat-message"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
    >
      <div className={`msg-avatar ${isAI ? 'ai' : 'user'}`}>
        {isAI ? '◈' : '▢'}
      </div>
      <div className="msg-body">
        <div className="msg-meta">
          <span className={`msg-sender ${isAI ? 'ai' : 'user'}`}>
            {isAI ? 'VAL' : 'YOU'}
          </span>
          {message.timestamp && (
            <span className="msg-time">{formatTime(message.timestamp)}</span>
          )}
          {isAI && message.model && (
            <span className={`model-tag ${
              message.terminal ? 'terminal'
              : message.model === 'fast-path' ? 'fast-path'
              : ['nmap','whois','ping','traceroute','shodan','dig','hashcat','sqlmap','nikto','ffuf','gobuster'].includes(message.model) ? 'terminal'
              : message.model === 'mistral' ? 'mistral'
              : 'qwen'
            }`}>
              {message.terminal
                ? (message.model || 'TERMINAL').toUpperCase()
                : message.model === 'fast-path' ? 'INSTANT'
                : (message.model || 'LLM').toUpperCase()}
            </span>
          )}
          {isAI && message.latency && (
            <span style={{ fontSize: 9, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              {message.latency}s
            </span>
          )}
        </div>
        <div className={`msg-bubble ${isUser ? 'user-bubble' : ''}`}>
          {message.terminal && !message.streaming ? (
            <TerminalBlock content={message.content} command={message.command} />
          ) : message.streaming ? (
            <>
              {message.terminal ? <TerminalBlock content={message.content} command={message.command} /> : renderContent(message.content)}
              <span className="cursor" />
            </>
          ) : (
            renderContent(message.content)
          )}
        </div>
      </div>
    </motion.div>
  );
}

export function TypingIndicator() {
  return (
    <motion.div
      className="chat-message"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
    >
      <div className="msg-avatar ai">◈</div>
      <div className="msg-body">
        <div className="msg-meta">
          <span className="msg-sender ai">VAL</span>
          <span className="model-tag qwen">PROCESSING</span>
        </div>
        <div className="msg-bubble">
          <div className="typing-dots">
            <div className="typing-dot" />
            <div className="typing-dot" />
            <div className="typing-dot" />
          </div>
        </div>
      </div>
    </motion.div>
  );
}
