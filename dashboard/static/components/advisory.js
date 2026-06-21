// advisory.js — advisory rail: lifecycle-aware cards (Acknowledge / Dismiss /
// Re-assess), evidence panel, SURFACE_CONFLICT dual-column, supersession and
// lifecycle (resolved/superseded/expired) handling.
// SUPPRESS advisories are never displayed.

import {
  confirmAdvisory,
  dismissAdvisory,
  reassessAdvisory,
  ReassessLimitError,
} from "./confirm.js";
import { safeTier } from "./format.js";

// Acknowledged cards linger briefly (so the ✓ is visible), then fold into the
// shift-decision counter. Removal runs on a timer, not transitionend —
// animation is never load-bearing.
const COLLAPSE_DELAY_MS = 4000;
// Dismissed cards fold away faster: a rejection is acknowledged, not savored.
const DISMISS_COLLAPSE_DELAY_MS = 1500;
// Superseded / resolved cards: the controller should see the state change land
// before the card leaves.
const LIFECYCLE_COLLAPSE_DELAY_MS = 3000;
const COLLAPSE_ANIM_MS = 450;
// Contract constant: orchestrator must answer a re-assess within 10 s; past
// that the card is fail-safe — it stays, the button recovers.
const REASSESS_TIMEOUT_MS = 10000;
// Per-card re-assess cap (design §1 / §4).
const REASSESS_MAX = 2;
// Unconfirmed cap: oldest cards drop out when the rail overflows.
const MAX_CARDS = 6;

const DISMISS_REASONS = [
  ["already_separated", "Already separated"],
  ["data_stale", "Data stale"],
  ["visual_separation", "Visual separation"],
  ["false_geometry", "False geometry"],
  ["other", "Other"],
];

// confidence -> band label (design §2: never show the raw 0.92).
function confidenceBand(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  if (n >= 0.8) return { label: "HIGH", level: "high", value: n };
  if (n >= 0.5) return { label: "MED", level: "med", value: n };
  return { label: "LOW", level: "low", value: n };
}

