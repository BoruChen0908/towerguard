"""Tests for the policy brief generator (N8, template-first)."""

from models.policy_brief import PolicyBrief, generate_brief
from models.scenario_engine import run_all


def _brief() -> PolicyBrief:
    return generate_brief(run_all())


def test_brief_sections_are_populated() -> None:
    brief = _brief()
    assert brief.executive_summary
    assert 3 <= len(brief.key_findings) <= 5
    assert brief.cost_of_delay
    assert brief.recommendations
    assert brief.limitations


def test_brief_presents_both_targets() -> None:
    """Responsible-AI guardrail (§13): show FAA and NATCA, endorse neither."""
    text = " ".join(_brief().recommendations)
    assert "12,563" in text
    assert "14,633" in text


def test_limitations_carry_safety_disclaimer() -> None:
    limitations = _brief().limitations.lower()
    assert "not accident" in limitations or "not a facility" in limitations


def test_brief_is_deterministic() -> None:
    assert generate_brief(run_all()) == generate_brief(run_all())
