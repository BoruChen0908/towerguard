// app.js — TowerGuard dashboard orchestrator.
// Wires the SSE stream to map / panels / advisory / briefing, and drives the
// header (UTC clock, airport code, connection dot) + DEGRADED banner.

import { connectSSE } from "./components/sse.js";
import { createMap } from "./components/map.js";
import { createPanels } from "./components/panels.js";
import { createAdvisoryRail } from "./components/advisory.js";
import { createBriefing } from "./components/briefing.js";
import { createLineage } from "./components/lineage.js";
import { createEventStrip } from "./components/eventstrip.js";
import { createAirportSwitcher } from "./components/airport.js";
import { utcClock } from "./components/format.js";

// ---- header refs ----
const clockEl = document.getElementById("utc-clock");
const connEl = document.getElementById("conn-indicator");
const connLabel = document.getElementById("conn-label");
const degradedBanner = document.getElementById("degraded-banner");

// ---- UTC clock (independent 1s ticker) ----
function tickClock() {
  clockEl.innerHTML = `${utcClock()}<span class="tg-clock-z">Z</span>`;
}
tickClock();
setInterval(tickClock, 1000);

// ---- airport-switch state ----
// While switching we hold the target ICAO; module/snapshot events for the OLD
// airport are ignored until the runner's next cycle reports the new airport.
let pendingAirport = null;

// ---- components ----
const mapView = createMap("map");

const panels = createPanels({
  onDegradedChange: (degraded) => {
    degradedBanner.hidden = !degraded;
  },
});

const advisoryRail = createAdvisoryRail(
  document.getElementById("advisory-rail"),
  document.getElementById("advisory-empty")
);

const briefing = createBriefing({
  btn: document.getElementById("briefing-btn"),
  scrim: document.getElementById("briefing-scrim"),
  panel: document.getElementById("briefing-panel"),
  body: document.getElementById("briefing-body"),
  closeBtn: document.getElementById("briefing-close"),
  confirmBtn: document.getElementById("briefing-confirm"),
});

createLineage({
  btn: document.getElementById("lineage-btn"),
  scrim: document.getElementById("lineage-scrim"),
  panel: document.getElementById("lineage-panel"),
  body: document.getElementById("lineage-body"),
  closeBtn: document.getElementById("lineage-close"),
});

const eventStrip = createEventStrip(
  document.getElementById("event-strip"),
  document.getElementById("event-strip-empty")
);

// lineage panel self-wires its button/scrim listeners; no further refs needed.

// ---- cross-module state: latest conflict pair drives map highlighting ----
let conflictPair = []; // callsigns of closest_pair, or []
let lastSnapshot = null;

function applyConflictToMap() {
  if (lastSnapshot) mapView.updateAircraft(lastSnapshot, conflictPair);
  mapView.setConflict(conflictPair);
}

// ---- airport switcher: drives the SWITCHING sequence on change ----
createAirportSwitcher({
  select: document.getElementById("airport-select"),
  onSwitch: (icao) => {
    pendingAirport = icao;
    mapView.recenterTo(icao);   // recenter + clear fleet immediately
    panels.setSwitching(true);  // neutral faint state until new-airport data
    conflictPair = [];
    lastSnapshot = null;
  },
});

// ---- connection state -> header dot ----
function setConnState(state) {
  connEl.dataset.state = state;
  connLabel.textContent =
    state === "open" ? "LIVE" : state === "connecting" ? "CONNECTING" : "DISCONNECTED";
}

// During a switch, drop module/snapshot events still tagged with the OLD
// airport. The first event carrying the new airport ends the switch; from then
// on panels.update() clears each panel's switching class as data flows in.
function staleDuringSwitch(data) {
  if (!pendingAirport) return false;
  if (data && data.airport === pendingAirport) {
    pendingAirport = null; // new-airport data arrived → switch complete
    return false;
  }
  return true; // old-airport data mid-switch → ignore
}

// ---- SSE event router ----
function onEvent(type, data) {
  switch (type) {
    case "traffic_density":
    case "workload_index":
      if (staleDuringSwitch(data)) break;
      panels.update(type, data);
      break;

    case "conflict_geometry": {
      if (staleDuringSwitch(data)) break;
      panels.update(type, data);
      // update conflict pair for the map; UNKNOWN/no-conflict clears it
      const cp = data.data_unavailable ? null : data.closest_pair;
      conflictPair = cp && Array.isArray(cp.callsigns) ? cp.callsigns : [];
      applyConflictToMap();
      break;
    }

    case "aircraft_snapshot":
      if (staleDuringSwitch(data)) break;
      lastSnapshot = data;
      applyConflictToMap();
      break;

    case "advisory":
      advisoryRail.handle(data);
      break;

    case "briefing":
      briefing.handle(data);
      break;

    case "shift_event":
      eventStrip.handle(data);
      break;

    default:
      console.warn("unhandled SSE type", type);
  }
}

// ---- connect ----
connectSSE({ onEvent, onState: setConnState });
