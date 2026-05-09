import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import useValStore from '../store';

export default function TelemetryHUD() {
  const {
    online, activeModel, modelDevice, ramPct, cpuPct,
    gpuAvailable, gpuName, gpuVramPct, gpuVramUsedGb, gpuVramTotalGb,
    latencyMs, securityMode,
  } = useValStore();

  const [collapsed, setCollapsed] = useState(false);

  if (!online) return null;

  const GaugeMini = ({ value, color, label, max = 100 }) => {
    const pct = Math.min(Math.max(value, 0), max);
    const angle = (pct / max) * 180;
    return (
      <div className="hud-gauge">
        <svg viewBox="0 0 60 34" className="hud-gauge-svg">
          <path d="M 6 30 A 24 24 0 0 1 54 30" fill="none" stroke="var(--border-hi)" strokeWidth="3" strokeLinecap="round" />
          <path
            d="M 6 30 A 24 24 0 0 1 54 30"
            fill="none" stroke={color} strokeWidth="3" strokeLinecap="round"
            strokeDasharray={`${(pct / 100) * 75.4} 75.4`}
            style={{ filter: `drop-shadow(0 0 4px ${color})` }}
          />
        </svg>
        <div className="hud-gauge-val" style={{ color }}>{Math.round(pct)}%</div>
        <div className="hud-gauge-label">{label}</div>
      </div>
    );
  };

  const modeColors = { SAFE: 'var(--green)', POWER: 'var(--amber)', LAB: 'var(--red)' };

  return (
    <motion.div
      className={`telemetry-hud ${collapsed ? 'collapsed' : ''}`}
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.5 }}
    >
      <div className="hud-header" onClick={() => setCollapsed(p => !p)}>
        <span className="hud-dot" style={{ background: 'var(--green)', boxShadow: '0 0 6px var(--green)' }} />
        <span className="hud-title">TELEMETRY</span>
        <span className="hud-collapse">{collapsed ? '▸' : '▾'}</span>
      </div>

      {!collapsed && (
        <motion.div
          className="hud-body"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          transition={{ duration: 0.2 }}
        >
          <div className="hud-gauges">
            <GaugeMini value={cpuPct} color="var(--cyan)" label="CPU" />
            <GaugeMini value={ramPct} color={ramPct > 85 ? 'var(--red)' : 'var(--amber)'} label="RAM" />
            {gpuAvailable && (
              <GaugeMini value={gpuVramPct} color="var(--magenta)" label="GPU" />
            )}
          </div>

          <div className="hud-stats">
            <div className="hud-stat">
              <span className="hud-stat-label">MODEL</span>
              <span className="hud-stat-value" style={{ color: 'var(--cyan)' }}>
                {(activeModel || 'none').toUpperCase()}
              </span>
            </div>
            <div className="hud-stat">
              <span className="hud-stat-label">DEVICE</span>
              <span className="hud-stat-value">{modelDevice.toUpperCase()}</span>
            </div>
            <div className="hud-stat">
              <span className="hud-stat-label">MODE</span>
              <span className="hud-stat-value" style={{ color: modeColors[securityMode] || 'var(--text-muted)' }}>
                {securityMode}
              </span>
            </div>
            {latencyMs && (
              <div className="hud-stat">
                <span className="hud-stat-label">LATENCY</span>
                <span className="hud-stat-value" style={{ color: latencyMs < 200 ? 'var(--green)' : latencyMs < 800 ? 'var(--amber)' : 'var(--red)' }}>
                  {latencyMs}ms
                </span>
              </div>
            )}
            {gpuAvailable && (
              <div className="hud-stat">
                <span className="hud-stat-label">VRAM</span>
                <span className="hud-stat-value" style={{ color: 'var(--magenta)' }}>
                  {gpuVramUsedGb.toFixed(1)}/{gpuVramTotalGb.toFixed(1)}G
                </span>
              </div>
            )}
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}
