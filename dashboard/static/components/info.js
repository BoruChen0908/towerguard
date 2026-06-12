// info.js — region "ⓘ" help icons + a single shared popover.
//
// Every region header gets a quiet ⓘ button. Clicking one opens ONE shared
// popover (singleton) positioned next to that icon, populated from the content
// registry below. Esc, an outside click, or clicking the same icon again
// closes it. Content is English (judges read it): each entry is a short title
// plus 3–5 plain sentences covering what the region is, where its data comes
// from + cadence, the professional basis (lineage standard), and what the AI
// does / does not do.

// --- content registry: region key -> { title, body: [paragraphs] } ---
// Wording, figures, and paragraph numbers are taken verbatim from the design
// brief and have been verified against the lineage; do not embellish.
const CONTENT = {
  traffic_density: {
    title: "Traffic Density",
    body: [
      "Counts aircraft within 50 NM and combines that with speed and altitude variance into a single weighted score, then maps it to a tier.",
      "Tier thresholds follow §2a (demo-calibrated). Updated every 60 s from ADS-B.",
      "Fully deterministic — no LLM is involved in this signal.",
    ],
  },
  conflict_geometry: {
    title: "Conflict Geometry",
    body: [
      "Projects every aircraft pair forward 120 s under a constant-velocity assumption and solves analytically for the closest point of approach (CPA).",
      "A pair is flagged only when both conditions hold: horizontal separation < 3.0 NM AND vertical separation < 1000 ft (FAA JO 7110.65 ¶5-5-4 / ¶4-5-1).",
      "Tier is set by time to first violation: ≤60 s is CRITICAL, ≤90 s is HIGH.",
      "Lineage: STARS / ERAM Conflict Alert.",
    ],
  },
  workload_index: {
    title: "Workload Index",
    body: [
      "Built on real FAA staffing baselines — the Controller Workforce Plan 2025–28 facility table.",
      "Combines staffed-vs-recommended controller counts with mock frequency and handoff load into a score.",
      "Being staffing-aware is the point: the same traffic is heavier when a facility is short-staffed.",
    ],
  },
  map: {
    title: "Airspace Map",
    body: [
      "Shows live ADS-B positions. Between the 60 s snapshots, markers are advanced by client-side dead reckoning using the same constant-velocity assumption as the conflict module.",
      "A red dashed line connects a projected conflict pair.",
      "If data goes stale (>90 s) the display freezes — it never fabricates motion.",
    ],
  },
  advisory: {
    title: "Advisory Rail",
    body: [
      "Output of the Orchestrator agent (ESCALATE / SURFACE_CONFLICT). “HUMAN DECISION REQUIRED” marks the Parasuraman stage 1–2 boundary.",
      "Acknowledge means “I’ve got it”, not agreement; Dismiss requires a reason (false-positive ground truth); Re-assess recomputes from fresh sensor data only and is rate-limited.",
      "Advisories re-surface on a change in the world, never on the passage of time.",
    ],
  },
  shift_events: {
    title: "Shift Event Strip",
    body: [
      "A visualization of the towerguard:shift_events Redis Stream.",
      "This is the exact log the Narrator agent reads to draft the relief briefing.",
    ],
  },
  briefing: {
    title: "Position Relief Briefing",
    body: [
      "LLM-drafted from recorded events only — no prediction and no recommendation.",
      "The outgoing controller must review and sign it.",
      "It is a digital version of the FAA JO 7110.65 ¶2-1-24 position relief.",
    ],
  },
  airport: {
    title: "Airport Selector",
    body: [
      "Five airports, each backed by real FAA staffing data.",
      "Switching re-anchors monitoring to the new airport within seconds.",
    ],
  },
  connection: {
    title: "Connection / LIVE",
    body: [
      "Reflects the SSE stream state.",
      "DEGRADED policy: a fault is never displayed as a safe state.",
    ],
  },
};

let popover = null; // the single shared popover element
let openKey = null; // region key currently shown, or null
let openIcon = null; // the icon button that opened it (for re-click toggle)

function ensurePopover() {
  if (popover) return popover;
  popover = document.createElement("div");
  popover.className = "tg-info-pop";
  popover.setAttribute("role", "dialog");
  popover.hidden = true;
  document.body.appendChild(popover);

  // Outside click / Esc close. Registered once for the singleton.
  document.addEventListener("click", onDocClick, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openKey) closePopover();
  });
  return popover;
}

function onDocClick(e) {
  if (!openKey) return;
  // clicks on the popover itself or the owning icon are handled elsewhere
  if (popover.contains(e.target)) return;
  if (openIcon && openIcon.contains(e.target)) return;
  closePopover();
}

function renderContent(entry) {
  const paras = entry.body.map((p) => `<p>${escapeHtml(p)}</p>`).join("");
  return `<h4 class="tg-info-pop-title">${escapeHtml(entry.title)}</h4>${paras}`;
}

/** Position the popover next to its icon, clamped to the viewport. */
function positionPopover(icon) {
  const r = icon.getBoundingClientRect();
  // measure after content is set
  const pw = popover.offsetWidth;
  const ph = popover.offsetHeight;
  const margin = 8;
  // prefer below-left-aligned to the icon; flip up if it would overflow bottom
  let top = r.bottom + 6;
  if (top + ph > window.innerHeight - margin) {
    top = Math.max(margin, r.top - ph - 6);
  }
  let left = r.left;
  if (left + pw > window.innerWidth - margin) {
    left = Math.max(margin, window.innerWidth - margin - pw);
  }
  popover.style.top = `${Math.round(top)}px`;
  popover.style.left = `${Math.round(left)}px`;
}

function openPopover(key, icon) {
  const entry = CONTENT[key];
  if (!entry) return; // unknown region key — fail quiet, no popover
  ensurePopover();
  popover.innerHTML = renderContent(entry);
  popover.hidden = false;
  openKey = key;
  openIcon = icon;
  if (icon) icon.setAttribute("aria-expanded", "true");
  positionPopover(icon);
  // re-run once styles/reflow settle (fonts can change measured size)
  requestAnimationFrame(() => {
    if (openKey === key) positionPopover(icon);
  });
}

function closePopover() {
  if (!popover) return;
  popover.hidden = true;
  if (openIcon) openIcon.setAttribute("aria-expanded", "false");
  openKey = null;
  openIcon = null;
}

/**
 * Create an ⓘ icon button for region `key` and append it to `hostEl`.
 * Returns the button (caller may ignore it). No-op if the key has no content.
 */
export function attachInfoIcon(hostEl, key) {
  if (!hostEl || !CONTENT[key]) return null;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "tg-info-icon";
  btn.setAttribute("aria-label", `About ${CONTENT[key].title}`);
  btn.setAttribute("aria-expanded", "false");
  btn.textContent = "ⓘ"; // ⓘ
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (openKey === key && openIcon === btn) {
      closePopover(); // re-click toggles off
    } else {
      openPopover(key, btn);
    }
  });
  hostEl.appendChild(btn);
  return btn;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
