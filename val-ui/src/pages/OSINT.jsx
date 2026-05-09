import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import Header from '../components/Header';
import { osintGather } from '../api/client';

export default function OSINT() {
  const [target, setTarget]   = useState('');
  const [result, setResult]   = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');

  const run = useCallback(async () => {
    if (!target.trim()) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const data = await osintGather(target.trim());
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [target]);

  return (
    <div className="flex-col" style={{ height: '100%' }}>
      <Header title="OSINT — Open Source Intelligence" icon="◉" color="magenta" />
      <div className="page-body">
        <div className="glass-card mb-4">
          <div className="card-title">Passive Intelligence Gathering</div>
          <div className="flex gap-2 items-center">
            <input
              value={target}
              onChange={e => setTarget(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && run()}
              placeholder="domain.com / 8.8.8.8 / https://target.org"
              style={{
                flex: 1, background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)',
                borderRadius: 8, padding: '10px 14px', color: 'var(--text-base)', fontSize: 13,
                fontFamily: 'var(--font-mono)', outline: 'none',
              }}
            />
            <motion.button
              className="btn btn-primary"
              onClick={run}
              disabled={loading || !target.trim()}
              whileTap={{ scale: 0.97 }}
            >
              {loading ? '⏳ Gathering...' : '◉ Gather'}
            </motion.button>
          </div>
          <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
            PASSIVE ONLY · No active scanning · WHOIS · DNS · HTTP headers · Geolocation
          </div>
        </div>

        {error && (
          <div className="mb-4" style={{ padding: '10px 14px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 8, color: 'var(--red)', fontSize: 12 }}>
            ⚠ {error}
          </div>
        )}

        {result && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <div className="glass-card mb-4">
              <div className="card-title flex items-center justify-between">
                <span>{result.target}</span>
                <span className="header-badge" style={{ color: 'var(--magenta)', borderColor: 'var(--magenta)' }}>
                  {result.type?.toUpperCase()}
                </span>
              </div>

              <div className="grid-2 gap-4">
                {result.whois && Object.keys(result.whois).length > 0 && (
                  <div>
                    <div style={{ fontSize: 9, color: 'var(--cyan)', fontFamily: 'var(--font-mono)', letterSpacing: '0.14em', marginBottom: 8, textTransform: 'uppercase' }}>WHOIS</div>
                    {Object.entries(result.whois).map(([k, v]) => (
                      <div key={k} className="info-row">
                        <span>{k.replace(/_/g, ' ')}</span>
                        <span className="val">{String(v).slice(0, 60)}</span>
                      </div>
                    ))}
                  </div>
                )}

                {result.dns && Object.keys(result.dns).length > 0 && !result.dns.error && (
                  <div>
                    <div style={{ fontSize: 9, color: 'var(--cyan)', fontFamily: 'var(--font-mono)', letterSpacing: '0.14em', marginBottom: 8, textTransform: 'uppercase' }}>DNS</div>
                    {Object.entries(result.dns).map(([rtype, records]) => (
                      <div key={rtype} className="info-row">
                        <span>{rtype}</span>
                        <span className="val">{Array.isArray(records) ? records.join(', ').slice(0, 60) : records}</span>
                      </div>
                    ))}
                  </div>
                )}

                {result.http && Object.keys(result.http).filter(k => result.http[k]).length > 0 && (
                  <div>
                    <div style={{ fontSize: 9, color: 'var(--cyan)', fontFamily: 'var(--font-mono)', letterSpacing: '0.14em', marginBottom: 8, textTransform: 'uppercase' }}>HTTP Headers</div>
                    {Object.entries(result.http).filter(([, v]) => v).map(([k, v]) => (
                      <div key={k} className="info-row">
                        <span>{k.replace(/_/g, ' ')}</span>
                        <span className="val">{String(v).slice(0, 60)}</span>
                      </div>
                    ))}
                  </div>
                )}

                {result.geo && Object.keys(result.geo).length > 0 && (
                  <div>
                    <div style={{ fontSize: 9, color: 'var(--cyan)', fontFamily: 'var(--font-mono)', letterSpacing: '0.14em', marginBottom: 8, textTransform: 'uppercase' }}>Geolocation</div>
                    {Object.entries(result.geo).map(([k, v]) => (
                      <div key={k} className="info-row">
                        <span>{k}</span>
                        <span className="val">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {result.report && (
              <div className="glass-card">
                <div className="card-title">Full Report</div>
                <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                  {result.report}
                </pre>
              </div>
            )}
          </motion.div>
        )}

        {!result && !loading && (
          <div className="empty-state">
            <div className="empty-icon">◉</div>
            <div className="empty-text">Enter a domain, IP, or URL to gather passive intelligence</div>
          </div>
        )}
      </div>
    </div>
  );
}
