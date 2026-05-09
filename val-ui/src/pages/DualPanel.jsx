import { useEffect } from 'react';
import RedTeamPanel from './RedTeamPanel';
import BlueTeamPanel from './BlueTeamPanel';
import useEventBus from '../store/useEventBus';

export default function DualPanel() {
  const { connect, disconnect, connected } = useEventBus();

  useEffect(() => {
    connect();
    return () => disconnect();
  }, []);

  return (
    <div className="dual-panel-container">
      <div className="dual-panel-status">
        <span className={`bus-indicator ${connected ? 'connected' : 'disconnected'}`} />
        <span>Event Bus: {connected ? 'Connected' : 'Disconnected'}</span>
      </div>
      <div className="dual-panel-grid">
        <RedTeamPanel />
        <div className="panel-divider" />
        <BlueTeamPanel />
      </div>
    </div>
  );
}
