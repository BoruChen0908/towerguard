// format.js — shared formatting helpers (pure, no DOM state)

export const TIERS = new Set(["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]);

/** Normalize a tier string to a known value; anything unexpected -> UNKNOWN
 *  so the UI fails safe (degraded), never silently green. */
export function safeTier(tier) {
  const t = String(tier || "").toUpperCase();
  return TIERS.has(t) ? t : "UNKNOWN";
}

/** Relative age label, e.g. "12s ago" / "3m 5s ago". */
export function ageLabel(fromMs, nowMs = Date.now()) {
  if (!fromMs) return "--";
  const secs = Math.max(0, Math.round((nowMs - fromMs) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}m ${s}s ago`;
}

/** Parse an ISO8601 timestamp to epoch ms; returns null on failure. */
export function parseTs(iso) {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

/** Two-digit zero pad. */
export function pad2(n) {
  return String(n).padStart(2, "0");
}

/** Current UTC HH:MM:SS. */
export function utcClock(d = new Date()) {
  return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}:${pad2(d.getUTCSeconds())}`;
}

/** Format a number for compact display; passes through non-numbers. */
export function num(v, digits = 0) {
  if (v === null || v === undefined || v === "") return "--";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toFixed(digits);
}
