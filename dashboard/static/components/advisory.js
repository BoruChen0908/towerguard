// advisory.js — advisory rail: ESCALATE cards + confirm, SURFACE_CONFLICT styling.
// SUPPRESS advisories are never displayed.

import { confirmAdvisory, dismissAdvisory } from "./confirm.js";
import { safeTier } from "./format.js";

// Confirmed cards linger briefly (so the ✓ is visible), then fold into the
// shift-decision counter. Removal runs on a timer, not transitionend —
// animation is never load-bearing.
const COLLAPSE_DELAY_MS = 4000;
// Dismissed cards fold away faster: a rejection is acknowledged, not savored.
const DISMISS_COLLAPSE_DELAY_MS = 1500;
const COLLAPSE_ANIM_MS = 450;
// Unconfirmed cap: the mock publishes on a fixed timer; real Katherine is
// event-driven. Oldest cards drop out when the rail overflows.
const MAX_CARDS = 6;

export function createAdvisoryRail(railEl, emptyEl) {
  const cards = new Map(); // advisory_id -> card element
  let confirmedCount = 0;
  let dismissedCount = 0;

  const chip = document.createElement("div");
  chip.className = "tg-adv-confirmed-chip";
  chip.style.display = "none";
  railEl.appendChild(chip);

  function refreshEmpty() {
    if (emptyEl) emptyEl.style.display = cards.size === 0 ? "" : "none";
  }

  // Chip shows whichever counts are non-zero: "✓ N confirmed · ✕ M dismissed".
  // Each half is dropped when its count is 0; if both are 0 the chip hides.
  function refreshDecisionChip() {
    const parts = [];
    if (confirmedCount > 0) parts.push(`✓ ${confirmedCount} confirmed`);
    if (dismissedCount > 0) parts.push(`✕ ${dismissedCount} dismissed`);
    if (parts.length === 0) {
      chip.style.display = "none";
      return;
    }
    chip.textContent = parts.join(" · ");
    chip.style.display = "";
  }

  // `decision` ∈ {"confirm", "dismiss"} — drives which counter the folded card
  // feeds into.
  function collapseCard(id, card, decision) {
    if (!card.isConnected) return;
    card.classList.add("is-collapsing");
    setTimeout(() => {
      card.remove();
      if (id) cards.delete(id);
      if (decision === "dismiss") dismissedCount += 1;
      else confirmedCount += 1;
      refreshDecisionChip();
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
        <button class="tg-dismiss-btn" type="button">Dismiss</button>
      </div>
    `;

    const confirmBtn = card.querySelector(".tg-confirm-btn");
    const dismissBtn = card.querySelector(".tg-dismiss-btn");
    const foot = card.querySelector(".tg-adv-foot");
    const ctx = { confirmBtn, dismissBtn, foot, card, id: adv.advisory_id };
    confirmBtn.addEventListener("click", () => handleConfirm(ctx));
    dismissBtn.addEventListener("click", () => handleDismiss(ctx));

    return card;
  }

  // Once either decision lands, both buttons lock — a card is confirmed XOR
  // dismissed, never both.
  function lockButtons(ctx) {
    ctx.confirmBtn.disabled = true;
    ctx.dismissBtn.disabled = true;
  }

  function decided(ctx) {
    return (
      ctx.confirmBtn.classList.contains("is-confirmed") ||
      ctx.dismissBtn.classList.contains("is-dismissed")
    );
  }

  async function handleConfirm(ctx) {
    if (decided(ctx)) return;
    lockButtons(ctx);
    ctx.confirmBtn.classList.add("is-pending");
    ctx.confirmBtn.textContent = "Confirming…";
    try {
      const res = await confirmAdvisory(ctx.id);
      ctx.confirmBtn.classList.remove("is-pending");
      ctx.confirmBtn.classList.add("is-confirmed");
      ctx.confirmBtn.textContent = "✓ Confirmed";
      const ts = formatTs(res && res.confirmed_at);
      if (ts) {
        const span = document.createElement("span");
        span.className = "tg-confirm-ts";
        span.textContent = ts;
        ctx.foot.appendChild(span);
      }
      setTimeout(() => collapseCard(ctx.id, ctx.card, "confirm"), COLLAPSE_DELAY_MS);
    } catch (err) {
      console.error("confirm failed", err);
      ctx.confirmBtn.classList.remove("is-pending");
      ctx.confirmBtn.classList.add("is-error");
      ctx.confirmBtn.textContent = "Retry confirm";
      // re-open both so the controller can retry or switch to dismiss
      ctx.confirmBtn.disabled = false;
      ctx.dismissBtn.disabled = false;
    }
  }

  async function handleDismiss(ctx) {
    if (decided(ctx)) return;
    lockButtons(ctx);
    ctx.dismissBtn.classList.add("is-pending");
    ctx.dismissBtn.textContent = "Dismissing…";
    try {
      await dismissAdvisory(ctx.id);
      ctx.dismissBtn.classList.remove("is-pending");
      ctx.dismissBtn.classList.add("is-dismissed");
      ctx.dismissBtn.textContent = "✕ Dismissed";
      // card immediately reads as rejected (dimmed, desaturated), then folds
      ctx.card.classList.add("is-dismissed");
      setTimeout(
        () => collapseCard(ctx.id, ctx.card, "dismiss"),
        DISMISS_COLLAPSE_DELAY_MS,
      );
    } catch (err) {
      console.error("dismiss failed", err);
      ctx.dismissBtn.classList.remove("is-pending");
      ctx.dismissBtn.classList.add("is-error");
      ctx.dismissBtn.textContent = "Retry dismiss";
      ctx.confirmBtn.disabled = false;
      ctx.dismissBtn.disabled = false;
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
