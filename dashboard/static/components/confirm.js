// confirm.js — advisory decision helpers (POST /confirm, /dismiss, /reassess).
// confirmAdvisory is shared by advisory (as "Acknowledge") + briefing;
// dismissAdvisory and reassessAdvisory are advisory-rail-only paths.

/**
 * Acknowledge an advisory ("I see it / I've got it" — not agreement, not
 * resolution). Posts /confirm. Resolves to `{ advisory_id, confirmed_at }`
 * or throws on a non-OK / network error.
 */
export async function confirmAdvisory(advisoryId) {
  return postDecision("confirm", advisoryId);
}

/**
 * Dismiss (reject) an advisory as a false positive. `reason` is one of the
 * canned codes (already_separated | data_stale | visual_separation |
 * false_geometry | other) and is sent in the body when present. Resolves to
 * `{ advisory_id, dismissed_at }` or throws on a non-OK / network error.
 */
export async function dismissAdvisory(advisoryId, reason) {
  const body = reason ? { reason } : undefined;
  return postDecision("dismiss", advisoryId, body);
}

/**
 * Re-assess an advisory: ask the orchestrator to recompute from fresh sensor
 * data. Resolves to `{ advisory_id, request_id, requested_at }`. A 429 throws
 * a ReassessLimitError so the caller can lock the button distinctly from a
 * generic failure.
 */
export async function reassessAdvisory(advisoryId) {
  return postDecision("reassess", advisoryId);
}

/** Thrown when /reassess returns 429 (per-card re-assess limit reached). */
export class ReassessLimitError extends Error {
  constructor() {
    super("reassess_limit");
    this.name = "ReassessLimitError";
  }
}

async function postDecision(action, advisoryId, body) {
  if (!advisoryId) throw new Error("missing advisory_id");

  const res = await fetch(`/${action}/${encodeURIComponent(advisoryId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 429) {
    throw new ReassessLimitError();
  }
  if (!res.ok) {
    throw new Error(`${action} failed: HTTP ${res.status}`);
  }
  return res.json();
}
