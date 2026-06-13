"""
TowerGuard — Shift-Handover Narrator Agent (v1.1)
Converts a shift event log into a FAA Appendix A formatted
position-relief briefing. Output is always a DRAFT for
controller review — never authoritative.

Changes from v1.0:
- Field names updated to match contract v1.1:
    severity → tier (in event log items)
- Added Redis Stream reader: reads towerguard:shift_events via XRANGE
- Added briefing_id (BRF-####) separate from advisory_id
- run_forever() listens for briefing trigger on towerguard:advisory
  and auto-generates briefing when action is ESCALATE or SURFACE_CONFLICT
"""

import json
import logging
import os
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

# ── Redis topic / key names (contract v1.1 §1) ────────────────────────────────

TOPIC_ADVISORY        = "towerguard:advisory"
TOPIC_BRIEFING        = "towerguard:briefing"
STREAM_SHIFT_EVENTS   = "towerguard:shift_events"

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the Shift-Handover Narrator for TowerGuard, an AI-augmented
decision support system for understaffed air traffic control towers.

## Your role
Every ~30 minutes, or when triggered by a shift relief event, you receive a
structured event log from the current shift. You convert this log into a
plain-language position-relief briefing that follows the FAA Order 7110.65
Appendix A format (ref: FAA JO 7110.65BB §2-1-24, FAA JO 7210.3EE §2-2-4).

Your output is a DRAFT. The outgoing controller must review and verbally
confirm before handoff. You are a writing assistant, not an authority.

## Input
You will receive a JSON array of shift events, each containing:
- event_type (traffic_density | conflict_geometry | workload_index |
  advisory | controller_action | weather | notam | airport_switch)
- timestamp
- airport
- tier  (LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN)
- summary
- alert_id (cite this when referencing specific events)

## Output format
Respond in Markdown. Use exactly this structure:

---
## Position Relief Briefing — [AIRPORT] [TIME UTC]
*AI-generated draft. Outgoing controller must review and confirm.*

### 1. Current traffic picture
[2–3 sentences. Active aircraft count, load tier, any notable
traffic patterns right now.]

### 2. Active advisories
[List any open advisories with alert_id and one-line status.
If none, write "No active advisories."]

### 3. Notable events this shift
[Bullet list. Max 5 items. Cite alert_id for each. Most recent first.]

### 4. Weather and NOTAMs
[Any weather flags or NOTAMs from the event log.
If none logged, write "No weather flags or NOTAMs this period."]

### 5. Pending actions
[Anything the incoming controller needs to follow up on.
If none, write "No pending actions."]

---
*Reviewed and confirmed by: ________________  [TIME]__________*
---

## Hard constraints
- Only summarize events present in the input log.
  Never infer, predict, or add information not in the data.
- Always cite alert_id when referencing a specific event.
- Never use the word "recommend" or "suggest" — this is a
  factual briefing, not an advisory.
- Keep each section concise. The whole briefing must be
  readable in under 90 seconds.
- If the event log is empty or malformed, output:
  "Insufficient data to generate briefing. Manual briefing required."
