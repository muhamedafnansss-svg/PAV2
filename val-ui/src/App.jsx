import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar      from './components/Sidebar';
import SystemPanel  from './components/SystemPanel';
import VoiceOrb     from './components/VoiceOrb';
import TelemetryHUD from './components/TelemetryHUD';
import Chat         from './pages/Chat';
import Agents       from './pages/Agents';
import Workspace    from './pages/Workspace';
import Tools        from './pages/Tools';
import SOC          from './pages/SOC';
import OSINT        from './pages/OSINT';
import Models       from './pages/Models';
import Memory       from './pages/Memory';
import Settings     from './pages/Settings';
import DualPanel    from './pages/DualPanel';
import useValStore  from './store';

export default function App() {
  const startPolling = useValStore(s => s.startPolling);
  const stopPolling  = useValStore(s => s.stopPolling);

  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, []);

  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/"          element={<Chat />} />
            <Route path="/agents"    element={<Agents />} />
            <Route path="/workspace" element={<Workspace />} />
            <Route path="/tools"     element={<Tools />} />
            <Route path="/soc"       element={<SOC />} />
            <Route path="/osint"     element={<OSINT />} />
            <Route path="/models"    element={<Models />} />
            <Route path="/memory"    element={<Memory />} />
            <Route path="/settings"  element={<Settings />} />
            <Route path="/dual"      element={<DualPanel />} />
            <Route path="*"          element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <SystemPanel />

        {/* JARVIS Voice Orb — floating, always visible */}
        <VoiceOrb />

        {/* Telemetry HUD — top-right overlay */}
        <TelemetryHUD />
      </div>
    </BrowserRouter>
  );
}
