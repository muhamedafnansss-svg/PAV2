import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import Header from '../components/Header';
import { runAgent } from '../api/client';

export default function Agents() {
  const [query, setQuery]     = useState('');
  const [result, setResult]   = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');

  const run = useCallback(async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await runAgent(query.trim(), 8);
      setResult(res);
    } catch (e) {
      setError(e.message || 'Agent failed');
    } finally {
      setLoading(false);
    }
  }, [query, loading]);

  return (
    <div className="page-layout">
      <Header title="REACT AGENT" icon="⬢" sub="Autonomous multi-step task execution" />

      <div style={{ padding: 24 }}>
        {/* Input */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 24 }}>
          <input
            className="chat-input"
            style={{ flex: 1, borderRadius: 8, padding: '12px 16px', fontSize: 14 }}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && run()}
            placeholder="agent: scan my project for security issues…"
            disabled={loading}
          />
          <motion.button
            className="btn btn-primary"
            onClick={run}
            disabled={!query.trim() || loading}
            whileTap={{ scale: 0.95 }}
            style={{ padding: '12px 24px', borderRadius: 8 }}
          >
            {loading ? '⏳ Running…' : '▶ Run Agent'}
          </motion.button>
        </div>

        {/* Error */}
        {error && <div className="error-bar" style={{ marginBottom: 16 }}>⚠ {error}</div>}

        {/* Results */}
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="card"
            style={{ padding: 20, background: 'var(--surface-1)', borderRadius: 12, border: '1px solid var(--border)' }}
          >
            {/* Summary */}
            <div style={{ display: 'flex', gap: 16, marginBottom: 16, fontSize: 12, color: 'var(--text-muted)' }}>
              <span>Steps: <strong style={{ color: 'var(--cyan)' }}>{result.total_steps}</strong></span>
              <span>Time: <strong style={{ color: 'var(--cyan)' }}>{result.total_ms?.toFixed(0)}ms</strong></span>
              <span>Status: {result.success
                ? <strong style={{ color: 'var(--green)' }}>✓ Success</strong>
                : <strong style={{ color: 'var(--red)' }}>✗ {result.error || 'Failed'}</strong>
              }</span>
            </div>

            {/* Steps */}
            {result.steps?.map((step, i) => (
              <div key={i} style={{
                padding: 12, marginBottom: 8, borderRadius: 8,
                background: step.is_final ? 'var(--green-dim)' : 'var(--surface-2)',
                border: `1px solid ${step.is_final ? 'var(--green)' : 'var(--border)'}`,
              }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                  Step {step.step} {step.is_final && '— FINAL'}
                </div>
                {step.thought && <div style={{ fontSize: 13, marginBottom: 4 }}>💭 {step.thought}</div>}
                {step.action && <div style={{ fontSize: 13, color: 'var(--amber)' }}>🔧 {step.action}</div>}
                {step.observation && (
                  <pre style={{
                    fontSize: 11, marginTop: 6, padding: 8, borderRadius: 6,
                    background: 'var(--bg-primary)', color: 'var(--text-secondary)',
                    maxHeight: 150, overflow: 'auto', whiteSpace: 'pre-wrap',
                  }}>{step.observation}</pre>
                )}
              </div>
            ))}

            {/* Final Answer */}
            {result.answer && (
              <div style={{
                marginTop: 16, padding: 16, borderRadius: 8,
                background: 'var(--surface-2)', border: '1px solid var(--cyan)',
              }}>
                <div style={{ fontSize: 11, color: 'var(--cyan)', marginBottom: 6 }}>ANSWER</div>
                <div style={{ fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{result.answer}</div>
              </div>
            )}
          </motion.div>
        )}

        {/* Empty state */}
        {!result && !loading && (
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>⬢</div>
            <div style={{ fontSize: 14 }}>Enter a task for the autonomous agent</div>
            <div style={{ fontSize: 12, marginTop: 8, opacity: 0.6 }}>
              The agent will Think → Act → Observe → Evaluate in up to 8 steps
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
