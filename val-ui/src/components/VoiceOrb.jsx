import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import useValStore from '../store';

const API = 'http://localhost:8765';

// Voice states
const VSTATE = {
  IDLE: 'idle', LISTENING: 'listening', TRANSCRIBING: 'transcribing',
  PROCESSING: 'processing', SPEAKING: 'speaking', LOCKED: 'locked',
};

const STATE_CFG = {
  [VSTATE.IDLE]:         { color: 'rgba(0, 212, 255, 0.4)', glow: 'none',                          icon: '◎', label: 'Ready' },
  [VSTATE.LISTENING]:    { color: 'var(--red)', glow: '0 0 30px #ff3b6b88',            icon: '●', label: 'Listening...' },
  [VSTATE.TRANSCRIBING]: { color: 'var(--cyan)', glow: '0 0 20px #ffb80066',            icon: '◎', label: 'Transcribing...' },
  [VSTATE.PROCESSING]:   { color: 'var(--cyan)', glow: '0 0 30px #00d4ff66',            icon: '◈', label: 'Processing...' },
  [VSTATE.SPEAKING]:     { color: 'var(--cyan)', glow: '0 0 30px #00ff8c66',            icon: '◉', label: 'Speaking...' },
  [VSTATE.LOCKED]:       { color: 'var(--red)', glow: '0 0 20px #ff3b6b44',            icon: '⊘', label: 'Locked' },
};

