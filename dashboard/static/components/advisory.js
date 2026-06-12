// advisory.js — advisory rail: ESCALATE cards + confirm, SURFACE_CONFLICT styling.
// SUPPRESS advisories are never displayed.

import { confirmAdvisory } from "./confirm.js";
import { safeTier } from "./format.js";

export function createAdvisoryRail(railEl, emptyEl) {
  const cards = new Map(); // advisory_id -> card element

  function refreshEmpty() {
    if (emptyEl) emptyEl.style.display = cards.size === 0 ? "" : "none";
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
    btn.addEventListener("click", () => handleConfirm(adv.advisory_id, btn, foot));

    return card;
  }

  async function handleConfirm(advisoryId, btn, foot) {
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
    if (emptyEl && railEl.firstChild !== emptyEl) {
      // keep empty placeholder out of the way
    }
    if (id) cards.set(id, card);
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
