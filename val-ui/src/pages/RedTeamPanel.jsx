import { useState, useRef, useEffect } from 'react';
import useEventBus from '../store/useEventBus';

const API = 'http://localhost:8765';

export default function RedTeamPanel() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef(null);
  const { redEvents } = useEventBus();

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async () => {
    const msg = input.trim();
    if (!msg || loading) return;
    setInput('');
    setMessages((p) => [...p, { role: 'user', text: msg }]);
    setLoading(true);

    try {
      const res = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, stream: true, model: 'qwen' }),
      });

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let full = '';

      setMessages((p) => [...p, { role: 'assistant', text: '', model: 'qwen' }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = dec.decode(value);
        const lines = chunk.split('\n').filter((l) => l.startsWith('data: '));
        for (const line of lines) {
          const raw = line.slice(6);
          if (raw === '[DONE]') break;
          try {
            const d = JSON.parse(raw);
            if (d.chunk) {
              full += d.chunk;
              setMessages((p) => {
                const copy = [...p];
                copy[copy.length - 1] = { ...copy[copy.length - 1], text: full };
                return copy;
              });
            }
          } catch {}
        }
      }
    } catch (e) {
      setMessages((p) => [...p, { role: 'error', text: `Error: ${e.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="dual-panel red-panel">
      <div className="panel-header red-header">
        <span className="panel-icon">⚔️</span>
        <h3>Red Team — Offensive Ops</h3>
        <span className="panel-badge">Qwen · Tier 2</span>
      </div>

      <div className="panel-events">
        {redEvents.slice(-3).map((e, i) => (
          <div key={i} className="event-pill red-event">
            <span className="event-type">{e.type}</span>
            <span className="event-data">{e.data?.tool || e.data?.model || ''}</span>
          </div>
        ))}
      </div>

      <div className="panel-chat">
        {messages.map((m, i) => (
          <div key={i} className={`panel-msg ${m.role}`}>
            <div className="msg-label">{m.role === 'user' ? '🔴 You' : m.role === 'error' ? '⚠️ Error' : '🗡️ Qwen'}</div>
            <div className="msg-text">{m.text}</div>
          </div>
        ))}
        {loading && <div className="panel-msg assistant"><div className="msg-text typing">Generating exploit...</div></div>}
        <div ref={chatEndRef} />
      </div>

      <div className="panel-input">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="Generate exploit, craft payload, fuzz target..."
          disabled={loading}
        />
        <button onClick={send} disabled={loading}>
          {loading ? '⏳' : '⚔️'}
        </button>
      </div>
    </div>
  );
}