export default function VoiceOrb() {
  const [voiceState, setVoiceState] = useState(VSTATE.IDLE);
  const [expanded, setExpanded] = useState(false);
  const [transcript, setTranscript] = useState([]);
  const [micActive, setMicActive] = useState(false);
  const [voiceMode, setVoiceMode] = useState('formal');

  // Audio refs
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const streamRef = useRef(null);
  const analyserRef = useRef(null);
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);

  const online = useValStore(s => s.online);

  // Cleanup
  useEffect(() => {
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
    };
  }, []);

  // Keyboard shortcut: Ctrl+Space = push-to-talk
  useEffect(() => {
    const handler = (e) => {
      if (e.ctrlKey && e.code === 'Space') {
        e.preventDefault();
        if (micActive) stopMic();
        else startMic();
      }
      if (e.altKey && e.code === 'KeyV') {
        e.preventDefault();
        setExpanded(prev => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [micActive]);

  // Waveform visualizer
  const drawWaveform = useCallback(() => {
    const canvas = canvasRef.current;
    const analyser = analyserRef.current;
    if (!canvas || !analyser) return;

    const ctx = canvas.getContext('2d');
    const bufLen = analyser.frequencyBinCount;
    const data = new Uint8Array(bufLen);

    const draw = () => {
      animFrameRef.current = requestAnimationFrame(draw);
      analyser.getByteTimeDomainData(data);

      ctx.fillStyle = 'rgba(5, 8, 18, 0.4)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const cfg = STATE_CFG[voiceState] || STATE_CFG[VSTATE.IDLE];
      ctx.lineWidth = 2;
      ctx.strokeStyle = cfg.color;
      ctx.shadowColor = cfg.color;
      ctx.shadowBlur = 8;
      ctx.beginPath();

      const sliceW = canvas.width / bufLen;
      let x = 0;
      for (let i = 0; i < bufLen; i++) {
        const v = data[i] / 128.0;
        const y = (v * canvas.height) / 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceW;
      }
      ctx.lineTo(canvas.width, canvas.height / 2);
      ctx.stroke();
      ctx.shadowBlur = 0;
    };
    draw();
  }, [voiceState]);

  // Start mic
  const startMic = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      analyserRef.current = analyser;

      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = () => handleRecordingDone();
      mediaRecorderRef.current = recorder;

      recorder.start();
      setMicActive(true);
      setVoiceState(VSTATE.LISTENING);
      drawWaveform();
    } catch (e) {
      console.error('Mic error:', e);
    }
  };

  // Stop mic
  const stopMic = () => {
    if (mediaRecorderRef.current?.state !== 'inactive') {
      mediaRecorderRef.current?.stop();
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    setMicActive(false);
  };

  // Handle recording complete
  const handleRecordingDone = async () => {
    setVoiceState(VSTATE.TRANSCRIBING);
    const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });

    try {
      const formData = new FormData();
      formData.append('audio', blob, 'recording.webm');
      const res = await fetch(`${API}/voice/transcribe`, { method: 'POST', body: formData });
      const data = await res.json();
      const userText = data.text || '';

      if (!userText.trim()) {
        setVoiceState(VSTATE.IDLE);
        return;
      }

      setTranscript(prev => [...prev, { role: 'user', text: userText }]);
      setVoiceState(VSTATE.PROCESSING);

      // Send to chat
      const chatRes = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userText, stream: false }),
      });
      const chatData = await chatRes.json();
      const valText = chatData.text || chatData.response || '';

      setTranscript(prev => [...prev, { role: 'assistant', text: valText }]);

      // Speak response
      if (valText) {
        setVoiceState(VSTATE.SPEAKING);
        await fetch(`${API}/voice/speak`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: valText }),
        });
        await new Promise(r => setTimeout(r, 2000));
      }

      setVoiceState(VSTATE.IDLE);
    } catch (e) {
      console.error('Voice pipeline error:', e);
      setVoiceState(VSTATE.IDLE);
    }
  };

  const toggleMic = () => {
    if (micActive) stopMic();
    else startMic();
  };

  const cfg = STATE_CFG[voiceState] || STATE_CFG[VSTATE.IDLE];
  const isActive = voiceState !== VSTATE.IDLE && voiceState !== VSTATE.LOCKED;

  return (
    <>
      {/* Floating Orb */}
      <motion.div
        id="voice-orb"
        className="voice-orb-floating"
        onClick={expanded ? undefined : toggleMic}
        onDoubleClick={() => setExpanded(prev => !prev)}
        animate={{
          boxShadow: isActive ? cfg.glow : '0 4px 20px rgba(0,0,0,0.4)',
          borderColor: cfg.color,
          scale: isActive ? 1.05 : 1,
        }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.92 }}
        style={{ borderColor: cfg.color }}
      >
        {/* Pulse ring */}
        {isActive && (
          <motion.div
            className="orb-pulse-ring"
            style={{ borderColor: cfg.color }}
            animate={{ scale: [1, 1.4, 1], opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
          />
        )}

        <span className="orb-icon" style={{ color: cfg.color }}>
          {micActive ? '⏹' : cfg.icon}
        </span>

        {/* State label */}
        {isActive && (
          <motion.div
            className="orb-label"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            style={{ color: cfg.color }}
          >
            {cfg.label}
          </motion.div>
        )}
      </motion.div>

      {/* Expanded Voice Overlay */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            className="voice-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
          >
            <div className="voice-overlay-inner">
              {/* Close */}
              <button
                className="voice-overlay-close"
                onClick={() => setExpanded(false)}
              >
                ✕
              </button>

              {/* Central Orb */}
              <motion.div
                className="voice-center-orb"
                onClick={toggleMic}
                animate={{
                  boxShadow: isActive ? `0 0 60px ${cfg.color}44, 0 0 120px ${cfg.color}22` : '0 0 40px rgba(0,212,255,0.1)',
                  borderColor: cfg.color,
                }}
                whileTap={{ scale: 0.92 }}
              >
                {isActive && (
                  <motion.div
                    className="center-pulse"
                    style={{ borderColor: cfg.color }}
                    animate={{ scale: [1, 1.3, 1], opacity: [0.5, 0, 0.5] }}
                    transition={{ duration: 2, repeat: Infinity }}
                  />
                )}
                <span style={{ fontSize: 40, color: cfg.color }}>{micActive ? '⏹' : '🎙'}</span>
              </motion.div>

              <div className="voice-state-label" style={{ color: cfg.color }}>
                {cfg.label}
              </div>

              {/* Waveform */}
              <div className="voice-waveform-wrap">
                <canvas ref={canvasRef} width={500} height={60} style={{ width: '100%', height: 60, borderRadius: 8 }} />
              </div>

              {/* Voice Mode Selector */}
              <div className="voice-mode-row">
                {['formal', 'tactical', 'friendly', 'silent'].map(m => (
                  <button
                    key={m}
                    className={`voice-mode-btn ${voiceMode === m ? 'active' : ''}`}
                    onClick={async () => {
                      setVoiceMode(m);
                      await fetch(`${API}/voice/mode`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ mode: m }),
                      });
                    }}
                  >
                    {m.toUpperCase()}
                  </button>
                ))}
              </div>

              {/* Transcript */}
              {transcript.length > 0 && (
                <div className="voice-transcript">
                  <div className="voice-transcript-header">
                    <span>Conversation</span>
                    <button onClick={() => setTranscript([])}>Clear</button>
                  </div>
                  <div className="voice-transcript-list">
                    {transcript.slice(-8).map((msg, i) => (
                      <div key={i} className={`voice-msg ${msg.role}`}>
                        <span className="voice-msg-role">
                          {msg.role === 'user' ? '🎙 YOU' : '◈ VAL'}
                        </span>
                        <span className="voice-msg-text">{msg.text}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="voice-hint">
                Ctrl+Space: Push-to-Talk · Alt+V: Toggle · Double-click orb: Expand
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