- Always include the outgoing controller confirmation line at the end."""


# ── Agent ─────────────────────────────────────────────────────────────────────

class ShiftHandoverNarrator:
    """
    Receives a shift event log, returns a Markdown briefing
    formatted to FAA Appendix A structure.

    Two usage modes:
      1. Direct call:  narrator.run(airport, event_log)
      2. Redis loop:   narrator.run_forever()
                       — watches towerguard:advisory and auto-generates
                         briefing on ESCALATE / SURFACE_CONFLICT
    """

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic()
        self.model = model
        self._briefing_counter = 0

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(
        self,
        airport: str,
        event_log: list[dict[str, Any]],
        trigger: str = "scheduled",  # "scheduled" | "relief_requested" | "advisory_escalate"
    ) -> dict[str, Any]:
        """
        Main entry point.
        Returns dict with 'briefing' (Markdown str) and metadata.
        """
        self._briefing_counter += 1
        briefing_id = f"BRF-{self._briefing_counter:04d}"

        if not event_log:
            return {
                "briefing_id": briefing_id,
                "airport": airport,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "trigger": trigger,
                "status": "insufficient_data",
                "confirmed_by_controller": False,
                "briefing": (
                    "Insufficient data to generate briefing. "
                    "Manual briefing required."
                ),
            }

        user_message = self._build_user_message(airport, event_log, trigger)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        briefing_md = response.content[0].text.strip()

        return {
            "briefing_id": briefing_id,
            "airport": airport,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "trigger": trigger,
            "status": "draft",
            "events_summarized": len(event_log),
            "confirmed_by_controller": False,  # set true only via dashboard
            "briefing": briefing_md,
        }

    # ── Redis Stream reader ───────────────────────────────────────────────────

    def read_shift_events(self, r: redis.Redis, airport: str) -> list[dict[str, Any]]:
        """
        Read all events from towerguard:shift_events Redis Stream.
        Filters to the given airport. Returns parsed event dicts.

        Uses XRANGE to read the full stream — safe for offline Narrator
        since Stream accumulates even when subscriber is not connected.
        """
        try:
            raw_entries = r.xrange(STREAM_SHIFT_EVENTS)
        except Exception as exc:
            logger.warning("Could not read shift_events stream: %s", exc)
            return []

        events = []
        for _entry_id, fields in raw_entries:
            # Each stream entry has a 'data' field containing JSON
            raw = fields.get("data")
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            # Filter to matching airport only
            if event.get("airport") == airport:
                events.append(event)

        logger.info(
            "Read %d shift events for %s from stream", len(events), airport
        )
        return events

    # ── Redis loop ────────────────────────────────────────────────────────────

    def run_forever(self) -> None:
        """
        Subscribe to towerguard:advisory.
        When an ESCALATE or SURFACE_CONFLICT advisory arrives,
        read the full shift_events stream and generate a briefing.
        Publish the briefing result to towerguard:briefing.
        """
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, decode_responses=True)

        pubsub = r.pubsub()
        pubsub.subscribe(TOPIC_ADVISORY)
        logger.info("Narrator subscribed to %s. Waiting for advisories…", TOPIC_ADVISORY)

        for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                advisory = json.loads(message["data"])
            except json.JSONDecodeError:
                logger.warning("Could not parse advisory message — skipping")
                continue

            action = advisory.get("action")
            airport = advisory.get("airport")

            # Only generate briefing on actionable advisories
            if action not in ("ESCALATE", "SURFACE_CONFLICT"):
                continue
            if not airport:
                logger.warning("Advisory missing airport field — skipping")
                continue

            logger.info(
                "Received %s advisory for %s — generating briefing", action, airport
            )

            # Read full shift log from Redis Stream
            event_log = self.read_shift_events(r, airport)

            # Generate briefing
            try:
                result = self.run(
                    airport=airport,
                    event_log=event_log,
                    trigger="advisory_escalate",
                )
                # Attach the triggering advisory_id for reference
                result["triggered_by_advisory"] = advisory.get("advisory_id")

                r.publish(TOPIC_BRIEFING, json.dumps(result))
                logger.info(
                    "Published briefing %s for %s (%d events)",
                    result["briefing_id"], airport, result.get("events_summarized", 0),
                )

            except Exception as exc:
                logger.error("Error generating briefing: %s", exc, exc_info=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_user_message(
        self,
        airport: str,
        event_log: list[dict[str, Any]],
        trigger: str,
    ) -> str:
        now = datetime.now(timezone.utc).strftime("%H%MZ")
        return (
            f"Airport: {airport}\n"
            f"Briefing time: {now}\n"
            f"Trigger: {trigger}\n"
            f"Event log ({len(event_log)} events):\n\n"
            + json.dumps(event_log, indent=2)
            + "\n\nGenerate the position-relief briefing now."
        )


# ── Quick test (v1.1 field names) ─────────────────────────────────────────────

if __name__ == "__main__":
    narrator = ShiftHandoverNarrator()

    # Simulated MDW shift log using v1.1 field names (tier instead of severity)
    sample_log = [
        {
            "event_type": "traffic_density",
            "alert_id": "TD-0041",
            "airport": "KMDW",
            "timestamp": "2026-06-14T17:00:00Z",
            "tier": "HIGH",
            "summary": "Aircraft count 115, score 0.74, HIGH tier.",
        },
        {
            "event_type": "conflict_geometry",
            "alert_id": "CG-0017",
            "airport": "KMDW",
            "timestamp": "2026-06-14T17:22:00Z",
            "tier": "HIGH",
            "summary": (
                "UAL412 and AAL891 projected at 2.8 NM separation "
                "within 87 seconds. ICAO minimum 3.0 NM."
            ),
        },
        {
            "event_type": "advisory",
            "alert_id": "ADV-0009",
            "airport": "KMDW",
            "timestamp": "2026-06-14T17:22:10Z",
            "tier": "HIGH",
            "summary": (
                "Orchestrator escalated: attention recommended on "
                "UAL412/AAL891 pair. Controller confirmed at 17:23Z."
            ),
        },
        {
            "event_type": "controller_action",
            "alert_id": "CA-0005",
            "airport": "KMDW",
            "timestamp": "2026-06-14T17:23:30Z",
            "tier": "LOW",
            "summary": "Controller issued spacing instruction. Conflict resolved.",
        },
        {
            "event_type": "workload_index",
            "alert_id": "WI-0033",
            "airport": "KMDW",
            "timestamp": "2026-06-14T18:30:00Z",
            "tier": "HIGH",
            "summary": (
                "Workload score 0.81. 2 controllers on position, "
                "4 recommended."
            ),
        },
    ]

    result = narrator.run(airport="KMDW", event_log=sample_log)

    print(f"Briefing ID:       {result['briefing_id']}")
    print(f"Status:            {result['status']}")
    print(f"Events summarized: {result['events_summarized']}")
    print(f"Generated at:      {result['generated_at']}")
    print("\n" + "─" * 60 + "\n")
    print(result["briefing"])
