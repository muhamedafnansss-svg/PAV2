import { useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import Header from '../components/Header';
import useValStore from '../store';
import { getMemory, resetSession } from '../api/client';

export default function Memory() {
  const { memoryStats, sessionId, setMemoryStats } = useValStore();

  const load = useCallback(async () => {
    try {
      const data = await getMemory(sessionId);
      setMemoryStats(data);
    } catch {}
  }, [sessionId, setMemoryStats]);

  useEffect(() => { load(); const id = setInterval(load, 10000); return () => clearInterval(id); }, [load]);

  const handleReset = async () => {
    try {
      await resetSession(sessionId);
      useValStore.getState().clearMessages();
      load();
    } catch {}
  };

  return (
    <div className="flex-col" style={{ height: '100%' }}>
      <Header title="MEMORY — Session Context" icon="◫" color="cyan" />
      <div className="page-body">

        <div className="grid-2 mb-4">
          <div className="glass-card">
            <div className="card-title">Current Session</div>
            {memoryStats ? (
              <>
                {[
                  { label: 'Session ID',    val: memoryStats.session_id },
                  { label: 'Turns',         val: memoryStats.turn_count },
                  { label: 'Messages',      val: memoryStats.message_count },
                  { label: 'Active sessions', val: memoryStats.sessions_total },
                ].map(({ label, val }) => (
                  <div key={label} className="info-row"><span>{label}</span><span className="val">{val}</span></div>
                ))}
                <div style={{ marginTop: 14 }}>
                  <motion.button
                    className="btn btn-danger"
                    onClick={handleReset}
                    whileTap={{ scale: 0.97 }}
                  >
                    ✕ Clear Session Memory
                  </motion.button>
                </div>
              </>
            ) : (
              <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading...</div>
            )}
          </div>

          <div className="glass-card">
            <div className="card-title">Architecture Notes</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.8 }}>
              <div>◈ Max history per session: <strong style={{ color: 'var(--cyan)' }}>10 turns (20 messages)</strong></div>
              <div>◈ Storage: <strong style={{ color: 'var(--text-base)' }}>In-memory only</strong> (reset on server restart)</div>
              <div>◈ Multiple sessions supported concurrently</div>
              <div>◈ Qwen 2.5 receives last 10 turns as context window</div>
              <br />
              <div style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                PLANNED: Persistent vector memory via ChromaDB + sentence-transformers
              </div>
            </div>
          </div>
        </div>

        {memoryStats?.history?.length > 0 && (
          <div className="glass-card">
            <div className="card-title">Recent History</div>
            <div className="flex-col gap-2">
              {memoryStats.history.map((msg, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.04 }}
                  style={{
                    padding: '10px 14px',
                    background: 'var(--bg-elevated)',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    borderLeft: `3px solid ${msg.role === 'assistant' ? 'var(--cyan)' : 'var(--magenta)'}`,
                  }}
                >
                  <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: msg.role === 'assistant' ? 'var(--cyan)' : 'var(--magenta)', letterSpacing: '0.12em', marginBottom: 4 }}>
                    {msg.role.toUpperCase()}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {msg.content.slice(0, 200)}{msg.content.length > 200 ? '...' : ''}
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
