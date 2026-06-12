// panels.js — three signal panels (traffic / conflict / workload)
// Owns tier rendering, DEGRADED state, secondary fields, and live age ticker.

import { safeTier, ageLabel, parseTs, num } from "./format.js";

const STALE_MS = 90 * 1000; // >90s since last update => stale styling

// Per-module: how to render the score line + secondary fields from the event.
const RENDERERS = {
  traffic_density: (e) => ({
    score: e.score === null || e.score === undefined ? "" : `score ${num(e.score, 2)}`,
    fields: [
      ["aircraft", num(e.aircraft_count)],
      ["spd var", `${num(e.speed_variance, 1)} kt`],
      ["alt var", `${num(e.altitude_variance)} ft`],
    ],
  }),
  conflict_geometry: (e) => {
    const cp = e.closest_pair;
    const fields = [["conflicts", num(e.conflicts_detected)]];
    if (cp && Array.isArray(cp.callsigns)) {
      fields.push(["closest", cp.callsigns.join(" / ")]);
      fields.push(["sep / ttv", `${num(cp.projected_separation_nm, 1)} nm / ${num(cp.time_to_violation_seconds)}s`]);
    } else {
      fields.push(["closest", "none"]);
    }
    return { score: `${num(e.pairs_checked)} pairs checked`, fields };
  },
  workload_index: (e) => ({
    score: e.score === null || e.score === undefined ? "" : `score ${num(e.score, 2)}`,
    fields: [
      ["staffed / rec", `${num(e.staffed_controllers)} / ${num(e.recommended_controllers)}`],
      ["freqs", num(e.active_frequencies)],
      ["handoffs/hr", num(e.handoff_rate_per_hour)],
    ],
  }),
};

export function createPanels({ onDegradedChange } = {}) {
  // module -> { el, tierEl, scoreEl, ageEl, fieldsEl, lastTsMs, tier }
  const state = {};

  for (const module of Object.keys(RENDERERS)) {
    const el = document.getElementById(`panel-${module}`);
    if (!el) continue;
    state[module] = {
      el,
      tierEl: el.querySelector('[data-role="tier"]'),
      scoreEl: el.querySelector('[data-role="score"]'),
      ageEl: el.querySelector('[data-role="age"]'),
      fieldsEl: el.querySelector('[data-role="fields"]'),
      lastTsMs: null,
      tier: null,
    };
  }

  function anyDegraded() {
    return Object.values(state).some((s) => s.tier === "UNKNOWN");
  }

  // ---- airport-switch neutral state ----
  // During a switch the old airport's tiers are meaningless but the feed is NOT
  // degraded — so we show a distinct faint "SWITCHING…" look, never the
  // DEGRADED grey-purple. setSwitching(true) freezes panels into that state;
  // the next module event for the new airport clears it (see update()).
  function setSwitching(on) {
    for (const s of Object.values(state)) {
      s.el.classList.toggle("is-switching", !!on);
      if (on) {
        s.tierEl.textContent = "SWITCHING…";
        s.scoreEl.textContent = "";
        s.fieldsEl.innerHTML = "";
        s.ageEl.textContent = "--";
        s.ageEl.classList.remove("is-stale");
      }
    }
  }

  function clearSwitching() {
    for (const s of Object.values(state)) s.el.classList.remove("is-switching");
  }

  function bump(node) {
    if (!node) return;
    node.classList.remove("t-bump");
    // force reflow so re-adding the class restarts the animation
    void node.offsetWidth;
    node.classList.add("t-bump");
  }

  function update(module, event) {
    const s = state[module];
    if (!s) return;

    // a real event for this panel resumes normal rendering after a switch
    s.el.classList.remove("is-switching");

    const tier = safeTier(event.tier);
    // Discipline: data_unavailable always forces DEGRADED regardless of tier.
    const effectiveTier = event.data_unavailable ? "UNKNOWN" : tier;

    s.el.setAttribute("data-tier", effectiveTier);
    s.tierEl.textContent = effectiveTier === "UNKNOWN" ? "DEGRADED" : effectiveTier;

    const render = RENDERERS[module](event);
    if (effectiveTier === "UNKNOWN") {
      // ::after CSS supplies the "sensor feed unavailable" note; keep text empty
      s.scoreEl.textContent = "";
      s.fieldsEl.innerHTML = "";
    } else {
      const prevScore = s.scoreEl.textContent;
      s.scoreEl.textContent = render.score;
      if (prevScore && prevScore !== render.score) bump(s.scoreEl);

      s.fieldsEl.innerHTML = render.fields
        .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
        .join("");
    }

    const wasDegraded = anyDegraded();
    s.tier = effectiveTier;
    s.lastTsMs = parseTs(event.timestamp) || Date.now();
    tickAge(); // refresh this panel's age immediately

    const nowDegraded = anyDegraded();
    if (nowDegraded !== wasDegraded && onDegradedChange) {
      onDegradedChange(nowDegraded);
    }
  }

  function tickAge() {
    const now = Date.now();
    for (const s of Object.values(state)) {
      if (s.lastTsMs == null) continue;
      s.ageEl.textContent = ageLabel(s.lastTsMs, now);
      const stale = now - s.lastTsMs > STALE_MS;
      s.ageEl.classList.toggle("is-stale", stale);
    }
  }

  // self-updating age ticker (1s); independent of any animation
  const timer = setInterval(tickAge, 1000);

  return {
    update,
    anyDegraded,
    setSwitching,
    clearSwitching,
    stop: () => clearInterval(timer),
  };
}
