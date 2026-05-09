import { useState, useRef, useEffect } from 'react';
import useEventBus from '../store/useEventBus';

const API = 'http://localhost:8765';

export default function BlueTeamPanel() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [socMetrics, setSocMetrics] = useState(null);
  const chatEndRef = useRef(null);
  const { blueEvents } = useEventBus();

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    fetch(`${API}/soc/metrics`).then(r => r.json()).then(setSocMetrics).catch(() => {});
    const iv = setInterval(() => {
      fetch(`${API}/soc/metrics`).then(r => r.json()).then(setSocMetrics).catch(() => {});
    }, 30000);
    return () => clearInterval(iv);
  }, []);

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
        body: JSON.stringify({ message: msg, stream: true, model: 'mistral' }),
      });

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let full = '';

      setMessages((p) => [...p, { role: 'assistant', text: '', model: 'mistral' }]);

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

  const runSocScan = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/soc/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tail_lines: 500 }),
      });
      const data = await res.json();
      setMessages((p) => [...p, {
        role: 'assistant',
        text: `**SOC Scan Complete**\n\n🔍 ${data.threat_count} threats found\n\n${data.report || 'No threats detected.'}`,
        model: 'soc-engine',
      }]);
    } catch (e) {
      setMessages((p) => [...p, { role: 'error', text: `SOC scan failed: ${e.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="dual-panel blue-panel">
      <div className="panel-header blue-header">
        <span className="panel-icon">🛡️</span>
        <h3>Blue Team — Defensive Ops</h3>
        <span className="panel-badge">Mistral · Tier 1</span>
      </div>

      {socMetrics && (
        <div className="soc-metrics-bar">
          <div className="metric"><span className="metric-val">{socMetrics.total || 0}</span><span className="metric-label">Total</span></div>
          <div className="metric critical"><span className="metric-val">{socMetrics.critical || 0}</span><span className="metric-label">Critical</span></div>
          <div className="metric high"><span className="metric-val">{socMetrics.high || 0}</span><span className="metric-label">High</span></div>
          <div className="metric medium"><span className="metric-val">{socMetrics.medium || 0}</span><span className="metric-label">Medium</span></div>
          <div className="metric"><span className="metric-val">{socMetrics.risk_score || 0}</span><span className="metric-label">Risk</span></div>
        </div>
      )}

      <div className="panel-events">
        {blueEvents.slice(-3).map((e, i) => (
          <div key={i} className="event-pill blue-event">
            <span className="event-type">{e.type}</span>
            <span className="event-data">{e.data?.tool || e.data?.model || ''}</span>
          </div>
        ))}
      </div>

      <div className="panel-chat">
        {messages.map((m, i) => (
          <div key={i} className={`panel-msg ${m.role}`}>
            <div className="msg-label">{m.role === 'user' ? '🔵 You' : m.role === 'error' ? '⚠️ Error' : '🛡️ Mistral'}</div>
            <div className="msg-text">{m.text}</div>
          </div>
        ))}
        {loading && <div className="panel-msg assistant"><div className="msg-text typing">Analyzing...</div></div>}
        <div ref={chatEndRef} />
      </div>

      <div className="panel-input">
        <button className="soc-scan-btn" onClick={runSocScan} disabled={loading}>🔍 SOC Scan</button>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="Analyze logs, triage threats, generate firewall rules..."
          disabled={loading}
        />
        <button onClick={send} disabled={loading}>
          {loading ? '⏳' : '🛡️'}
        </button>
      </div>
    </div>
  );
}
