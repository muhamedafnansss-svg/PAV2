import { NavLink, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import useValStore from '../store';
import { useEffect, useCallback } from 'react';
import { getStatus } from '../api/client';

const NAV = [
  { path: '/',          icon: '◈',  label: 'Console',    section: 'CORE' },
  { path: '/agents',    icon: '⬢',  label: 'Agents',     section: 'CORE' },
  { path: '/workspace', icon: '⬡',  label: 'Workspace',  section: 'CORE' },
  { path: '/tools',     icon: '⚒',  label: 'Tools',      section: 'CORE' },
  { path: '/dual',      icon: '⚔',  label: 'Dual Panel', section: 'INTEL' },
  { path: '/soc',       icon: '⬟',  label: 'SOC',        section: 'INTEL', badge: 'threats' },
  { path: '/osint',     icon: '◉',  label: 'OSINT',      section: 'INTEL' },
  { path: '/memory',    icon: '◫',  label: 'Memory',     section: 'SYSTEM' },
  { path: '/models',    icon: '◆',  label: 'Models',     section: 'SYSTEM' },
  { path: '/settings',  icon: '◇',  label: 'Settings',   section: 'SYSTEM' },
];

export default function Sidebar() {
  const { online, modelLoaded, modelDevice, ramPct, socThreats, setOnline, setStatus, activeModel } = useValStore();

  const poll = useCallback(async () => {
    try {
      const s = await getStatus();
      setStatus(s);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, [setStatus, setOnline]);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 8000);
    return () => clearInterval(id);
  }, [poll]);

  // Group nav items by section
  const sections = [];
  let currentSection = null;
  for (const item of NAV) {
    if (item.section !== currentSection) {
      currentSection = item.section;
      sections.push({ section: item.section, items: [] });
    }
    sections[sections.length - 1].items.push(item);
  }

  const threatCount = socThreats.filter(t => ['CRITICAL','HIGH'].includes(t.severity)).length;

  return (
    <motion.aside
      className="sidebar"
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <div className="sidebar-logo">
        <div className="logo-title">VAL</div>
        <div className="logo-sub">JARVIS-Class AI Platform</div>
      </div>

      <nav className="sidebar-nav">
        {sections.map(({ section, items }) => (
          <div key={section}>
            <div className="nav-section">{section}</div>
            {items.map(item => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
              >
                <span className="nav-icon">{item.icon}</span>
                <span className="nav-label">{item.label}</span>
                {item.badge === 'threats' && threatCount > 0 && (
                  <span className="nav-badge">{threatCount}</span>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="status-dot">
          <div className={`dot ${online ? 'online' : 'offline'}`} />
          {online ? (
            <span style={{ fontSize: 10 }}>
              {activeModel ? activeModel.toUpperCase() : 'API'} · {modelDevice.toUpperCase()}
            </span>
          ) : (
            <span>OFFLINE</span>
          )}
        </div>
        {online && (
          <div className="status-dot" style={{ marginTop: 4 }}>
            <div className="dot warn" />
            <span style={{ fontSize: 9, color: 'var(--amber)', letterSpacing: '0.1em' }}>OPERATOR MODE</span>
          </div>
        )}
        {online && (
          <div className="progress-bar-wrap" style={{ marginTop: 8 }}>
            <div className="progress-label">
              <span>RAM</span>
              <span>{ramPct.toFixed(0)}%</span>
            </div>
            <div className="progress-track">
              <div
                className={`progress-fill ${ramPct > 85 ? 'red' : ramPct > 65 ? 'amber' : 'cyan'}`}
                style={{ width: `${ramPct}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </motion.aside>
  );
}