export function createAdvisoryRail(railEl, emptyEl) {
  // advisory_id -> { card, adv, reassessCount, reassessReqId, reassessTimer, settled }
  const cards = new Map();
  // pending re-assess requests keyed by request_id, so an incoming advisory or
  // lifecycle event carrying in_response_to can clear the right card's spinner.
  const pendingReassess = new Map(); // request_id -> advisory_id
  let acknowledgedCount = 0;
  let dismissedCount = 0;

  const chip = document.createElement("div");
  chip.className = "tg-adv-confirmed-chip";
  chip.style.display = "none";
  railEl.appendChild(chip);

  function refreshEmpty() {
    if (emptyEl) emptyEl.style.display = cards.size === 0 ? "" : "none";
  }

  // Chip shows whichever counts are non-zero: "✓ N acknowledged · ✕ M dismissed".
  function refreshDecisionChip() {
    const parts = [];
    if (acknowledgedCount > 0) parts.push(`✓ ${acknowledgedCount} acknowledged`);
    if (dismissedCount > 0) parts.push(`✕ ${dismissedCount} dismissed`);
    if (parts.length === 0) {
      chip.style.display = "none";
      return;
    }
    chip.textContent = parts.join(" · ");
    chip.style.display = "";
  }

  // `decision` ∈ {"acknowledge", "dismiss", null}. null = lifecycle removal
  // (superseded/resolved/expired) which must NOT feed the ack/dismiss counters.
  function collapseCard(id, card, decision) {
    if (!card.isConnected) return;
    card.classList.add("is-collapsing");
    setTimeout(() => {
      card.remove();
      const entry = id ? cards.get(id) : null;
      if (entry && entry.reassessTimer) clearTimeout(entry.reassessTimer);
      if (id) cards.delete(id);
      if (decision === "dismiss") dismissedCount += 1;
      else if (decision === "acknowledge") acknowledgedCount += 1;
      refreshDecisionChip();
      refreshEmpty();
    }, COLLAPSE_ANIM_MS);
  }

  // ---- evidence / confidence rendering (pure HTML; data optional) ----

  function tierDot(tier) {
    const t = safeTier(tier);
    return `<span class="tg-sig-dot" data-tier="${t}"></span>`;
  }

  function buildSignalChips(signals) {
    if (!Array.isArray(signals) || signals.length === 0) return "";
    const chips = signals
      .map((s) => {
        const t = safeTier(s.tier);
        const label = escapeHtml(s.event_type || s.alert_id || "signal");
        return `<span class="tg-sig-chip" data-tier="${t}">${tierDot(t)}${label}</span>`;
      })
      .join("");
    return `<div class="tg-adv-sigchips">${chips}</div>`;
  }

  function buildConfidenceBand(adv) {
    const band = confidenceBand(adv.confidence);
    if (!band) return "";
    return `
      <div class="tg-adv-conf" data-level="${band.level}">
        <span class="tg-adv-conf-label">${band.label}</span>
        <span class="tg-adv-conf-num">conf ${band.value.toFixed(2)}</span>
      </div>`;
  }

  // Tier-1 strip: confidence band + contributing-signal chips. Either may be
  // absent; the strip is omitted entirely when both are.
  function buildTier1(adv) {
    const evidence = adv.evidence || {};
    const conf = buildConfidenceBand(adv);
    const chips = buildSignalChips(evidence.signals);
    if (!conf && !chips) return "";
    return `<div class="tg-adv-tier1">${conf}${chips}</div>`;
  }

  // Tier-2 expandable evidence: one row per signal (tier dot + alert_id +
  // detail). Returns "" when there is no evidence (tolerated absence).
  function buildEvidencePanel(adv, expanded) {
    const signals = adv.evidence && Array.isArray(adv.evidence.signals)
      ? adv.evidence.signals
      : [];
    if (signals.length === 0) return "";
    const rows = signals
      .map((s) => {
        const t = safeTier(s.tier);
        const id = escapeHtml(s.alert_id || s.event_type || "—");
        const detail = escapeHtml(s.detail || "");
        return `<div class="tg-evi-row">${tierDot(t)}<span class="tg-evi-id">${id}</span><span class="tg-evi-detail">${detail}</span></div>`;
      })
      .join("");
    const open = expanded ? " is-open" : "";
    const caret = expanded ? "▾" : "▸";
    return `
      <div class="tg-adv-evidence${open}">
        <button class="tg-evi-toggle" type="button" aria-expanded="${expanded}">
          <span class="tg-evi-caret">${caret}</span> EVIDENCE
        </button>
        <div class="tg-evi-body">${rows}</div>
      </div>`;
  }

  // SURFACE_CONFLICT: two equal-weight columns (each tier big + claim), a
  // "SIGNALS DISAGREE" divider, then the note. Never visually favors a side.
  function buildConflictBlock(conflict) {
    const between = conflict && Array.isArray(conflict.between) ? conflict.between : [];
    if (between.length < 2) return "";
    const col = (c) => {
      const t = safeTier(c.tier);
      const id = escapeHtml(c.alert_id || c.event_type || "");
      const claim = escapeHtml(c.claim || "");
      return `
        <div class="tg-conf-col" data-tier="${t}">
          <span class="tg-conf-tier">${t}</span>
          <span class="tg-conf-src">${id}</span>
          <span class="tg-conf-claim">${claim}</span>
        </div>`;
    };
    const note = conflict.note
      ? `<div class="tg-conf-note">${escapeHtml(conflict.note)}</div>`
      : "";
    return `
      <div class="tg-adv-conflict">
        ${col(between[0])}
        <div class="tg-conf-divider">⚡ SIGNALS DISAGREE</div>
        ${col(between[1])}
        ${note}
      </div>`;
  }

  // Small corner badge for a re-assessed / escalated new card.
  function originBadge(adv) {
    if (adv.in_response_to) return `<span class="tg-adv-origin" data-kind="reassess">RE-ASSESSED</span>`;
    if (Array.isArray(adv.supersedes) && adv.supersedes.length > 0) {
      return `<span class="tg-adv-origin" data-kind="escalate">ESCALATED</span>`;
    }
    return "";
  }

  function buildCard(adv) {
    const sev = safeTier(adv.severity);
    const isSurface = adv.action === "SURFACE_CONFLICT";
    const isCritical = sev === "CRITICAL";

    const card = document.createElement("article");
    card.className = "tg-advisory-card t-slide-in";
    card.dataset.sev = sev;
    if (isSurface) card.classList.add("is-surface-conflict");
    // SURFACE_CONFLICT cards de-emphasize plain Acknowledge (design §1/§2).
    if (isSurface) card.classList.add("is-deweight-ack");

    const badge = adv.human_override_required
      ? `<span class="tg-adv-badge">HUMAN DECISION REQUIRED</span>`
      : "";

    // EVIDENCE defaults open for CRITICAL severity or SURFACE_CONFLICT.
    const eviExpanded = isCritical || isSurface;

    card.innerHTML = `
      <div class="tg-adv-head">
        <span class="tg-adv-action">${escapeHtml(adv.action || "ADVISORY")}</span>
        <span class="tg-adv-id">${escapeHtml(adv.advisory_id || "")}</span>
        ${originBadge(adv)}
        ${badge}
      </div>
      <div class="tg-adv-summary">${escapeHtml(adv.summary || "")}</div>
      ${buildTier1(adv)}
      <div class="tg-adv-attn">${escapeHtml(adv.recommended_attention || "")}</div>
      ${isSurface ? buildConflictBlock(adv.conflict) : ""}
      ${buildEvidencePanel(adv, eviExpanded)}
      <div class="tg-adv-foot">
        <button class="tg-ack-btn tg-confirm-btn" type="button">Acknowledge</button>
        <button class="tg-dismiss-btn" type="button">Dismiss</button>
        <button class="tg-reassess-btn" type="button">Re-assess</button>
      </div>
      <div class="tg-adv-reasons" hidden></div>
    `;

    const ackBtn = card.querySelector(".tg-ack-btn");
    const dismissBtn = card.querySelector(".tg-dismiss-btn");
    const reassessBtn = card.querySelector(".tg-reassess-btn");
    const foot = card.querySelector(".tg-adv-foot");
    const reasonsEl = card.querySelector(".tg-adv-reasons");
    const eviToggle = card.querySelector(".tg-evi-toggle");

    const ctx = {
      ackBtn,
      dismissBtn,
      reassessBtn,
      foot,
      reasonsEl,
      card,
      id: adv.advisory_id,
    };
    ackBtn.addEventListener("click", () => handleAcknowledge(ctx));
    dismissBtn.addEventListener("click", () => toggleReasons(ctx));
    reassessBtn.addEventListener("click", () => handleReassess(ctx));
    if (eviToggle) {
      eviToggle.addEventListener("click", () => {
        const panel = eviToggle.closest(".tg-adv-evidence");
        const open = panel.classList.toggle("is-open");
        eviToggle.setAttribute("aria-expanded", String(open));
        const caret = eviToggle.querySelector(".tg-evi-caret");
        if (caret) caret.textContent = open ? "▾" : "▸";
      });
    }

    return card;
  }

  // Once any terminal decision lands, all three buttons lock.
  function lockButtons(ctx) {
    ctx.ackBtn.disabled = true;
    ctx.dismissBtn.disabled = true;
    ctx.reassessBtn.disabled = true;
  }

  function decided(ctx) {
    return (
      ctx.ackBtn.classList.contains("is-confirmed") ||
      ctx.dismissBtn.classList.contains("is-dismissed")
    );
  }

  async function handleAcknowledge(ctx) {
    if (decided(ctx)) return;
    lockButtons(ctx);
    ctx.ackBtn.classList.add("is-pending");
    ctx.ackBtn.textContent = "Acknowledging…";
    try {
      const res = await confirmAdvisory(ctx.id);
      ctx.ackBtn.classList.remove("is-pending");
      ctx.ackBtn.classList.add("is-confirmed");
      ctx.ackBtn.textContent = "✓ Acknowledged";
      const ts = formatTs(res && res.confirmed_at);
      if (ts) {
        const span = document.createElement("span");
        span.className = "tg-confirm-ts";
        span.textContent = ts;
        ctx.foot.appendChild(span);
      }
      clearReassessPending(ctx);
      setTimeout(() => collapseCard(ctx.id, ctx.card, "acknowledge"), COLLAPSE_DELAY_MS);
    } catch (err) {
      console.error("acknowledge failed", err);
      ctx.ackBtn.classList.remove("is-pending");
      ctx.ackBtn.classList.add("is-error");
      ctx.ackBtn.textContent = "Retry acknowledge";
      ctx.ackBtn.disabled = false;
      ctx.dismissBtn.disabled = false;
      ctx.reassessBtn.disabled = false;
    }
  }

  // Dismiss is two-step: first click expands the canned reason chips; choosing
  // one POSTs /dismiss with that reason. A second click on Dismiss collapses
  // the chips without sending.
  function toggleReasons(ctx) {
    if (decided(ctx)) return;
    const el = ctx.reasonsEl;
    if (!el.hidden) {
      el.hidden = true;
      el.innerHTML = "";
      ctx.dismissBtn.classList.remove("is-armed");
      return;
    }
    ctx.dismissBtn.classList.add("is-armed");
    el.innerHTML = DISMISS_REASONS.map(
      ([code, label]) =>
        `<button class="tg-reason-chip" type="button" data-reason="${code}">${label}</button>`,
    ).join("");
    el.hidden = false;
    el.querySelectorAll(".tg-reason-chip").forEach((b) => {
      b.addEventListener("click", () => handleDismiss(ctx, b.dataset.reason));
    });
  }

  async function handleDismiss(ctx, reason) {
    if (decided(ctx)) return;
    lockButtons(ctx);
    ctx.reasonsEl.hidden = true;
    ctx.reasonsEl.innerHTML = "";
    ctx.dismissBtn.classList.remove("is-armed");
    ctx.dismissBtn.classList.add("is-pending");
    ctx.dismissBtn.textContent = "Dismissing…";
    try {
      await dismissAdvisory(ctx.id, reason);
      ctx.dismissBtn.classList.remove("is-pending");
      ctx.dismissBtn.classList.add("is-dismissed");
      ctx.dismissBtn.textContent = "✕ Dismissed";
      ctx.card.classList.add("is-dismissed");
      clearReassessPending(ctx);
      setTimeout(
        () => collapseCard(ctx.id, ctx.card, "dismiss"),
        DISMISS_COLLAPSE_DELAY_MS,
      );
    } catch (err) {
      console.error("dismiss failed", err);
      ctx.dismissBtn.classList.remove("is-pending");
      ctx.dismissBtn.classList.add("is-error");
      ctx.dismissBtn.textContent = "Retry dismiss";
      ctx.ackBtn.disabled = false;
      ctx.dismissBtn.disabled = false;
      ctx.reassessBtn.disabled = false;
    }
  }

  function clearReassessPending(ctx) {
    const entry = cards.get(ctx.id);
    if (!entry) return;
    if (entry.reassessTimer) {
      clearTimeout(entry.reassessTimer);
      entry.reassessTimer = null;
    }
    if (entry.reassessReqId) {
      pendingReassess.delete(entry.reassessReqId);
      entry.reassessReqId = null;
    }
    ctx.reassessBtn.classList.remove("is-pending");
  }

  async function handleReassess(ctx) {
    if (decided(ctx)) return;
    const entry = cards.get(ctx.id);
    if (!entry) return;
    if (entry.reassessCount >= REASSESS_MAX) return; // already capped
    if (ctx.reassessBtn.classList.contains("is-pending")) return; // in flight

    ctx.reassessBtn.disabled = true;
    ctx.reassessBtn.classList.remove("is-error");
    ctx.reassessBtn.classList.add("is-pending");
    ctx.reassessBtn.textContent = "Re-assessing…";
    try {
      const res = await reassessAdvisory(ctx.id);
      entry.reassessCount += 1;
      entry.reassessReqId = res && res.request_id ? res.request_id : null;
      if (entry.reassessReqId) pendingReassess.set(entry.reassessReqId, ctx.id);

      // 10 s fail-safe: if no answer arrives, recover the button (never silent,
      // never auto-clear the card).
      entry.reassessTimer = setTimeout(() => {
        if (!cards.has(ctx.id)) return;
        ctx.reassessBtn.classList.remove("is-pending");
        ctx.reassessBtn.classList.add("is-error");
        ctx.reassessBtn.textContent = "Re-assess timed out";
        ctx.reassessBtn.disabled = false;
        if (entry.reassessReqId) {
          pendingReassess.delete(entry.reassessReqId);
          entry.reassessReqId = null;
        }
        entry.reassessTimer = null;
      }, REASSESS_TIMEOUT_MS);
    } catch (err) {
      ctx.reassessBtn.classList.remove("is-pending");
      if (err instanceof ReassessLimitError) {
        // server-side limit: lock the button dead.
        entry.reassessCount = REASSESS_MAX;
        ctx.reassessBtn.classList.add("is-error");
        ctx.reassessBtn.textContent = "Re-assess limit";
        ctx.reassessBtn.disabled = true;
      } else {
        console.error("reassess failed", err);
        ctx.reassessBtn.classList.add("is-error");
        ctx.reassessBtn.textContent = "Re-assess failed";
        ctx.reassessBtn.disabled = false;
      }
    }
  }

  // When a new advisory answers a pending re-assess, clear the originating
  // card's spinner/timer so it doesn't time out after a real answer arrived.
  function resolvePendingFor(inResponseTo) {
    if (!inResponseTo) return;
    const originId = pendingReassess.get(inResponseTo);
    if (!originId) return;
    pendingReassess.delete(inResponseTo);
    const entry = cards.get(originId);
    if (!entry) return;
    if (entry.reassessTimer) {
      clearTimeout(entry.reassessTimer);
      entry.reassessTimer = null;
    }
    entry.reassessReqId = null;
    const btn = entry.card.querySelector(".tg-reassess-btn");
    if (btn) {
      btn.classList.remove("is-pending");
      // button stays usable up to the cap; cap was bumped at request time.
      if (entry.reassessCount >= REASSESS_MAX) {
        btn.disabled = true;
        btn.textContent = "Re-assess limit";
      } else {
        btn.disabled = false;
        btn.textContent = "Re-assess";
      }
    }
  }

  // Mark an old card SUPERSEDED, dim it, then fold it away (does NOT count as
  // an ack/dismiss).
  function supersedeCard(oldId, bySupersedeId) {
    const entry = cards.get(oldId);
    if (!entry || entry.card.classList.contains("is-superseded")) return;
    entry.card.classList.add("is-superseded");
    const head = entry.card.querySelector(".tg-adv-head");
    if (head) {
      const tag = document.createElement("span");
      tag.className = "tg-adv-lifecycle-tag";
      tag.dataset.kind = "superseded";
      tag.textContent = bySupersedeId ? `SUPERSEDED by ${bySupersedeId}` : "SUPERSEDED";
      head.appendChild(tag);
    }
    if (entry.reassessTimer) {
      clearTimeout(entry.reassessTimer);
      entry.reassessTimer = null;
    }
    setTimeout(() => collapseCard(oldId, entry.card, null), LIFECYCLE_COLLAPSE_DELAY_MS);
  }

  /** Handle an incoming advisory event. */
  function handle(adv) {
    if (!adv || adv.action === "SUPPRESS") return;

    const id = adv.advisory_id;
    if (id && cards.has(id)) return; // de-dupe; leave existing state intact

    // A new advisory answering a re-assess clears the originating spinner.
    resolvePendingFor(adv.in_response_to);

    // Supersession: dim + fold the cards this one replaces.
    if (Array.isArray(adv.supersedes)) {
      for (const oldId of adv.supersedes) supersedeCard(oldId, id);
    }

    const card = buildCard(adv);
    railEl.insertBefore(
      card,
      railEl.firstChild === emptyEl ? null : railEl.firstChild,
    );
    if (id) {
      cards.set(id, {
        card,
        adv,
        reassessCount: 0,
        reassessReqId: null,
        reassessTimer: null,
      });
    }

    // bound the rail: drop the oldest card once over the cap
    if (cards.size > MAX_CARDS) {
      const oldestId = cards.keys().next().value;
      const oldest = cards.get(oldestId);
      cards.delete(oldestId);
      if (oldest) {
        if (oldest.reassessTimer) clearTimeout(oldest.reassessTimer);
        oldest.card.remove();
      }
    }
    refreshEmpty();
  }

  /**
   * Handle an advisory_lifecycle event:
   * { advisory_id, new_state: resolved|superseded|expired, in_response_to,
   *   reason, timestamp }.
   */
  function handleLifecycle(ev) {
    if (!ev || !ev.advisory_id) return;
    // a lifecycle answer to a pending re-assess clears that spinner too
    resolvePendingFor(ev.in_response_to);

    const entry = cards.get(ev.advisory_id);
    if (!entry) return; // card already gone — nothing to update
    const state = String(ev.new_state || "").toLowerCase();

    if (state === "resolved") {
      entry.card.classList.add("is-resolved");
      const head = entry.card.querySelector(".tg-adv-head");
      if (head) {
        const tag = document.createElement("span");
        tag.className = "tg-adv-lifecycle-tag";
        tag.dataset.kind = "resolved";
        tag.textContent = ev.reason ? `RESOLVED — ${ev.reason}` : "RESOLVED";
        head.appendChild(tag);
      }
      if (entry.reassessTimer) {
        clearTimeout(entry.reassessTimer);
        entry.reassessTimer = null;
      }
      const btn = entry.card.querySelector(".tg-reassess-btn");
      if (btn) btn.classList.remove("is-pending");
      setTimeout(
        () => collapseCard(ev.advisory_id, entry.card, null),
        LIFECYCLE_COLLAPSE_DELAY_MS,
      );
    } else if (state === "superseded") {
      supersedeCard(ev.advisory_id, ev.in_response_to || null);
    } else if (state === "expired") {
      const head = entry.card.querySelector(".tg-adv-head");
      if (head) {
        const tag = document.createElement("span");
        tag.className = "tg-adv-lifecycle-tag";
        tag.dataset.kind = "expired";
        tag.textContent = "EXPIRED";
        head.appendChild(tag);
      }
      if (entry.reassessTimer) {
        clearTimeout(entry.reassessTimer);
        entry.reassessTimer = null;
      }
      setTimeout(
        () => collapseCard(ev.advisory_id, entry.card, null),
        LIFECYCLE_COLLAPSE_DELAY_MS,
      );
    }
    // unknown new_state: tolerate, do nothing
  }

  // Drop every card + reset counters (used on airport switch — the previous
  // airport's advisories no longer describe what is being monitored). The Redis
  // shift-event history is untouched; this only clears the live rail.
  function clear() {
    for (const [, entry] of cards) {
      if (entry.reassessTimer) clearTimeout(entry.reassessTimer);
      entry.card.remove();
    }
    cards.clear();
    pendingReassess.clear();
    acknowledgedCount = 0;
    dismissedCount = 0;
    refreshDecisionChip();
    refreshEmpty();
  }

  return { handle, handleLifecycle, clear };
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
