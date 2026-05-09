import { motion } from 'framer-motion';
import useValStore from '../store';

export default function Header({ title, icon, sub, color = 'cyan' }) {
  const { online, modelLoaded, cpuPct } = useValStore();

  return (
    <motion.div
      className="page-header"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      {icon && <span style={{ fontSize: 18, color: `var(--${color})` }}>{icon}</span>}
      <span className="page-title">{title}</span>

      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
        {sub && <span className="page-sub">{sub}</span>}

        <span
          className="header-badge"
          style={{ color: online ? 'var(--green)' : 'var(--text-muted)' }}
        >
          {online ? (modelLoaded ? 'QWEN READY' : 'LOADING') : 'OFFLINE'}
        </span>

        {online && (
          <span
            className="header-badge"
            style={{ color: 'var(--text-muted)' }}
          >
            CPU {cpuPct.toFixed(0)}%
          </span>
        )}
      </div>
    </motion.div>
  );
}
