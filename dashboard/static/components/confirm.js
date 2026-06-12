// confirm.js — advisory decision helpers (POST /confirm, /dismiss).
// confirmAdvisory is shared by advisory + briefing; dismissAdvisory is the
// advisory rail's reject path (briefing has only a sign-off, no dismiss).

/**
 * Confirm an advisory. Resolves to the parsed response
 * `{ advisory_id, confirmed_at }` or throws on a non-OK / network error.
 */
export async function confirmAdvisory(advisoryId) {
  return postDecision("confirm", advisoryId);
}

/**
 * Dismiss (reject) an advisory. Resolves to the parsed response
 * `{ advisory_id, dismissed_at }` or throws on a non-OK / network error.
 */
export async function dismissAdvisory(advisoryId) {
  return postDecision("dismiss", advisoryId);
}

async function postDecision(action, advisoryId) {
  if (!advisoryId) throw new Error("missing advisory_id");

  const res = await fetch(`/${action}/${encodeURIComponent(advisoryId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    throw new Error(`${action} failed: HTTP ${res.status}`);
  }
  return res.json();
}
