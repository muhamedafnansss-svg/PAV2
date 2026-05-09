import { useState } from 'react';
import { motion } from 'framer-motion';
import Header from '../components/Header';
import useValStore from '../store';

export default function Settings() {
  const { settings, updateSettings, sessionId } = useValStore();
  const [saved, setSaved] = useState(false);

  const save = () => { setSaved(true); setTimeout(() => setSaved(false), 2000); };

  const Toggle = ({ value, onChange }) => (
    <div className={`toggle ${value ? 'on' : ''}`} onClick={() => onChange(!value)} />
  );

  return (
    <div className="flex-col" style={{ height: '100%' }}>
      <Header title="SETTINGS — System Configuration" icon="◇" color="cyan" />
      <div className="page-body">

        <div className="settings-group">
          <div className="settings-group-title">Inference</div>

          <div className="settings-row">
            <div>
              <div className="settings-label">Streaming Mode</div>
              <div className="settings-desc">Stream tokens as they generate (recommended)</div>
            </div>
            <Toggle value={settings.streaming} onChange={v => updateSettings({ streaming: v })} />
          </div>

          <div className="settings-row">
            <div>
              <div className="settings-label">Max Tokens</div>
              <div className="settings-desc">Maximum output length per response: {settings.maxTokens}</div>
            </div>
            <input
              type="range" min={64} max={2048} step={64}
              value={settings.maxTokens}
              onChange={e => updateSettings({ maxTokens: +e.target.value })}
              className="range-input"
            />
          </div>

          <div className="settings-row">
            <div>
              <div className="settings-label">Temperature</div>
              <div className="settings-desc">Creativity / randomness: {settings.temperature.toFixed(1)}</div>
            </div>
            <input
              type="range" min={0} max={1.5} step={0.1}
              value={settings.temperature}
              onChange={e => updateSettings({ temperature: +e.target.value })}
              className="range-input"
            />
          </div>
        </div>

        <div className="settings-group">
          <div className="settings-group-title">API Connection</div>
          <div className="settings-row">
            <div>
              <div className="settings-label">API Endpoint</div>
              <div className="settings-desc">JARVIS backend server address</div>
            </div>
            <input
              value={settings.apiBase}
              onChange={e => updateSettings({ apiBase: e.target.value })}
              style={{
                width: 240, background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)',
                borderRadius: 6, padding: '6px 10px', color: 'var(--text-base)', fontSize: 12,
                fontFamily: 'var(--font-mono)', outline: 'none',
              }}
            />
          </div>
          <div className="settings-row">
            <div>
              <div className="settings-label">Session ID</div>
              <div className="settings-desc">Current conversation session</div>
            </div>
            <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--cyan)' }}>{sessionId}</div>
          </div>
        </div>

        <div className="settings-group">
          <div className="settings-group-title">Platform Info</div>
          {[
            { label: 'JARVIS Version',   val: '9.0.0' },
            { label: 'Model',         val: 'Qwen2.5-Coder-7B-Instruct' },
            { label: 'Backend',       val: 'FastAPI + Uvicorn' },
            { label: 'Frontend',      val: 'React 19 + Vite + Zustand + Framer Motion' },
            { label: 'Modules',       val: 'Chat · SOC · OSINT · Voice · Tools · Memory' },
          ].map(({ label, val }) => (
            <div key={label} className="settings-row">
              <div className="settings-label">{label}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{val}</div>
            </div>
          ))}
        </div>

        <motion.button
          className="btn btn-primary"
          onClick={save}
          whileTap={{ scale: 0.97 }}
        >
          {saved ? '✓ Saved' : '◈ Save Settings'}
        </motion.button>
      </div>
    </div>
  );
}
