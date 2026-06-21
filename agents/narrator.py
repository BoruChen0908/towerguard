"""TowerGuard — Shift-Handover Narrator (v2, LLM-augmented briefing).

The relief briefing is assembled deterministically from the real shift-events
log (``fixtures/advisory_briefing.build_briefing_markdown``) — five FAA
Appendix-A sections, every line sourced from a logged event, with a fixed
"AI-generated draft / outgoing controller must review and confirm" disclaimer
and a sign-off line. That deterministic markdown is the ground truth.

``BriefingNarrator`` rewrites that ground-truth briefing into more fluent
position-relief prose **without adding or altering any fact** — it is a writing
pass over already-assembled content, never a generator of new content. Two
guardrails keep it safe:
  1. The model is told to preserve every alert_id, number, the draft disclaimer,
     and the confirmation line, and to add nothing.
  2. ``render`` re-checks that the disclaimer and confirmation line survived; if
     either is missing (or anything fails), it returns the deterministic
     markdown unchanged.

So the briefing a controller signs is always grounded in the shift log; the LLM
only changes how it reads. Off by default (see config.llm_enabled()).
"""

import logging
from typing import Optional

import config
from agents import llm_client

logger = logging.getLogger(__name__)

# Markers the deterministic template guarantees; the rephrase must keep them or
# we discard it and fall back. Lower-cased substring checks.
_REQUIRED_MARKERS = ("ai-generated draft", "review and confirm")

SYSTEM_PROMPT = """You are the shift-handover writing assistant for TowerGuard, a
decision-support system for understaffed air traffic control towers.

You will receive a position-relief briefing that has ALREADY been assembled from
the shift's event log. Rewrite it into clear, professional FAA Order 7110.65
Appendix-A position-relief prose. This is a WRITING pass, not an analysis pass.

Absolute rules:
- Add NO new facts. Use only what is in the input briefing.
- Preserve every alert_id (e.g. CG-0017, ADV-0009) and every number exactly.
- Keep the five-section structure and their headings.
- Keep the "AI-generated draft. Outgoing controller must review and confirm."
  disclaimer line and the reviewer/confirmation sign-off line verbatim.
- Never add a recommendation, prediction, or directive — this is a factual
  briefing the outgoing controller confirms, not advice.
- Output Markdown only. No commentary before or after the briefing."""


class BriefingNarrator:
    """Rephrases a deterministically-assembled relief briefing via Claude.

    ``render`` always returns valid briefing markdown: the rephrased version when
    augmentation is on, the call succeeds, and the structural guardrails survive;
    otherwise the input template markdown unchanged.
    """

    def __init__(self, model: Optional[str] = None, max_tokens: int = 1200):
        self.model = model or config.llm_model()
        self.max_tokens = max_tokens

    def render(self, template_markdown: str) -> str:
        if not llm_client.available():
            return template_markdown
        try:
            response = llm_client.get_client().messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Rewrite this position-relief briefing per your "
                            "rules:\n\n" + template_markdown
                        ),
                    }
                ],
            )
            text = llm_client.extract_text(response).strip()
            if text and _markers_present(text):
                return text
            logger.warning("LLM briefing missing required markers — using template")
        except Exception as exc:  # any failure → deterministic template
            logger.warning("LLM briefing failed (%s) — using template", exc)
        return template_markdown


def _markers_present(text: str) -> bool:
    low = text.lower()
    return all(marker in low for marker in _REQUIRED_MARKERS)


if __name__ == "__main__":  # pragma: no cover — manual smoke test
    logging.basicConfig(level=logging.INFO)
    sample = (
        "---\n## Position Relief Briefing — KMDW 1842Z\n"
        "*AI-generated draft. Outgoing controller must review and confirm.*\n\n"
        "### 1. Current traffic picture\n- TRAFFIC DENSITY: HIGH\n\n"
        "### 2. Active advisories\n- · ADV-0009: Projected separation violation "
        "(HIGH) for DMO901/DMO902.\n\n### 3. Notable events this shift\n"
        "- CONFLICT GEOMETRY MEDIUM → HIGH (DMO901/DMO902)\n\n"
        "### 4. Weather and NOTAMs\nVFR conditions, no active NOTAMs (demo).\n\n"
        "### 5. Pending actions\n- 1 advisory(ies) awaiting controller decision.\n\n"
        "---\n*Reviewed and confirmed by: ________________  [TIME]__________*\n---\n"
    )
    print(BriefingNarrator().render(sample))
