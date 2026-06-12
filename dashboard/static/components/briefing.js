// briefing.js — position relief briefing: launch button + slide-out panel.
// Renders markdown (marked CDN, with a minimal fallback) and a Confirm button.

import { confirmAdvisory } from "./confirm.js";
import { renderMarkdown } from "./markdown.js";

export function createBriefing(refs) {
  const { btn, scrim, panel, body, closeBtn, confirmBtn } = refs;
  let currentId = null;

  function openPanel() {
    scrim.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    // next frame so the transition runs from the off-screen state
    requestAnimationFrame(() => {
      scrim.classList.add("is-open");
      panel.classList.add("is-open");
    });
  }

  function closePanel() {
    scrim.classList.remove("is-open");
    panel.classList.remove("is-open");
    panel.setAttribute("aria-hidden", "true");
    // Hide scrim after fade; not load-bearing — also force-hide as a fallback.
    const done = () => { scrim.hidden = true; };
    scrim.addEventListener("transitionend", done, { once: true });
    setTimeout(done, 600);
  }

  function resetConfirmBtn() {
    confirmBtn.className = "tg-confirm-btn";
    confirmBtn.disabled = false;
    confirmBtn.textContent = "Controller Confirmed";
    // drop any stale timestamp chip
    const chip = panel.querySelector(".tg-confirm-ts");
    if (chip) chip.remove();
  }

  async function handleConfirm() {
    if (!currentId || confirmBtn.classList.contains("is-confirmed")) return;
    confirmBtn.disabled = true;
    confirmBtn.classList.add("is-pending");
    confirmBtn.textContent = "Confirming…";
    try {
      const res = await confirmAdvisory(currentId);
      confirmBtn.classList.remove("is-pending");
      confirmBtn.classList.add("is-confirmed");
      confirmBtn.textContent = "✓ Confirmed";
      if (res && res.confirmed_at) {
        const chip = document.createElement("span");
        chip.className = "tg-confirm-ts";
        chip.textContent = formatTs(res.confirmed_at);
        confirmBtn.parentNode.appendChild(chip);
      }
    } catch (err) {
      console.error("briefing confirm failed", err);
      confirmBtn.classList.remove("is-pending");
      confirmBtn.classList.add("is-error");
      confirmBtn.textContent = "Retry confirm";
      confirmBtn.disabled = false;
    }
  }

  /** Handle an incoming briefing event: { advisory_id, markdown }. */
  function handle(brief) {
    if (!brief) return;
    currentId = brief.advisory_id || null;
    body.innerHTML = renderMarkdown(brief.markdown || "");
    resetConfirmBtn();

    // light up the launch button
    btn.hidden = false;
    btn.classList.remove("t-appear");
    void btn.offsetWidth;
    btn.classList.add("t-appear");
  }

  btn.addEventListener("click", openPanel);
  closeBtn.addEventListener("click", closePanel);
  scrim.addEventListener("click", closePanel);
  confirmBtn.addEventListener("click", handleConfirm);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel.classList.contains("is-open")) closePanel();
  });

  return { handle };
}

function formatTs(iso) {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return String(iso);
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}Z`;
}
