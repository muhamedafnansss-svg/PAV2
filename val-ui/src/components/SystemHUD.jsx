import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';

const SystemHUD = () => {
    const [metrics, setMetrics] = useState({ cpu: 0, ram: 0, vram: 0, tasks: 0 });

    useEffect(() => {
        // Poll the VAL backend for live metrics
        const fetchMetrics = async () => {
            try {
                const res = await fetch('http://127.0.0.1:8765/api/status');
                const data = await res.json();
                setMetrics({
                    cpu: data.cpu_pct || 0,
                    ram: data.ram_pct || 0,
                    vram: data.gpu_vram_pct || 0,
                    tasks: data.sessions_active || 0
                });
            } catch (e) {
                // Silently ignore if backend is down
            }
        };

        const interval = setInterval(fetchMetrics, 2000);
        return () => clearInterval(interval);
    }, []);

    const renderBar = (label, value, color) => (
        <div style={{ marginBottom: '8px', fontSize: '10px', fontFamily: 'monospace', color: '#888' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
                <span>{label}</span>
                <span style={{ color: color }}>{value.toFixed(1)}%</span>
            </div>
            <div style={{ width: '150px', height: '4px', background: '#222', borderRadius: '2px', overflow: 'hidden' }}>
                <motion.div 
                    initial={{ width: 0 }}
                    animate={{ width: `${value}%` }}
                    transition={{ duration: 0.5 }}
                    style={{ height: '100%', background: color }}
                />
            </div>
        </div>
    );

    return (
        <div style={{
            position: 'fixed',
            top: '20px',
            right: '20px',
            zIndex: 9998,
            background: 'rgba(10, 10, 15, 0.8)',
            backdropFilter: 'blur(10px)',
            border: '1px solid rgba(0, 255, 255, 0.1)',
            borderRadius: '8px',
            padding: '15px',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 4px 20px rgba(0,0,0,0.5)'
        }}>
            <div style={{ color: '#0ff', fontSize: '12px', letterSpacing: '2px', marginBottom: '15px', borderBottom: '1px solid rgba(0,255,255,0.2)', paddingBottom: '5px' }}>
                JARVIS TELEMETRY
            </div>
            {renderBar('INTEL CPU', metrics.cpu, '#00ffcc')}
            {renderBar('SYS RAM', metrics.ram, '#ffaa00')}
            {renderBar('RTX 4070 VRAM', metrics.vram, '#ff0055')}
            
            <div style={{ marginTop: '10px', fontSize: '10px', color: '#666', fontFamily: 'monospace', display: 'flex', justifyContent: 'space-between' }}>
                <span>ACTIVE TASKS:</span>
                <span style={{ color: '#0ff' }}>{metrics.tasks}</span>
            </div>
        </div>
    );
};

export default SystemHUD;
