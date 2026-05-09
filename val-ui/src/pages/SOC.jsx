import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import Header from '../components/Header';
import useValStore from '../store';
import { socScan, socAnalyze, getSocMetrics } from '../api/client';

const SEVERITY_COLOR = { CRITICAL: 'red', HIGH: 'amber', MEDIUM: 'cyan', LOW: 'green' };

export default function SOC() {
  const { socThreats, socMetrics, socIocs, socReport, socLoading, setSocData, setSocLoading } = useValStore();
  const [tab, setTab]         = useState('dashboard');
  const [scanText, setScanText] = useState('');
  const [logPath, setLogPath]  = useState('');
  const [error, setError]     = useState('');

  const runScan = useCallback(async () => {
    setSocLoading(true);
    setError('');
    try {
      const data = await socScan(logPath || undefined, undefined);
      setSocData(data);
      setTab('threats');
    } catch (e) {
      setError(e.message);
    } finally {
      setSocLoading(false);
    }
  }, [logPath, setSocData, setSocLoading]);

  const analyzeText = useCallback(async () => {
    if (!scanText.trim()) return;
    setSocLoading(true);
    setError('');
    try {
      const data = await socAnalyze(scanText);
      setSocData({ ...data, success: true });
      setTab('threats');
    } catch (e) {
      setError(e.message);
    } finally {
      setSocLoading(false);
    }
  }, [scanText, setSocData, setSocLoading]);

  const loadMetrics = useCallback(async () => {
    try {
      const m = await getSocMetrics();
      setSocData({ threats: socThreats, metrics: m, iocs: socIocs, report: socReport });
    } catch {}
  }, [socThreats, socIocs, socReport, setSocData]);

  const riskColor = !socMetrics ? 'text-muted'
    : socMetrics.risk_score >= 70 ? 'text-red'
    : socMetrics.risk_score >= 40 ? 'text-amber'
    : 'text-green';

  return (
    <div className="flex-col" style={{ height: '100%' }}>
      <Header title="SOC — Security Operations Center" icon="⬟" color="red" />

      <div className="page-body">
        {/* Metrics Row */}
        <div className="grid-2 mb-4">
          <div className="glass-card">
            <div className="card-title">Threat Overview</div>
            {socMetrics ? (
              <div className="metrics-grid">
                {[
                  { label: 'Total',    val: socMetrics.total,    color: 'cyan'   },
                  { label: 'Critical', val: socMetrics.critical, color: 'red'    },
                  { label: 'High',     val: socMetrics.high,     color: 'amber'  },
                  { label: 'Medium',   val: socMetrics.medium,   color: 'cyan'   },
                  { label: 'Low',      val: socMetrics.low,      color: 'green'  },
                ].map(({ label, val, color }) => (
                  <div key={label} className="metric-card">
                    <div className={`metric-value text-${color}`}>{val}</div>
                    <div className="metric-label">{label}</div>
                  </div>
                ))}
                <div className="metric-card">
                  <div className={`metric-value ${riskColor}`}>{socMetrics.risk_score}</div>
                  <div className="metric-label">Risk Score /100</div>
                </div>
              </div>
            ) : (
              <div className="empty-state" style={{ padding: '24px 0' }}>
                <div className="empty-text">Run a scan to see threat metrics</div>
              </div>
            )}
          </div>

          <div className="glass-card">
            <div className="card-title">Scan Controls</div>
            <div className="flex-col gap-3">
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, fontFamily: 'var(--font-mono)' }}>
                  LOG FILE PATH (optional)
                </div>
                <input
                  value={logPath}
                  onChange={e => setLogPath(e.target.value)}
                  placeholder="d:/PAV2/PA/app.log (leave empty for default)"
                  style={{
                    width: '100%', background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)',
                    borderRadius: 6, padding: '8px 12px', color: 'var(--text-base)', fontSize: 12,
                    fontFamily: 'var(--font-mono)', outline: 'none',
                  }}
                />
              </div>
              <div className="flex gap-2">
                <motion.button
                  className="btn btn-primary flex-1"
                  onClick={runScan}
                  disabled={socLoading}
                  whileTap={{ scale: 0.97 }}
                >
                  {socLoading ? '⏳ Scanning...' : '⬟ Scan Log File'}
                </motion.button>
                <motion.button
                  className="btn btn-ghost"
                  onClick={loadMetrics}
                  disabled={socLoading}
                  whileTap={{ scale: 0.97 }}
                >
                  ↺
                </motion.button>
              </div>

              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, fontFamily: 'var(--font-mono)' }}>
                  PASTE TEXT TO ANALYZE
                </div>
                <textarea
                  value={scanText}
                  onChange={e => setScanText(e.target.value)}
                  placeholder="Paste log lines, command output, or suspicious text..."
                  rows={4}
                  style={{
                    width: '100%', background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)',
                    borderRadius: 6, padding: '8px 12px', color: 'var(--text-base)', fontSize: 12,
                    fontFamily: 'var(--font-mono)', resize: 'vertical', outline: 'none',
                  }}
                />
                <motion.button
                  className="btn btn-ghost w-full"
                  style={{ marginTop: 8 }}
                  onClick={analyzeText}
                  disabled={socLoading || !scanText.trim()}
                  whileTap={{ scale: 0.97 }}
                >
                  ⬟ Analyze Text
                </motion.button>
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div className="mb-4" style={{ padding: '10px 14px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 8, color: 'var(--red)', fontSize: 12 }}>
            ⚠ {error}
          </div>
        )}

        {/* IOCs */}
        {Object.keys(socIocs).length > 0 && (
          <div className="glass-card mb-4">
            <div className="card-title">Indicators of Compromise (IOCs)</div>
            <div className="flex gap-4" style={{ flexWrap: 'wrap' }}>
              {Object.entries(socIocs).map(([type, vals]) => (
                <div key={type}>
                  <div style={{ fontSize: 9, color: 'var(--cyan)', fontFamily: 'var(--font-mono)', letterSpacing: '0.14em', marginBottom: 6, textTransform: 'uppercase' }}>
                    {type} ({vals.length})
                  </div>
                  {vals.slice(0, 5).map((v, i) => (
                    <div key={i} style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', padding: '2px 0' }}>{v}</div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Threats */}
        {socThreats.length > 0 && (
          <div className="glass-card">
            <div className="card-title flex items-center justify-between">
              <span>Detected Threats ({socThreats.length})</span>
              <div className="soc-severity">
                {['CRITICAL','HIGH','MEDIUM','LOW'].map(s => {
                  const count = socThreats.filter(t => t.severity === s).length;
                  return count > 0 && (
                    <span key={s} className={`sev-badge ${s}`}>{s} {count}</span>
                  );
                })}
              </div>
            </div>
            <div className="threat-list">
              {socThreats.map((t, i) => (
                <motion.div
                  key={i}
                  className={`threat-item ${t.severity}`}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.03 }}
                >
                  <div className="threat-desc">
                    <span className={`sev-badge ${t.severity}`} style={{ marginRight: 8 }}>{t.severity}</span>
                    {t.description}
                    {t.line_num && <span style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 8, fontFamily: 'var(--font-mono)' }}>line {t.line_num}</span>}
                  </div>
                  <div className="threat-match">{t.matched}</div>
                </motion.div>
              ))}
            </div>
          </div>
        )}

        {socThreats.length === 0 && !socLoading && socMetrics === null && (
          <div className="empty-state">
            <div className="empty-icon">⬟</div>
            <div className="empty-text">No scan results yet. Run a scan to detect threats.</div>
          </div>
        )}
      </div>
    </div>
  );
}
