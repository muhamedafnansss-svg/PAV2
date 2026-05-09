/**
 * VAL Zustand Store v7.0
 * Adds: securityMode, gpuStats, responseMode, live system polling
 */
import { create } from 'zustand';
import { getSystemStats, getGpuStats } from '../api/client';

const useValStore = create((set, get) => ({
  // ── Connection ────────────────────────────────────────────────────────────
  online:       false,
  connecting:   false,
  lastPing:     null,

  // ── System Status ─────────────────────────────────────────────────────────
  status:       null,
  modelLoaded:  false,
  modelDevice:  'cpu',
  ramPct:       0,
  cpuPct:       0,
  activeModel:  null,
  latencyMs:    null,

  // ── GPU ───────────────────────────────────────────────────────────────────
  gpuAvailable:   false,
  gpuName:        null,
  gpuPct:         0,
  gpuVramUsedGb:  0,
  gpuVramTotalGb: 0,
  gpuVramPct:     0,

  // ── Security Mode ─────────────────────────────────────────────────────────
  securityMode: 'SAFE',   // SAFE | POWER | LAB

  // ── Response Mode ─────────────────────────────────────────────────────────
  responseMode: 'brief',  // brief | deep

  // ── Chat ──────────────────────────────────────────────────────────────────
  messages:      [],
  isGenerating:  false,
  sessionId:     'val-session',

  // ── SOC ───────────────────────────────────────────────────────────────────
  socThreats:  [],
  socMetrics:  null,
  socIocs:     {},
  socReport:   '',
  socLoading:  false,

  // ── Logs / Memory ─────────────────────────────────────────────────────────
  systemLogs:  [],
  memoryStats: null,

  // ── Settings ──────────────────────────────────────────────────────────────
  settings: { streaming: true, maxTokens: 512, temperature: 0.4 },

  // ── Actions ───────────────────────────────────────────────────────────────
  setOnline:  (v) => set({ online: v }),

  setStatus: (s) => set({
    status:      s,
    modelLoaded: s?.model_loaded ?? false,
    modelDevice: s?.model_device ?? 'cpu',
    ramPct:      s?.ram_pct ?? 0,
    cpuPct:      s?.cpu_pct ?? 0,
    activeModel: s?.active_model ?? s?.loader_status?.active_model ?? null,
  }),

  setActiveModel:  (m)    => set({ activeModel: m }),
  setLatency:      (ms)   => set({ latencyMs: ms }),
  setSecurityMode: (mode) => set({ securityMode: mode.toUpperCase() }),
  setResponseMode: (mode) => set({ responseMode: mode }),

  setGpuStats: (g) => set({
    gpuAvailable:   g?.available ?? false,
    gpuName:        g?.name      ?? null,
    gpuVramUsedGb:  g?.vram_used_gb  ?? 0,
    gpuVramTotalGb: g?.vram_total_gb ?? 0,
    gpuVramPct:     g?.vram_pct      ?? 0,
  }),

  addMessage: (msg) => set((s) => ({
    messages: [...s.messages, { id: Date.now() + Math.random(), ...msg }],
  })),

  updateLastMessage: (patch) => set((s) => {
    const msgs = [...s.messages];
    if (msgs.length) msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...patch };
    return { messages: msgs };
  }),

  clearMessages:   () => set({ messages: [] }),
  setGenerating:   (v) => set({ isGenerating: v }),

  setSocData: (data) => set({
    socThreats: data.threats || [],
    socMetrics: data.metrics || null,
    socIocs:    data.iocs    || {},
    socReport:  data.report  || '',
    socLoading: false,
  }),
  setSocLoading:  (v) => set({ socLoading: v }),
  setMemoryStats: (s) => set({ memoryStats: s }),
  addLog: (log) => set((s) => ({ systemLogs: [...s.systemLogs.slice(-199), log] })),
  updateSettings: (patch) => set((s) => ({ settings: { ...s.settings, ...patch } })),

  // ── Live stats polling (call once at app mount) ───────────────────────────
  _pollInterval: null,

  startPolling: () => {
    const { _pollInterval } = get();
    if (_pollInterval) return;

    const poll = async () => {
      try {
        const [sys, gpu] = await Promise.allSettled([getSystemStats(), getGpuStats()]);
        if (sys.status === 'fulfilled') {
          const s = sys.value;
          set({
            online:      true,
            status:      s,
            modelLoaded: s?.model_loaded  ?? false,
            modelDevice: s?.model_device  ?? 'cpu',
            ramPct:      s?.ram_pct       ?? 0,
            cpuPct:      s?.cpu_pct       ?? 0,
            activeModel: s?.active_model  ?? null,
            lastPing:    Date.now(),
          });
        } else {
          set({ online: false });
        }
        if (gpu.status === 'fulfilled') {
          get().setGpuStats(gpu.value);
        }
      } catch {
        set({ online: false });
      }
    };

    poll();
    const id = setInterval(poll, 5000);
    set({ _pollInterval: id });
  },

  stopPolling: () => {
    const { _pollInterval } = get();
    if (_pollInterval) { clearInterval(_pollInterval); set({ _pollInterval: null }); }
  },
}));

export default useValStore;
