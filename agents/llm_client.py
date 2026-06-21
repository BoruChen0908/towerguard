"""Shared Anthropic client for the optional LLM augmentation layer.

The deterministic AdvisoryEngine owns every decision and guardrail; this module
only exists so the Orchestrator (advisory phrasing) and Narrator (briefing
prose) can turn already-decided structured signals into the human-facing text a
controller reads. Everything degrades to the deterministic template when no key
is configured or a call fails — see ``config.llm_enabled()``.

``anthropic`` is imported lazily inside ``get_client`` so this module (and the
agents that import it) load fine even when the package is absent or no key is
set — the augmentation path simply stays off.
"""

import logging
from functools import lru_cache
from typing import Any

import config

logger = logging.getLogger(__name__)


def available() -> bool:
    """Whether LLM augmentation should be attempted (explicitly on + key set)."""
    return config.llm_enabled()


@lru_cache(maxsize=1)
def get_client() -> Any:
    """Construct (and cache) an Anthropic client. Resolves the key from env."""
    import anthropic  # lazy: only needed when augmentation is actually on

    return anthropic.Anthropic()


def extract_text(response: Any) -> str:
    """Return the first text block of a messages.create() response, or ''."""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""
