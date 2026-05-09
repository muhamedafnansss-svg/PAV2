import { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import Header from '../components/Header';
import { getVoiceStatus, voiceSpeak, queryChat } from '../api/client';

// Voice assistant states
const STATE = { IDLE: 'idle', LISTENING: 'listening', TRANSCRIBING: 'transcribing', THINKING: 'thinking', SPEAKING: 'speaking' };
const STATE_LABELS = {
  [STATE.IDLE]: '● Ready',
  [STATE.LISTENING]: '◉ Listening...',
  [STATE.TRANSCRIBING]: '◎ Transcribing...',
  [STATE.THINKING]: '◈ Thinking...',
  [STATE.SPEAKING]: '◉ Speaking...',
};
const STATE_COLORS = {
  [STATE.IDLE]: 'var(--text-muted)',
  [STATE.LISTENING]: 'var(--red)',
  [STATE.TRANSCRIBING]: 'var(--amber)',
  [STATE.THINKING]: 'var(--cyan)',
  [STATE.SPEAKING]: 'var(--green)',
};

export default function Voice() {
  const [status, setStatus]       = useState(null);
  const [text, setText]           = useState('');
  const [speaking, setSpeaking]   = useState(false);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState('');
  const [success, setSuccess]     = useState('');
  const [voiceState, setVoiceState] = useState(STATE.IDLE);
  const [transcript, setTranscript] = useState([]);
  const [micActive, setMicActive] = useState(false);

  // Audio refs
  const mediaRecorderRef = useRef(null);
  const audioChunksRef   = useRef([]);
  const canvasRef        = useRef(null);
  const analyserRef      = useRef(null);
  const animFrameRef     = useRef(null);
  const streamRef        = useRef(null);

  const load = useCallback(async () => {
    try {
      const s = await getVoiceStatus();
      setStatus(s);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
    };
  }, []);

  // Waveform visualizer
  const drawWaveform = useCallback(() => {
    const canvas = canvasRef.current;
    const analyser = analyserRef.current;
    if (!canvas || !analyser) return;

    const ctx = canvas.getContext('2d');
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    const draw = () => {
      animFrameRef.current = requestAnimationFrame(draw);
      analyser.getByteTimeDomainData(dataArray);

      ctx.fillStyle = 'rgba(10, 12, 16, 0.3)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.lineWidth = 2;
      ctx.strokeStyle = micActive ? '#ff4444' : '#00d4ff';
      ctx.beginPath();

      const sliceWidth = canvas.width / bufferLength;
      let x = 0;
      for (let i = 0; i < bufferLength; i++) {
        const v = dataArray[i] / 128.0;
        const y = (v * canvas.height) / 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceWidth;
      }
      ctx.lineTo(canvas.width, canvas.height / 2);
      ctx.stroke();
    };
    draw();
  }, [micActive]);

  // Start microphone capture
  const startMic = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // Setup analyser for waveform
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Setup recorder
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      audioChunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      mediaRecorder.onstop = () => handleRecordingStop();
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.start();
      setMicActive(true);
      setVoiceState(STATE.LISTENING);
      drawWaveform();
      setError('');
    } catch (e) {
      setError('Microphone access denied: ' + e.message);
    }
  };

  // Stop microphone
  const stopMic = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
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

  // Handle recording complete — send to backend
  const handleRecordingStop = async () => {
    setVoiceState(STATE.TRANSCRIBING);
    const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });

    try {
      // Send audio to transcribe endpoint
      const formData = new FormData();
      formData.append('audio', blob, 'recording.webm');
      const res = await fetch('/voice/transcribe', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Transcription failed');
      }

      const data = await res.json();
      const userText = data.text || '';

      if (!userText.trim()) {
        setVoiceState(STATE.IDLE);
        setError('No speech detected');
        return;
      }

      // Add to transcript
      setTranscript(prev => [...prev, { role: 'user', text: userText }]);

      // Send to VAL for response
      setVoiceState(STATE.THINKING);
      const valRes = await queryChat(userText);
      const valText = valRes.text || valRes.response || '';

      setTranscript(prev => [...prev, { role: 'assistant', text: valText }]);

      // Speak response
      if (status?.tts?.available && valText) {
        setVoiceState(STATE.SPEAKING);
        await voiceSpeak(valText);
        await new Promise(r => setTimeout(r, 2000));
      }

      setVoiceState(STATE.IDLE);
    } catch (e) {
      setError(e.message);
      setVoiceState(STATE.IDLE);
    }
  };

  // Toggle mic
  const toggleMic = () => {
    if (micActive) stopMic();
    else startMic();
  };

  // Manual TTS
  const speak = useCallback(async () => {
    if (!text.trim() || speaking) return;
    setSpeaking(true); setError(''); setSuccess('');
    try {
      const res = await voiceSpeak(text);
      if (!res.tts_available) setError('TTS not available. Install pyttsx3');
      else { setSuccess('Speaking...'); setTimeout(() => setSuccess(''), 3000); }
    } catch (e) { setError(e.message); }
    finally { setSpeaking(false); }
  }, [text, speaking]);

  return (
    <div className="flex-col" style={{ height: '100%' }}>
      <Header title="VOICE — Assistant Interface" icon="◎" color="magenta" />
      <div className="page-body">

        {/* Voice Assistant Control */}
        <motion.div className="glass-card glow-cyan mb-4" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <div className="card-title flex items-center justify-between">
            <span>Voice Assistant</span>
            <span style={{ fontSize: 11, color: STATE_COLORS[voiceState], fontFamily: 'var(--font-mono)' }}>
              {STATE_LABELS[voiceState]}
            </span>
          </div>

          {/* Waveform */}
          <div style={{ marginBottom: 16, borderRadius: 8, overflow: 'hidden', border: '1px solid var(--border-hi)', background: 'var(--bg-elevated)' }}>
            <canvas ref={canvasRef} width={600} height={80} style={{ width: '100%', height: 80, display: 'block' }} />
          </div>

          {/* Mic Button */}
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
            <motion.button
              onClick={toggleMic}
              disabled={voiceState === STATE.TRANSCRIBING || voiceState === STATE.THINKING}
              whileTap={{ scale: 0.92 }}
              style={{
                width: 72, height: 72, borderRadius: '50%',
                border: `2px solid ${micActive ? 'var(--red)' : 'var(--cyan)'}`,
                background: micActive ? 'rgba(255,68,68,0.15)' : 'var(--bg-elevated)',
                color: micActive ? 'var(--red)' : 'var(--cyan)',
                fontSize: 28, cursor: 'pointer', display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.2s ease',
                boxShadow: micActive ? '0 0 20px rgba(255,68,68,0.3)' : 'none',
              }}
            >
              {micActive ? '⏹' : '🎙'}
            </motion.button>
          </div>

          <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
            {micActive ? 'Click to stop recording' : 'Click to start voice input'}
          </div>

          {error && <div style={{ textAlign: 'center', color: 'var(--red)', fontSize: 12, marginTop: 8 }}>⚠ {error}</div>}
        </motion.div>

        {/* Voice Transcript */}
        {transcript.length > 0 && (
          <div className="glass-card mb-4">
            <div className="card-title flex items-center justify-between">
              <span>Conversation</span>
              <button className="btn btn-ghost" style={{ fontSize: 10 }} onClick={() => setTranscript([])}>Clear</button>
            </div>
            <div style={{ maxHeight: 250, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
              {transcript.map((msg, i) => (
                <div key={i} style={{
                  padding: '8px 12px', borderRadius: 8, fontSize: 12, lineHeight: 1.6,
                  background: msg.role === 'user' ? 'rgba(0,212,255,0.08)' : 'rgba(0,255,136,0.08)',
                  borderLeft: `3px solid ${msg.role === 'user' ? 'var(--cyan)' : 'var(--green)'}`,
                }}>
                  <div style={{ fontSize: 9, color: msg.role === 'user' ? 'var(--cyan)' : 'var(--green)', fontFamily: 'var(--font-mono)', marginBottom: 4, textTransform: 'uppercase' }}>
                    {msg.role === 'user' ? '🎙 You' : '◈ VAL'}
                  </div>
                  {msg.text}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Status Cards */}
        <div className="grid-2 mb-4">
          <div className="glass-card">
            <div className="card-title">STT — Speech to Text</div>
            {!loading && status && (
              <>
                <div className="flex items-center gap-3 mb-4">
                  <div style={{ width: 36, height: 36, borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18 }}>🎙</div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>Whisper ({status.stt?.model_size})</div>
                    <div style={{ fontSize: 11, color: status.stt?.available ? 'var(--green)' : 'var(--text-muted)' }}>
                      {status.stt?.available ? 'Loaded and ready' : 'Not installed'}
                    </div>
                  </div>
                  <div className={`dot ${status.stt?.available ? 'online' : 'offline'}`} style={{ marginLeft: 'auto' }} />
                </div>
                {!status.stt?.available && (
                  <div style={{ padding: '10px 14px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 6 }}>
                    <div style={{ fontSize: 10, color: 'var(--amber)', fontFamily: 'var(--font-mono)', marginBottom: 4 }}>INSTALL TO ACTIVATE</div>
                    <code style={{ fontSize: 11, color: 'var(--text-muted)' }}>pip install openai-whisper</code>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="glass-card">
            <div className="card-title">TTS — Text to Speech</div>
            {!loading && status && (
              <>
                <div className="flex items-center gap-3 mb-4">
                  <div style={{ width: 36, height: 36, borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18 }}>🔊</div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-bright)' }}>pyttsx3</div>
                    <div style={{ fontSize: 11, color: status.tts?.available ? 'var(--green)' : 'var(--text-muted)' }}>
                      {status.tts?.available ? 'System TTS ready' : 'Not installed'}
                    </div>
                  </div>
                  <div className={`dot ${status.tts?.available ? 'online' : 'offline'}`} style={{ marginLeft: 'auto' }} />
                </div>
                {!status.tts?.available && (
                  <div style={{ padding: '10px 14px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 6 }}>
                    <div style={{ fontSize: 10, color: 'var(--amber)', fontFamily: 'var(--font-mono)', marginBottom: 4 }}>INSTALL TO ACTIVATE</div>
                    <code style={{ fontSize: 11, color: 'var(--text-muted)' }}>pip install pyttsx3</code>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* TTS Test */}
        <div className="glass-card">
          <div className="card-title">Text-to-Speech Test</div>
          <div className="flex-col gap-3">
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder="Enter text for VAL to speak..."
              rows={4}
              style={{
                background: 'var(--bg-elevated)', border: '1px solid var(--border-hi)',
                borderRadius: 8, padding: '12px', color: 'var(--text-base)', fontSize: 13,
                fontFamily: 'var(--font-ui)', resize: 'vertical', outline: 'none', width: '100%',
              }}
            />
            {error   && <div style={{ color: 'var(--red)',   fontSize: 12 }}>⚠ {error}</div>}
            {success && <div style={{ color: 'var(--green)', fontSize: 12 }}>✓ {success}</div>}
            <motion.button
              className="btn btn-primary"
              onClick={speak}
              disabled={!text.trim() || speaking || !status?.tts?.available}
              whileTap={{ scale: 0.97 }}
              style={{ alignSelf: 'flex-start' }}
            >
              {speaking ? '🔊 Speaking...' : '🔊 Speak'}
            </motion.button>
          </div>
        </div>

        <div className="glass-card" style={{ marginTop: 16 }}>
          <div className="card-title">Roadmap</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.8 }}>
            <div>◈ <strong style={{ color: 'var(--cyan)' }}>Current:</strong> pyttsx3 TTS + Whisper STT + Mic capture + Voice loop UI</div>
            <div>◈ <strong style={{ color: 'var(--green)' }}>Ready:</strong> Microphone → Whisper → VAL (Qwen) → TTS output (full loop)</div>
            <div>◈ <strong style={{ color: 'var(--text-muted)' }}>Planned:</strong> Coqui TTS for neural voices</div>
            <div>◈ <strong style={{ color: 'var(--text-muted)' }}>Planned:</strong> Wake word detection ("Hey VAL")</div>
          </div>
        </div>
      </div>
    </div>
  );
}
