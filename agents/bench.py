"""Latency benchmark for the LLM augmentation layer.

Times one realistic advisory-phrasing call and one relief-briefing call against
one or more Claude models, so you can see exactly how long a live run takes and
compare models before choosing one for the demo.

Needs a key — set it and run:

    ANTHROPIC_API_KEY=sk-... python -m agents.bench
    ANTHROPIC_API_KEY=sk-... python -m agents.bench --models claude-opus-4-8,claude-haiku-4-5 --runs 5

The phraser path is the latency that matters in the tower (it fires per
advisory); the briefing path runs on a slow ~120 s cadence, so its latency is
not user-blocking.
"""

import argparse
import os
import statistics
import time

# Force the augmentation gate on for the benchmark (the real toggle is the env
# var; here we just need available() to return True when a key is present).
os.environ.setdefault("TOWERGUARD_USE_LLM", "1")

from agents import llm_client  # noqa: E402
from agents.narrator import BriefingNarrator  # noqa: E402
from agents.orchestrator import AdvisoryPhraser  # noqa: E402

# A representative HIGH conflict advisory (KMDW, two aircraft closing inside the
# ICAO minimum) — the shape build_evidence produces for the phraser.
_EVIDENCE = {
    "signals": [
        {
            "event_type": "conflict_geometry",
            "alert_id": "CG-0017",
            "tier": "HIGH",
            "key_values": {
                "projected_separation_nm": 2.8,
                "icao_minimum_nm": 3.0,
                "time_to_violation_seconds": 87,
            },
            "detail": "2.8 NM vs ICAO min 3.0 NM, first violation in 87 s.",
        },
        {
            "event_type": "traffic_density",
            "alert_id": "TD-0041",
            "tier": "HIGH",
            "key_values": {"aircraft_count": 115, "score": 0.74},
            "detail": "115 aircraft within 50 NM, density score 0.74.",
        },
        {
            "event_type": "workload_index",
            "alert_id": "WI-0033",
            "tier": "HIGH",
            "key_values": {
                "staffed_controllers": 2,
                "recommended_controllers": 4,
                "score": 0.81,
            },
            "detail": "2/4 controllers on board (short 2), workload score 0.81.",
        },
    ]
}

_BRIEFING_TEMPLATE = (
    "---\n## Position Relief Briefing — KMDW 1842Z\n"
    "*AI-generated draft. Outgoing controller must review and confirm.*\n\n"
    "### 1. Current traffic picture\n- TRAFFIC DENSITY: HIGH\n"
    "- CONFLICT GEOMETRY: HIGH\n- WORKLOAD INDEX: HIGH\n\n"
    "### 2. Active advisories\n- · ADV-0009: Projected separation violation "
    "(HIGH) for DMO901/DMO902.\n\n### 3. Notable events this shift\n"
    "- CONFLICT GEOMETRY MEDIUM → HIGH (DMO901/DMO902)\n"
    "- WORKLOAD INDEX MEDIUM → HIGH\n\n### 4. Weather and NOTAMs\n"
    "VFR conditions, no active NOTAMs affecting the field (demo).\n\n"
    "### 5. Pending actions\n- 1 advisory(ies) awaiting controller decision.\n\n"
    "---\n*Reviewed and confirmed by: ________________  [TIME]__________*\n---\n"
)


def _time(fn, runs: int) -> list[float]:
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return samples


def _report(label: str, samples: list[float]) -> None:
    lo, hi = min(samples), max(samples)
    med = statistics.median(samples)
    print(f"  {label:<22} median {med:5.2f}s   (min {lo:.2f}s / max {hi:.2f}s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        default="claude-opus-4-8,claude-haiku-4-5",
        help="comma-separated model ids to compare",
    )
    parser.add_argument("--runs", type=int, default=3, help="calls per path per model")
    args = parser.parse_args()

    if not llm_client.available():
        raise SystemExit(
            "LLM not available — set ANTHROPIC_API_KEY (and TOWERGUARD_USE_LLM=1)."
        )

    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"\n{model}  ({args.runs} runs each)")
        phraser = AdvisoryPhraser(model=model)
        narrator = BriefingNarrator(model=model)

        def phrase_once():
            phraser.phrase(
                action="ESCALATE",
                severity="HIGH",
                callsigns=["DMO901", "DMO902"],
                evidence=_EVIDENCE,
                fallback_summary="Projected separation violation (HIGH) for "
                "DMO901/DMO902.",
                fallback_attention="DMO901/DMO902 closing to 2.8 NM in 87 s — "
                "verify separation.",
            )

        _report("advisory phrasing", _time(phrase_once, args.runs))
        _report("relief briefing", _time(lambda: narrator.render(_BRIEFING_TEMPLATE), args.runs))


if __name__ == "__main__":
    main()
