// sse.js — EventSource wrapper with auto-reconnect + connection-state reporting

const EVENT_TYPES = [
  "traffic_density",
  "conflict_geometry",
  "workload_index",
  "advisory",
  "advisory_lifecycle",
  "aircraft_snapshot",
  "briefing",
  "shift_event",
];

/**
 * Connect to GET /events SSE.
 *
 * @param {object} cfg
 * @param {(type:string, data:any)=>void} cfg.onEvent  named-event handler
 * @param {(state:"connecting"|"open"|"closed")=>void} cfg.onState  conn state
 *
 * EventSource auto-reconnects natively; on each drop the browser fires
 * `onerror` (readyState CONNECTING) then retries. We surface that as
 * "closed" so the header dot goes red, and "open" again on recovery.
 */
export function connectSSE({ onEvent, onState }) {
  let es = null;

  const setState = (s) => {
    try { onState && onState(s); } catch (_) { /* never let UI cb break SSE */ }
  };

  const open = () => {
    setState("connecting");
    es = new EventSource("/events");

    es.onopen = () => setState("open");

    es.onerror = () => {
      // readyState: 0=CONNECTING (browser will retry), 2=CLOSED
      if (es.readyState === EventSource.CLOSED) {
        setState("closed");
        // Browser gave up; re-create after a short backoff.
        setTimeout(open, 3000);
      } else {
        setState("closed"); // dropped, native retry in flight
      }
    };

    for (const type of EVENT_TYPES) {
      es.addEventListener(type, (ev) => {
        let data;
        try {
          data = JSON.parse(ev.data);
        } catch (err) {
          console.warn(`SSE ${type}: bad JSON`, err);
          return; // drop malformed payload, keep connection
        }
        try {
          onEvent(type, data);
        } catch (err) {
          console.error(`handler error for ${type}`, err);
        }
      });
    }
  };

  open();

  return {
    close() {
      if (es) es.close();
      setState("closed");
    },
  };
}
