"""
TowerGuard — Orchestrator / Arbitration Agent (v1.1)
Synthesizes signals from deterministic modules and decides
what deserves human attention.

Changes from v1.0:
- Field names updated to match contract v1.1:
    load_index → score
    load_tier  → tier
    workload_score → score
    severity (in cg event) → tier
- Added Redis pub/sub listener loop (run_forever)
- Added confirmed_by_controller field to output
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import anthropic
import redis
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Redis topic names (must match contract v1.1 §1) ───────────────────────────

TOPIC_TRAFFIC_DENSITY   = "towerguard:traffic_density"
TOPIC_CONFLICT_GEOMETRY = "towerguard:conflict_geometry"
TOPIC_WORKLOAD_INDEX    = "towerguard:workload_index"
TOPIC_ADVISORY          = "towerguard:advisory"

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the Orchestrator agent for TowerGuard, an AI-augmented decision
support system for understaffed air traffic control towers.

## Your role
You receive structured JSON events from three deterministic modules:
- Traffic Density  (aircraft count, speed variance, altitude variance → score, tier)
- Conflict Geometry (pairwise separation projections, 60–120s horizon → tier)
- Workload Index   (staffing ratio, frequencies, handoff rate → score, tier)

Each event shares a common envelope with these fields:
  event_type, alert_id, airport, timestamp, tier, data_unavailable

Your job is to synthesize these signals and decide what — if anything —
deserves human attention. You surface tensions; you do not resolve them.

## Decision rules

ESCALATE to a graded advisory when ANY of the following are true:
- Any module's tier is HIGH or CRITICAL
- conflict_geometry shows time_to_violation_seconds ≤ 90 on any pair
- workload_index score > 0.75 AND any other module is MEDIUM or above
- Two or more modules signal elevated risk simultaneously

SUPPRESS (do not issue advisory) when:
- All three modules are LOW
- data_unavailable is true on all three modules (system degraded)
- A conflict_geometry flag exists but all other modules are LOW and
  workload_index score < 0.40

SURFACE_CONFLICT (special case) when:
- Modules disagree — e.g. tier is LOW on traffic_density but conflict_geometry
  flags a critical pair. Do NOT silently resolve. Present both signals to the
  human with your reasoning.
- data_unavailable is true on some but not all modules (partial degradation)

## Output format
Always respond in valid JSON. Never respond in prose.

{
  "advisory_id": "<ADV-####>",
  "timestamp": "<ISO8601 UTC>",
  "airport": "<ICAO code>",
  "action": "ESCALATE" | "SUPPRESS" | "SURFACE_CONFLICT",
  "severity": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "confidence": <0.0–1.0>,
  "summary": "<one sentence, plain English, max 20 words>",
  "contributing_signals": ["traffic_density", "conflict_geometry", "workload_index"],
  "recommended_attention": "<specific thing controller should look at, max 20 words>",
  "human_override_required": true,
  "confirmed_by_controller": false
}

## Hard constraints
- human_override_required is ALWAYS true. Never set it to false. Never omit it.
- confirmed_by_controller is ALWAYS false on initial publish. Never set it to true.
- Never issue a directive. Use language like "attention recommended" or
  "consider reviewing" — never "do this" or "issue clearance".
- Never invent data not present in the input JSON.
- If data_unavailable is true on any module, note the gap in summary.
- If input is malformed or incomplete, respond with action: "SUPPRESS"
  and note the data gap in summary.
- Confidence above 0.85 requires signals from at least two modules."""


# ── Agent ─────────────────────────────────────────────────────────────────────

