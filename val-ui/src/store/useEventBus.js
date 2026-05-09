import { create } from 'zustand';

const API_BASE = 'http://localhost:8765';

const useEventBus = create((set, get) => ({
  events: [],
  connected: false,
  eventSource: null,
  redEvents: [],
  blueEvents: [],

  connect: () => {
    const state = get();
    if (state.eventSource) return;

    const es = new EventSource(`${API_BASE}/events/stream`);

    es.onopen = () => set({ connected: true });

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);
        set((s) => {
          const events = [...s.events.slice(-99), event];
          const isRed = ['tool.started', 'tool.completed', 'tool.failed', 'agent.step_completed'].includes(event.type);
          const isBlue = ['soc.threat_detected', 'soc.enrichment_complete', 'model.loading', 'model.ready'].includes(event.type);

          return {
            events,
            redEvents: isRed ? [...s.redEvents.slice(-49), event] : s.redEvents,
            blueEvents: isBlue ? [...s.blueEvents.slice(-49), event] : s.blueEvents,
          };
        });
      } catch {}
    };

    es.onerror = () => {
      set({ connected: false });
      setTimeout(() => {
        set({ eventSource: null });
        get().connect();
      }, 5000);
    };

    set({ eventSource: es });
  },

  disconnect: () => {
    const { eventSource } = get();
    if (eventSource) {
      eventSource.close();
      set({ eventSource: null, connected: false });
    }
  },

  clearEvents: () => set({ events: [], redEvents: [], blueEvents: [] }),
}));

export default useEventBus;
