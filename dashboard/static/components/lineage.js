// lineage.js — "依據" panel: header button + slide-out (mirrors the briefing
// slide-out pattern). On first open it fetches GET /lineage (the markdown text
// of docs/lineage.md) and renders it; the result is cached for later opens.

import { renderMarkdown } from "./markdown.js";

export function createLineage(refs) {
  const { btn, scrim, panel, body, closeBtn } = refs;
  let loaded = false;

  function openPanel() {
    scrim.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => {
      scrim.classList.add("is-open");
      panel.classList.add("is-open");
    });
    if (!loaded) loadLineage();
  }

  function closePanel() {
    scrim.classList.remove("is-open");
    panel.classList.remove("is-open");
    panel.setAttribute("aria-hidden", "true");
    const done = () => { scrim.hidden = true; };
    scrim.addEventListener("transitionend", done, { once: true });
    setTimeout(done, 600);
  }

  async function loadLineage() {
    body.innerHTML = `<p class="tg-lineage-loading">Loading lineage…</p>`;
    try {
      const res = await fetch("/lineage");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const md = await res.text();
      body.innerHTML = renderMarkdown(md);
      loaded = true;
    } catch (err) {
      console.error("lineage load failed", err);
      body.innerHTML =
        `<p class="tg-lineage-error">Lineage unavailable — could not reach /lineage.</p>`;
      // leave loaded=false so the next open retries
    }
  }

  btn.addEventListener("click", openPanel);
  closeBtn.addEventListener("click", closePanel);
  scrim.addEventListener("click", closePanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel.classList.contains("is-open")) closePanel();
  });

  return { open: openPanel };
}
