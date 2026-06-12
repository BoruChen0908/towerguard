// confirm.js — POST /confirm/{advisory_id} helper, shared by advisory + briefing

/**
 * Confirm an advisory. Resolves to the parsed response
 * `{ advisory_id, confirmed_at }` or throws on a non-OK / network error.
 */
export async function confirmAdvisory(advisoryId) {
  if (!advisoryId) throw new Error("missing advisory_id");

  const res = await fetch(`/confirm/${encodeURIComponent(advisoryId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    throw new Error(`confirm failed: HTTP ${res.status}`);
  }
  return res.json();
}
