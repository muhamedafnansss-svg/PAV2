import { useEffect, useCallback, useState } from 'react';
import { motion } from 'framer-motion';
import Header from '../components/Header';
import useValStore from '../store';
import { getModels, loadModel, unloadModel } from '../api/client';

export default function Models() {
  const { status } = useValStore();
  const [models, setModels]   = useState([]);
  const [loading, setLoading] = useState(false);
  const [action, setAction]   = useState('');
  const [message, setMessage] = useState('');
  const [error, setError]     = useState('');

  const fetchModels = useCallback(async () => {
    try {
      const data = await getModels();
      setModels(data.models || []);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { fetchModels(); }, [fetchModels]);

  const doLoad = async () => {
    setLoading(true); setAction('load'); setMessage(''); setError('');
    try {
      const r = await loadModel();
      setMessage(r.message);
      await fetchModels();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false); setAction('');
    }
  };

  const doUnload = async () => {
    setLoading(true); setAction('unload'); setMessage(''); setError('');
    try {
      const r = await unloadModel();
      setMessage(r.message);
      await fetchModels();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false); setAction('');
    }
  };

  const qwenModel = models[0];

  return (
    <div className="flex-col" style={{ height: '100%' }}>
      <Header title="MODELS — Model Registry" icon="◆" color="cyan" />
      <div className="page-body">

        {qwenModel && (
          <motion.div className="glass-card glow-cyan mb-4" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <div className="card-title flex items-center justify-between">
              <span>Qwen2.5-Coder-7B-Instruct</span>
              <span className="header-badge" style={{ color: qwenModel.loaded ? 'var(--green)' : 'var(--text-muted)', borderColor: qwenModel.loaded ? 'var(--green)' : 'var(--border)' }}>
                {qwenModel.loaded ? '● LOADED' : '○ UNLOADED'}
              </span>
            </div>

            <div className="grid-2 gap-4 mb-4">
              <div>
                {[
                  { label: 'Model ID',    val: 'qwen' },
                  { label: 'Architecture', val: 'Qwen2.5 (Transformer, ChatML)' },
                  { label: 'Context',     val: '32,768 tokens' },
                  { label: 'Parameters', val: '7.6 Billion' },
                  { label: 'Device',      val: qwenModel.device?.toUpperCase() || 'CPU' },
                  { label: 'Precision',   val: qwenModel.device === 'cuda' ? 'float16 + 4-bit NF4' : 'float32' },
                  { label: 'Load time',   val: qwenModel.load_time_s ? `${qwenModel.load_time_s}s` : 'N/A' },
                  { label: 'Requests',    val: qwenModel.requests || 0 },
                ].map(({ label, val }) => (
                  <div key={label} className="info-row">
                    <span>{label}</span>
                    <span className="val">{val}</span>
                  </div>
                ))}
              </div>

              <div>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', letterSpacing: '0.12em', marginBottom: 8, textTransform: 'uppercase' }}>
                  Model Path
                </div>
                <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--cyan)', wordBreak: 'break-all', padding: '8px', background: 'var(--bg-elevated)', borderRadius: 6, border: '1px solid var(--border-hi)' }}>
                  {qwenModel.path}
                </div>

                <div style={{ marginTop: 12, display: 'flex', gap: 6 }}>
                  {!qwenModel.loaded ? (
                    <motion.button className="btn btn-primary flex-1" onClick={doLoad} disabled={loading} whileTap={{ scale: 0.97 }}>
                      {loading && action === 'load' ? '⏳ Loading...' : '◆ Load Model'}
                    </motion.button>
                  ) : (
                    <motion.button className="btn btn-danger flex-1" onClick={doUnload} disabled={loading} whileTap={{ scale: 0.97 }}>
                      {loading && action === 'unload' ? '⏳ Unloading...' : '▢ Unload'}
                    </motion.button>
                  )}
                  <button className="btn btn-ghost" onClick={fetchModels}>↺</button>
                </div>

                {message && <div style={{ marginTop: 8, fontSize: 12, color: 'var(--green)' }}>✓ {message}</div>}
                {error   && <div style={{ marginTop: 8, fontSize: 12, color: 'var(--red)' }}>⚠ {error}</div>}
              </div>
            </div>

            {/* GPU note */}
            <div style={{ padding: '10px 14px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 6 }}>
              <div style={{ fontSize: 10, color: 'var(--amber)', fontFamily: 'var(--font-mono)', fontWeight: 700, marginBottom: 4 }}>
                INFERENCE NOTE
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                Qwen 2.5 Coder 7B uses 4-bit NF4 quantization on GPU (~4.5 GB VRAM).
                CPU fallback uses float32 and will be significantly slower.
                For best performance, ensure CUDA PyTorch and bitsandbytes are installed.
              </div>
            </div>
          </motion.div>
        )}

        <div className="glass-card">
          <div className="card-title">System Memory</div>
          {status && (
            <div className="flex-col gap-3">
              {[
                { label: 'RAM Used',  val: `${status.ram_gb} GB / ${status.ram_total_gb} GB`, pct: status.ram_pct, color: status.ram_pct > 85 ? 'red' : status.ram_pct > 65 ? 'amber' : 'green' },
                { label: 'CPU',       val: `${status.cpu_pct?.toFixed(1)}%`, pct: status.cpu_pct, color: status.cpu_pct > 80 ? 'amber' : 'cyan' },
              ].map(({ label, val, pct, color }) => (
                <div key={label}>
                  <div className="progress-label"><span>{label}</span><span>{val}</span></div>
                  <div className="progress-track"><div className={`progress-fill ${color}`} style={{ width: `${pct}%` }} /></div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
