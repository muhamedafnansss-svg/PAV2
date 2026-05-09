import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import Header from '../components/Header';
import { runTerminal } from '../api/client';

const ALLOWED = ['ls', 'dir', 'pwd', 'whoami', 'date', 'uptime', 'df', 'free', 'ps', 'echo', 'top', 'uname', 'hostname', 'ipconfig', 'ifconfig'];

const QUICK_CMDS = ['whoami', 'pwd', 'hostname', 'date', 'dir', 'ipconfig', 'echo Hello from JARVIS'];

export default function Tools() {
  const [cmd, setCmd]         = useState('');
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  const run = useCallback(async (command) => {
    const c = (command || cmd).trim();
    if (!c) return;
    setCmd('');
    setLoading(true);
    const entry = { cmd: c, output: '', blocked: false, ts: Date.now() };
    try {
      const data = await runTerminal(c);
      entry.output  = data.output;
      entry.blocked = data.blocked;
    } catch (e) {
      entry.output = `[ERROR] ${e.message}`;
    } finally {
      setHistory(h => [entry, ...h.slice(0, 29)]);
      setLoading(false);
    }
  }, [cmd]);

  return (
    <div className="flex-col" style={{ height: '100%' }}>
      <Header title="TOOLS — Safe Execution Engine" icon="⚙" color="amber" />
      <div className="page-body">
        <div className="grid-2 mb-4">
          <div className="glass-card">
            <div className="card-title">Terminal</div>
            <div className="terminal-block">
              <div className="terminal-header">
                <div className="terminal-dots">
                  <div className="terminal-dot td-r" />
                  <div className="terminal-dot td-y" />
                  <div className="terminal-dot td-g" />
                </div>
                <span className="terminal-title">JARVIS Safe Shell — Allowlisted Commands Only</span>
              </div>
              <div className="terminal-body">
                {history.length === 0 && <span style={{ color: 'var(--text-dim)' }}>$ ready</span>}
                {[...history].reverse().map((h, i) => (
                  <div key={i} style={{ marginBottom: 10 }}>
                    <div><span className="terminal-prompt">$ </span>{h.cmd}</div>
                    <div className={`terminal-output ${h.blocked ? 'text-red' : ''}`} style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>
                      {h.output}
                    </div>
                  </div>
                ))}
                {loading && <div style={{ color: 'var(--cyan)' }}>$ running...</div>}
              </div>
            </div>

            <div className="flex gap-2 items-center" style={{ marginTop: 10 }}>
              <input
                value={cmd}
                onChange={e => setCmd(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && run()}
                placeholder="Enter allowed command..."
                style={{
                  flex: 1, background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)',
                  borderRadius: 6, padding: '8px 12px', color: 'var(--text-base)', fontSize: 12,
                  fontFamily: 'var(--font-mono)', outline: 'none',
                }}
              />
              <button className="btn btn-primary" onClick={() => run()} disabled={loading || !cmd.trim()}>Run</button>
            </div>

            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', letterSpacing: '0.12em', marginBottom: 6 }}>QUICK COMMANDS</div>
              <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
                {QUICK_CMDS.map(c => (
                  <button
                    key={c}
                    className="btn btn-ghost"
                    style={{ fontSize: 10, padding: '3px 8px' }}
                    onClick={() => run(c)}
                    disabled={loading}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="glass-card">
            <div className="card-title">Allowed Commands</div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 12, fontFamily: 'var(--font-mono)' }}>
              Security policy: these commands are whitelisted for execution.
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {ALLOWED.map(c => (
                <span key={c} style={{
                  fontSize: 10, fontFamily: 'var(--font-mono)', padding: '3px 9px',
                  background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)',
                  borderRadius: 4, color: 'var(--green)',
                }}>
                  {c}
                </span>
              ))}
            </div>
            <div style={{ marginTop: 16, padding: '10px 14px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 6 }}>
              <div style={{ fontSize: 10, color: 'var(--red)', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>BLOCKED</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                rm, kill, shutdown, reboot, nmap, wget, curl, netcat, ssh, and all other commands are blocked by the security sandbox.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
