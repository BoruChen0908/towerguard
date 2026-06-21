"""TowerGuard — Orchestrator / Advisory Phraser (v2, LLM-augmented engine).

In the v1.2 architecture the deterministic ``AdvisoryEngine``
(``fixtures/advisory_engine.py``) is the orchestrator: it synthesizes the three
module signals, applies the design §6 rule table, and owns the full advisory
lifecycle (dedup, cooldown, supersede/resolve, the human-override fields). That
machinery is the Responsible-AI backbone and is never delegated to a model.

This module is the **one** place the LLM enters the live advisory path: given an
advisory the engine has *already decided to issue*, ``AdvisoryPhraser`` rewrites
the controller-facing ``summary`` and ``recommended_attention`` from the same
structured evidence. The model never decides whether/when to escalate, never
sees a directive verb, and never invents data — and on any failure (no key,
network, bad JSON) the engine's deterministic template text is returned
unchanged. So the LLM improves how a signal is *described*, never *whether it
fires*.

Enable via ``TOWERGUARD_USE_LLM=1`` + ``ANTHROPIC_API_KEY`` (see config); off by
default so tests and the offline demo stay deterministic.
"""

import json
import logging
from typing import Any, Optional

import config
from agents import llm_client

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the phrasing layer for TowerGuard, a decision-support
system for understaffed air traffic control towers.

A deterministic engine has ALREADY decided to issue this advisory and ALREADY
chosen its action and severity. You do not make or change that decision. Your
only job: turn the structured evidence into two short, plain-English strings a
controller will read.

You will receive JSON with:
- action: ESCALATE | SURFACE_CONFLICT  (fixed — do not question it)
- severity: LOW | MEDIUM | HIGH | CRITICAL  (fixed)
- callsigns: the aircraft pair, if any
- evidence: the contributing module signals, each with its numbers and a
  one-line detail putting the number against its threshold
- fallback: the deterministic text already prepared (your output replaces this
  only if it is clearly better; match its meaning exactly)

Return ONLY valid JSON, no prose, no markdown fences:
{"summary": "<=20 words", "recommended_attention": "<=20 words"}

Hard constraints:
- Use ONLY numbers and facts present in the evidence. Never invent data.
- Never issue a directive. Use "attention recommended", "consider reviewing",
  "verify" — never "do this", "issue clearance", or any command.
- For SURFACE_CONFLICT, make clear the signals disagree and the controller must
  adjudicate — never resolve the disagreement yourself.
- Keep each field a single clause, controller-readable at a glance.
- If anything is unclear, mirror the fallback text rather than guessing."""


class AdvisoryPhraser:
    """Rewrites a decided advisory's summary + recommended_attention via Claude.

    Stateless and side-effect-free. ``phrase`` always returns a (summary,
    recommended_attention) pair: the LLM's when augmentation is on and the call
    succeeds, otherwise the deterministic fallback passed in by the engine.
    """

    def __init__(self, model: Optional[str] = None, max_tokens: int = 300):
        self.model = model or config.llm_model()
        self.max_tokens = max_tokens

    def phrase(
        self,
        *,
        action: str,
        severity: str,
        callsigns: list[str],
        evidence: dict[str, Any],
        fallback_summary: str,
        fallback_attention: str,
    ) -> tuple[str, str]:
        if not llm_client.available():
            return fallback_summary, fallback_attention
        try:
            payload = {
                "action": action,
                "severity": severity,
                "callsigns": callsigns,
                "evidence": evidence,
                "fallback": {
                    "summary": fallback_summary,
                    "recommended_attention": fallback_attention,
                },
            }
            response = llm_client.get_client().messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps(payload)}],
            )
            data = _parse_json(llm_client.extract_text(response))
            summary = _clean(data.get("summary"))
            attention = _clean(data.get("recommended_attention"))
            if summary and attention:
                return summary, attention
            logger.warning("LLM phrasing incomplete — using template")
        except Exception as exc:  # any failure → deterministic template
            logger.warning("LLM phrasing failed (%s) — using template", exc)
        return fallback_summary, fallback_attention


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1])
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


if __name__ == "__main__":  # pragma: no cover — manual smoke test
    logging.basicConfig(level=logging.INFO)
    phraser = AdvisoryPhraser()
    s, a = phraser.phrase(
        action="ESCALATE",
        severity="HIGH",
        callsigns=["DMO901", "DMO902"],
        evidence={
            "signals": [
                {
                    "event_type": "conflict_geometry",
                    "tier": "HIGH",
                    "detail": "2.8 NM vs ICAO min 3.0 NM, first violation in 87 s.",
                }
            ]
        },
        fallback_summary="Projected separation violation (HIGH) for DMO901/DMO902.",
        fallback_attention="DMO901/DMO902 closing to 2.8 NM in 87 s — verify separation.",
    )
    print("summary:", s)
    print("recommended_attention:", a)
