// eventstrip.js — thin single-row shift-event timeline above the advisory rail.
// Each shift_event becomes a compact chip: HH:MMZ + a kind-colored dot + a
// truncated summary (full summary on hover). Newest chip sits on the right and
// the strip auto-scrolls to it. Capped at MAX_CHIPS; oldest drop off the left.
//
// shift_event payload: { timestamp: ISO8601Z, kind, summary, ref|null }
// kind ∈ tier_change | advisory | briefing | airport_switch | confirm | dismiss
// Per-kind dot color is owned by CSS via data-kind (see style.css).

const MAX_CHIPS = 50;
const SUMMARY_MAX = 48; // chars before ellipsis on the inline label

// kinds we color explicitly; anything else falls back to a neutral dot.
const KNOWN_KINDS = new Set([
  "tier_change",
  "advisory",
  "briefing",
  "airport_switch",
  "confirm",
  "dismiss",
]);

export function createEventStrip(stripEl, emptyEl) {
  const chips = []; // chip elements, oldest-first (matches DOM left→right order)

  function refreshEmpty() {
    if (emptyEl) emptyEl.style.display = chips.length === 0 ? "" : "none";
  }

  function handle(ev) {
    if (!ev) return;

    const chip = buildChip(ev);
    stripEl.appendChild(chip); // newest on the right
    chips.push(chip);

    // bound the strip: drop the oldest (leftmost) chips over the cap
    while (chips.length > MAX_CHIPS) {
      const oldest = chips.shift();
      if (oldest) oldest.remove();
    }

    refreshEmpty();
    // auto-scroll to the newest chip on the right
    stripEl.scrollLeft = stripEl.scrollWidth;
  }

  return { handle };
}

function buildChip(ev) {
  const kind = KNOWN_KINDS.has(ev.kind) ? ev.kind : "unknown";
  const summary = String(ev.summary || "");
  const ts = formatHm(ev.timestamp);

  const chip = document.createElement("span");
  chip.className = "tg-event-chip t-slide-in";
  chip.dataset.kind = kind;
  chip.title = summary; // full summary on hover

  const time = document.createElement("span");
  time.className = "tg-event-chip-time";
  time.textContent = ts;

  const dot = document.createElement("span");
  dot.className = "tg-event-chip-dot";

  const label = document.createElement("span");
  label.className = "tg-event-chip-summary";
  label.textContent = truncate(summary, SUMMARY_MAX);

  chip.append(time, dot, label);
  return chip;
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

/** ISO8601Z -> "HH:MMZ" (UTC). Passes through unparseable input. */
function formatHm(iso) {
  if (!iso) return "--:--Z";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return String(iso);
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}Z`;
}
