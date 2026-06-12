// advisory.js — advisory rail: ESCALATE cards + confirm, SURFACE_CONFLICT styling.
// SUPPRESS advisories are never displayed.

import { confirmAdvisory } from "./confirm.js";
import { safeTier } from "./format.js";

// Confirmed cards linger briefly (so the ✓ is visible), then fold into the
// "confirmed this shift" counter. Removal runs on a timer, not transitionend —
// animation is never load-bearing.
const COLLAPSE_DELAY_MS = 4000;
const COLLAPSE_ANIM_MS = 450;
// Unconfirmed cap: the mock publishes on a fixed timer; real Katherine is
// event-driven. Oldest cards drop out when the rail overflows.
const MAX_CARDS = 6;

export function createAdvisoryRail(railEl, emptyEl) {
  const cards = new Map(); // advisory_id -> card element
  let confirmedCount = 0;

  const chip = document.createElement("div");
  chip.className = "tg-adv-confirmed-chip";
  chip.style.display = "none";
  railEl.appendChild(chip);

  function refreshEmpty() {
    if (emptyEl) emptyEl.style.display = cards.size === 0 ? "" : "none";
  }

  function bumpConfirmedChip() {
    confirmedCount += 1;
    chip.textContent = `✓ ${confirmedCount} confirmed this shift`;
    chip.style.display = "";
  }

  function collapseCard(id, card) {
    if (!card.isConnected) return;
    card.classList.add("is-collapsing");
    setTimeout(() => {
      card.remove();
      if (id) cards.delete(id);
      bumpConfirmedChip();
      refreshEmpty();
    }, COLLAPSE_ANIM_MS);
  }

  function buildCard(adv) {
    const sev = safeTier(adv.severity);
    const isSurface = adv.action === "SURFACE_CONFLICT";

    const card = document.createElement("article");
    card.className = "tg-advisory-card t-slide-in";
    card.dataset.sev = sev;
    if (isSurface) card.classList.add("is-surface-conflict");

    const badge = adv.human_override_required
      ? `<span class="tg-adv-badge">HUMAN DECISION REQUIRED</span>`
      : "";

    card.innerHTML = `
      <div class="tg-adv-head">
        <span class="tg-adv-action">${adv.action || "ADVISORY"}</span>
        <span class="tg-adv-id">${adv.advisory_id || ""}</span>
        ${badge}
      </div>
      <div class="tg-adv-summary">${escapeHtml(adv.summary || "")}</div>
      <div class="tg-adv-attn">${escapeHtml(adv.recommended_attention || "")}</div>
      <div class="tg-adv-foot">
        <button class="tg-confirm-btn" type="button">Confirm</button>
      </div>
    `;

    const btn = card.querySelector(".tg-confirm-btn");
    const foot = card.querySelector(".tg-adv-foot");
    btn.addEventListener("click", () => handleConfirm(adv.advisory_id, btn, foot, card));

    return card;
  }

  async function handleConfirm(advisoryId, btn, foot, card) {
    if (btn.classList.contains("is-confirmed")) return;
    btn.disabled = true;
    btn.classList.add("is-pending");
    btn.textContent = "Confirming…";
    try {
      const res = await confirmAdvisory(advisoryId);
      btn.classList.remove("is-pending");
      btn.classList.add("is-confirmed");
      btn.textContent = "✓ Confirmed";
      const ts = formatTs(res && res.confirmed_at);
      if (ts) {
        const span = document.createElement("span");
        span.className = "tg-confirm-ts";
        span.textContent = ts;
        foot.appendChild(span);
      }
      setTimeout(() => collapseCard(advisoryId, card), COLLAPSE_DELAY_MS);
    } catch (err) {
      console.error("confirm failed", err);
      btn.classList.remove("is-pending");
      btn.classList.add("is-error");
      btn.textContent = "Retry confirm";
      btn.disabled = false;
    }
  }

  /** Handle an incoming advisory event. */
  function handle(adv) {
    if (!adv || adv.action === "SUPPRESS") return;

    const id = adv.advisory_id;
    // de-dupe: if we already show this advisory, leave its confirm state intact
    if (id && cards.has(id)) return;

    const card = buildCard(adv);
    // newest first
    railEl.insertBefore(card, railEl.firstChild === emptyEl ? null : railEl.firstChild);
    if (id) cards.set(id, card);

    // bound the rail: drop the oldest card once over the cap
    if (cards.size > MAX_CARDS) {
      const oldestId = cards.keys().next().value;
      const oldest = cards.get(oldestId);
      cards.delete(oldestId);
      if (oldest) oldest.remove();
    }
    refreshEmpty();
  }

  return { handle };
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function formatTs(iso) {
  if (!iso) return "";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return String(iso);
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}Z`;
}
