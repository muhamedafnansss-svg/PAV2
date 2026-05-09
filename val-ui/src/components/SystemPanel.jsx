/**
 * VAL SystemPanel — Right-side live stats panel
 * Shows: Model · CPU · RAM · GPU · VRAM · Mode · Latency
 */
import { useState } from 'react';
import useValStore from '../store';

const Bar = ({ pct, color = 'cyan' }) => (
  <div className="progress-track" style={{ marginTop: 4 }}>
    <div
      className={`progress-fill ${color}`}
      style={{ width: `${Math.min(pct, 100)}%` }}
    />
  </div>
);

const Stat = ({ label, value, pct, color, unit = '' }) => (
  <div className="sp-stat">
    <div className="sp-stat-row">
      <span className="sp-label">{label}</span>
      <span className="sp-value">{value}{unit}</span>
    </div>
    {pct !== undefined && <Bar pct={pct} color={color} />}
  </div>
);

const MODE_CFG = {
  SAFE:  { color: 'var(--green)',   label: '🟢 SAFE',  desc: 'Standard' },
  POWER: { color: 'var(--amber)',   label: '🟡 POWER', desc: 'Extended tools' },
  LAB:   { color: 'var(--red)',     label: '🔴 LAB',   desc: 'Unrestricted' },
};

export default function SystemPanel() {
  const [collapsed, setCollapsed] = useState(false);
  const {
    online, activeModel, modelDevice, modelLoaded,
    ramPct, ramUsedGb, cpuPct,
    gpuAvailable, gpuName, gpuVramPct, gpuVramUsedGb, gpuVramTotalGb,
    securityMode, latencyMs,
  } = useValStore();

  const mode = MODE_CFG[securityMode] || MODE_CFG.SAFE;

  if (collapsed) {
    return (
      <div className="sys-panel sys-panel--collapsed" onClick={() => setCollapsed(false)}>
        <span className="sp-expand-icon">◧</span>
      </div>
    );
  }

  return (
    <aside className="sys-panel">
      <div className="sp-header">
        <span className="sp-title">SYS</span>
        <button className="sp-collapse" onClick={() => setCollapsed(true)} title="Collapse">◨</button>
      </div>

      {/* Connection */}
      <div className="sp-section">
        <div className="sp-row">
          <span className={`sp-dot ${online ? 'sp-dot--online' : 'sp-dot--offline'}`} />
          <span className="sp-label">{online ? 'ONLINE' : 'OFFLINE'}</span>
        </div>
      </div>

      {/* Model */}
      <div className="sp-section">
        <div className="sp-section-title">MODEL</div>
        <div className="sp-model-name">
          {modelLoaded ? (activeModel || '—').toUpperCase() : 'NOT LOADED'}
        </div>
        <div className="sp-model-device">{modelDevice?.toUpperCase()}</div>
        {latencyMs != null && (
          <div className="sp-latency">{latencyMs}ms last response</div>
        )}
      </div>

      {/* CPU / RAM */}
      <div className="sp-section">
        <div className="sp-section-title">SYSTEM</div>
        <Stat label="CPU"  value={`${cpuPct.toFixed(0)}%`}  pct={cpuPct}  color={cpuPct > 80 ? 'red' : 'cyan'} />
        <Stat label="RAM"  value={`${ramPct.toFixed(0)}%`}  pct={ramPct}  color={ramPct > 85 ? 'red' : ramPct > 65 ? 'amber' : 'green'} />
      </div>

      {/* GPU */}
      {gpuAvailable && (
        <div className="sp-section">
          <div className="sp-section-title">GPU</div>
          <div className="sp-gpu-name">{gpuName || 'GPU'}</div>
          <Stat
            label="VRAM"
            value={`${gpuVramUsedGb}/${gpuVramTotalGb}GB`}
            pct={gpuVramPct}
            color={gpuVramPct > 90 ? 'red' : gpuVramPct > 70 ? 'amber' : 'magenta'}
          />
        </div>
      )}

      {/* Security Mode */}
      <div className="sp-section">
        <div className="sp-section-title">MODE</div>
        <div className="sp-mode-badge" style={{ color: mode.color, borderColor: mode.color }}>
          {mode.label}
        </div>
        <div className="sp-mode-desc">{mode.desc}</div>
      </div>
    </aside>
  );
}
