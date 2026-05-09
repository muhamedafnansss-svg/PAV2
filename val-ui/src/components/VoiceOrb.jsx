import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';

const VoiceOrb = () => {
    const [isListening, setIsListening] = useState(false);

    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.ctrlKey && e.code === 'Space') {
                e.preventDefault();
                setIsListening(true);
            }
        };

        const handleKeyUp = (e) => {
            if (e.code === 'Space') {
                setIsListening(false);
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        window.addEventListener('keyup', handleKeyUp);

        return () => {
            window.removeEventListener('keydown', handleKeyDown);
            window.removeEventListener('keyup', handleKeyUp);
        };
    }, []);

    return (
        <div style={{
            position: 'fixed',
            bottom: '40px',
            right: '40px',
            zIndex: 9999,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center'
        }}>
            <motion.div
                animate={{
                    scale: isListening ? [1, 1.2, 1] : 1,
                    boxShadow: isListening 
                        ? '0px 0px 30px 10px rgba(0, 255, 255, 0.6)' 
                        : '0px 0px 10px 2px rgba(0, 255, 255, 0.2)'
                }}
                transition={{
                    repeat: isListening ? Infinity : 0,
                    duration: 1.5
                }}
                style={{
                    width: '60px',
                    height: '60px',
                    borderRadius: '50%',
                    background: 'radial-gradient(circle, rgba(0,255,255,1) 0%, rgba(0,128,255,1) 100%)',
                    cursor: 'pointer',
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    border: '2px solid rgba(255,255,255,0.3)'
                }}
                onMouseDown={() => setIsListening(true)}
                onMouseUp={() => setIsListening(false)}
                onMouseLeave={() => setIsListening(false)}
            >
                {/* Inner core */}
                <motion.div 
                    animate={{ scale: isListening ? [1, 0.8, 1] : 1 }}
                    transition={{ repeat: isListening ? Infinity : 0, duration: 0.8 }}
                    style={{
                        width: '30px',
                        height: '30px',
                        borderRadius: '50%',
                        background: 'white',
                        opacity: 0.8
                    }}
                />
            </motion.div>
            <div style={{ marginTop: '10px', color: '#0ff', fontFamily: 'monospace', fontSize: '12px' }}>
                {isListening ? 'LISTENING...' : 'Ctrl+Space'}
            </div>
        </div>
    );
};

export default VoiceOrb;