class OrchestratorAgent:
    """
    Receives module events, calls the LLM, returns a structured advisory dict.

    Two usage modes:
      1. Direct call:   agent.run(td_event, cg_event, wi_event)
      2. Redis loop:    agent.run_forever()  — subscribes and runs continuously
    """

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic()
        self.model = model
        self._advisory_counter = 0

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(
        self,
        traffic_density_event: dict[str, Any],
        conflict_geometry_event: dict[str, Any],
        workload_index_event: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Synthesize three module events into an advisory.
        Returns a parsed advisory dict ready for publishing to Redis.
        """
        user_message = self._build_user_message(
            traffic_density_event,
            conflict_geometry_event,
            workload_index_event,
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text
        advisory = self._parse_response(raw)

        # Guarantee safety fields regardless of LLM output
        self._advisory_counter += 1
        advisory["advisory_id"] = f"ADV-{self._advisory_counter:04d}"
        advisory["human_override_required"] = True
        advisory["confirmed_by_controller"] = False
        advisory["generated_at"] = datetime.now(timezone.utc).isoformat()

        return advisory

    # ── Redis loop ────────────────────────────────────────────────────────────

    def run_forever(self) -> None:
        """
        Subscribe to the three module topics and run continuously.
        Collects one event from each module per cycle, then calls run().
        Publishes the advisory to towerguard:advisory.

        Safe to run alongside Bo-Ru's runner — just reads pub/sub, never writes
        to module topics.
        """
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, decode_responses=True)

        pubsub = r.pubsub()
        pubsub.subscribe(
            TOPIC_TRAFFIC_DENSITY,
            TOPIC_CONFLICT_GEOMETRY,
            TOPIC_WORKLOAD_INDEX,
        )
        logger.info("Orchestrator subscribed to 3 module topics. Waiting for events…")

        # Buffer: hold the latest event from each module
        buffer: dict[str, dict | None] = {
            "traffic_density": None,
            "conflict_geometry": None,
            "workload_index": None,
        }

        for message in pubsub.listen():
            if message["type"] != "message":
                continue

            topic = message["channel"]
            try:
                event = json.loads(message["data"])
            except json.JSONDecodeError:
                logger.warning("Could not parse message on %s — skipping", topic)
                continue

            # Store latest event in buffer by event_type
            event_type = event.get("event_type")
            if event_type in buffer:
                buffer[event_type] = event
                logger.info(
                    "Received %s from %s — tier=%s",
                    event_type, event.get("airport"), event.get("tier"),
                )

            # Once all three modules have reported, run the agent
            if all(v is not None for v in buffer.values()):
                try:
                    advisory = self.run(
                        traffic_density_event=buffer["traffic_density"],
                        conflict_geometry_event=buffer["conflict_geometry"],
                        workload_index_event=buffer["workload_index"],
                    )

                    # Only publish ESCALATE and SURFACE_CONFLICT to dashboard
                    if advisory.get("action") != "SUPPRESS":
                        r.publish(TOPIC_ADVISORY, json.dumps(advisory))
                        logger.info(
                            "Published advisory: action=%s severity=%s airport=%s",
                            advisory.get("action"),
                            advisory.get("severity"),
                            advisory.get("airport"),
                        )
                    else:
                        logger.info(
                            "Advisory suppressed for %s — all signals LOW",
                            advisory.get("airport"),
                        )

                except Exception as exc:
                    logger.error("Error running orchestrator cycle: %s", exc, exc_info=True)

                # Reset buffer — wait for next full set of events
                buffer = {k: None for k in buffer}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_user_message(
        self,
        td: dict[str, Any],
        cg: dict[str, Any],
        wi: dict[str, Any],
    ) -> str:
        payload = {
            "traffic_density": td,
            "conflict_geometry": cg,
            "workload_index": wi,
        }
        return (
            "Here are the latest module events. "
            "Synthesize and return your advisory JSON.\n\n"
            + json.dumps(payload, indent=2)
        )

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Strip markdown fences if present, then parse JSON."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "action": "SUPPRESS",
                "severity": "LOW",
                "confidence": 0.0,
                "summary": "Parse error — manual review required.",
                "contributing_signals": [],
                "recommended_attention": "Check system logs.",
                "human_override_required": True,
                "confirmed_by_controller": False,
                "_parse_error": True,
                "_raw": raw,
            }


# ── Quick test (v1.1 field names) ─────────────────────────────────────────────

if __name__ == "__main__":
    agent = OrchestratorAgent()

    # Simulated MDW scenario using v1.1 field names
    result = agent.run(
        traffic_density_event={
            "event_type": "traffic_density",
            "alert_id": "TD-0001",
            "airport": "KMDW",
            "timestamp": "2026-06-14T18:42:00Z",
            "tier": "HIGH",
            "data_unavailable": False,
            "score": 0.74,
            "aircraft_count": 115,
            "speed_variance": 42.3,
            "altitude_variance": 3800,
            "window_seconds": 60,
        },
        conflict_geometry_event={
            "event_type": "conflict_geometry",
            "alert_id": "CG-0017",
            "airport": "KMDW",
            "timestamp": "2026-06-14T18:42:05Z",
            "tier": "HIGH",
            "data_unavailable": False,
            "pairs_checked": 22,
            "conflicts_detected": 2,
            "closest_pair": {
                "callsigns": ["UAL412", "AAL891"],
                "projected_separation_nm": 2.8,
                "icao_minimum_nm": 3.0,
                "time_to_violation_seconds": 87,
            },
            "all_conflicts": [
                {
                    "callsigns": ["UAL412", "AAL891"],
                    "projected_separation_nm": 2.8,
                    "icao_minimum_nm": 3.0,
                    "time_to_violation_seconds": 87,
                }
            ],
        },
        workload_index_event={
            "event_type": "workload_index",
            "alert_id": "WI-0033",
            "airport": "KMDW",
            "timestamp": "2026-06-14T18:42:08Z",
            "tier": "HIGH",
            "data_unavailable": False,
            "score": 0.81,
            "staffed_controllers": 2,
            "recommended_controllers": 4,
            "active_frequencies": 3,
            "handoff_rate_per_hour": 12,
        },
    )

    print(json.dumps(result, indent=2))
