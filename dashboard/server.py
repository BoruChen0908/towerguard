"""TowerGuard dashboard server — FastAPI + SSE bridge over Redis pub/sub.

Interface contract (frozen with the frontend agent):
  GET  /                       → dashboard/static/index.html
  GET  /static/*               → static files
  GET  /events                 → SSE stream; `event: <type>\\ndata: <json>\\n\\n`
                                 type ∈ {traffic_density, conflict_geometry,
                                 workload_index, advisory, aircraft_snapshot,
                                 briefing, shift_event}. The first five forward
                                 the Redis topic JSON verbatim; briefing data is
                                 {"advisory_id", "markdown"}; shift_event data is
                                 {"timestamp", "kind", "summary", "ref"}. On
                                 connect, the cached last message of each type is
                                 replayed, then the most recent 20 shift events.
  GET  /airports               → {"airports": [{"icao", "name"}...], "selected"}
  POST /airport/{icao}         → validate icao against config; SET
                                 towerguard:selected_airport. Returns
                                 {"airport": "<icao>"}. 404 if unknown.
  POST /confirm/{advisory_id}  → SET towerguard:confirmed:{id} <ISO8601 UTC>,
                                 idempotent (returns the existing timestamp on
                                 repeat). Returns {"advisory_id", "confirmed_at"}.
                                 Also XADDs a confirm shift event.
  POST /dismiss/{advisory_id}  → SET towerguard:dismissed:{id} <ISO8601 UTC>,
                                 idempotent (returns the existing timestamp on
                                 repeat). Optional JSON body {"reason": <enum>}
                                 with reason ∈ {already_separated, data_stale,
                                 visual_separation, false_geometry, other}; the
                                 reason is stored under towerguard:dismiss_reason:
                                 {id} and carried on the dismiss shift event.
                                 Returns {"advisory_id", "dismissed_at"}. Also
                                 XADDs a dismiss shift event.
  POST /reassess/{advisory_id} → publish a reassess_request to
                                 towerguard:reassess_request; rate-limited to 2
                                 per advisory (429 {"error": "reassess_limit"} on
                                 the third). Returns {"advisory_id",
                                 "request_id", "requested_at"}.
  POST /demo/{flag}/{state}    → flag ∈ {degraded, sparse, workload_surge},
                                 state ∈ {on, off}; SET/DEL towerguard:demo:{flag}.
                                 404 on unknown flag/state. Returns the full
                                 demo-flag state map.
  GET  /demo                   → current {flag: bool} director-switch state.
  GET  /lineage                → docs/lineage.md as text/markdown; 404 if absent.
  GET  /health                 → {"status": "ok", "redis": bool}

Same-origin only (no CORS). Run with uvicorn on 127.0.0.1:8800.
"""

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

import config
from dashboard.bridge import PubSubBridge
from dashboard.shift_stream import KIND_CONFIRM, KIND_DISMISS, xadd_shift_event
from dashboard.topics import (
    DEMO_FLAG_KEY_PREFIX,
    DEMO_FLAGS,
    SELECTED_AIRPORT_KEY,
    TOPIC_REASSESS_REQUEST,
)

logger = logging.getLogger(__name__)

# Key prefixes for the persisted human-in-the-loop decisions (contact.md §4).
CONFIRMED_KEY_PREFIX = "towerguard:confirmed:"
DISMISSED_KEY_PREFIX = "towerguard:dismissed:"
# v1.2: a dismissal may carry a canned reason chip (false-positive ground truth
# for threshold tuning); stored separately so the dismissed_at key stays an ISO
# timestamp exactly as before.
DISMISS_REASON_KEY_PREFIX = "towerguard:dismiss_reason:"
# v1.2 re-assess rate limit: a Redis counter per advisory caps manual re-assess
# requests so a controller cannot hammer the Orchestrator on one card.
REASSESS_COUNT_KEY_PREFIX = "towerguard:reassess_count:"
REASSESS_MAX_PER_ADVISORY = 2

# Canned dismiss reasons (frozen with the frontend agent — the chip set).
DISMISS_REASONS = frozenset(
    {
        "already_separated",
        "data_stale",
        "visual_separation",
        "false_geometry",
        "other",
    }
)

# Director-switch states accepted by POST /demo/{flag}/{state}.
DEMO_STATES = frozenset({"on", "off"})

_STATIC_DIR = Path(__file__).parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

# docs/lineage.md is authored by the frontend agent; we serve it if present.
_LINEAGE_MD = Path(__file__).parent.parent / "docs" / "lineage.md"


def _build_redis_client() -> redis.Redis:
    """Build a decode_responses Redis client from REDIS_URL (same as runner)."""
    url = os.getenv("REDIS_URL", config.REDIS_URL_DEFAULT)
    return redis.from_url(url, decode_responses=True)


def _utc_now_iso() -> str:
    """Current UTC time as ISO 8601 (matches the module envelope format)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _parse_dismiss_reason(request: Request) -> str | None:
    """Extract an optional, validated dismiss reason from the request body.

    The body is optional: an empty body, non-JSON, or an absent ``reason`` all
    resolve to None (a reasonless dismissal — unchanged v1.1 behaviour). A
    present ``reason`` must be one of the canned chips; anything else is a 400 so
    a typo cannot silently poison the false-positive ground-truth data.
    """
    raw = await request.body()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    reason = parsed.get("reason")
    if reason is None:
        return None
    if reason not in DISMISS_REASONS:
        raise HTTPException(status_code=400, detail=f"Unknown dismiss reason: {reason}")
    return reason


def _demo_state(redis_client: redis.Redis) -> dict:
    """Return {flag: bool} for every director switch, presence == on.

    A Redis error is treated as all-off so the dashboard always renders a valid
    switch panel rather than failing on a transient blip.
    """
    state: dict[str, bool] = {}
    for flag in DEMO_FLAGS:
        try:
            state[flag] = redis_client.get(f"{DEMO_FLAG_KEY_PREFIX}{flag}") is not None
        except Exception:
            state[flag] = False
    return {"flags": state}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the pub/sub bridge on startup, tear it down on shutdown."""
    loop = asyncio.get_running_loop()
    redis_client = _build_redis_client()
    bridge = PubSubBridge(redis_client, loop)
    bridge.start()
    app.state.redis = redis_client
    app.state.bridge = bridge
    try:
        yield
    finally:
        bridge.stop()


def _cors_origins() -> list[str]:
    """Allowed cross-origin hosts from TOWERGUARD_CORS_ORIGINS (comma-separated).

    Empty/unset → no CORS middleware is added (the app stays same-origin only, so
    local runs and tests are unchanged). Set this to the hosted dashboard's
    origin — or "*" for a throwaway demo — when serving the live SSE feed to a
    cloud-hosted frontend through a public tunnel (ngrok / cloudflared).
    """
    raw = os.getenv("TOWERGUARD_CORS_ORIGINS", "").strip()
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> FastAPI:
    """Application factory — keeps the app testable with a custom lifespan."""
    app = FastAPI(title="TowerGuard Dashboard", lifespan=lifespan)

    # Optional CORS for serving the live feed to a cross-origin (cloud-hosted)
    # frontend via a public tunnel. Off unless TOWERGUARD_CORS_ORIGINS is set, so
    # the default same-origin behaviour (and the tests) are untouched.
    origins = _cors_origins()
    if origins:
        wildcard = "*" in origins
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            # "*" + credentials is rejected by browsers; only allow credentials
            # when origins are explicitly enumerated.
            allow_credentials=not wildcard,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Static files. The directory is the frontend agent's domain; we only mount
    # it. mkdir(exist_ok=True) so the mount does not fail before they land files.
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        """Serve the dashboard shell built by the frontend agent."""
        return FileResponse(str(_INDEX_HTML))

    @app.get("/events")
    async def events(request: Request) -> EventSourceResponse:
        """SSE stream: replay cached last-of-each-type, then the most recent
        shift events (time order), then live messages."""
        bridge: PubSubBridge = request.app.state.bridge
        # register() seeds the queue with the cached last-of-each-type replay;
        # the shift-event backlog is enqueued after it so the dashboard renders
        # current state first, then recent shift-log history chronologically.
        queue = bridge.register()
        for message in bridge.replay_shift_events():
            queue.put_nowait(message)

        async def event_generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    message = await queue.get()
                    # EventSourceResponse renders this dict as
                    # `event: <event>\ndata: <data>\n\n`.
                    yield {"event": message.event, "data": message.data}
            finally:
                bridge.unregister(queue)

        return EventSourceResponse(event_generator())

    @app.get("/airports")
    async def airports() -> dict:
        """List the configured airports and the currently selected one.

        The selected airport comes from towerguard:selected_airport (set via
        POST /airport/{icao}); if unset or stale it falls back to the config
        default so the dashboard always renders a valid selection.
        """
        redis_client: redis.Redis = app.state.redis
        try:
            selected = redis_client.get(SELECTED_AIRPORT_KEY)
        except Exception:
            selected = None
        if selected not in config.AIRPORTS:
            selected = config.DEFAULT_AIRPORT
        return {
            "airports": [
                {"icao": a.icao, "name": a.name} for a in config.AIRPORTS.values()
            ],
            "selected": selected,
        }

    @app.post("/airport/{icao}")
    async def select_airport(icao: str) -> dict:
        """Select the monitored airport; the runner picks the change up on its
        next poll. 404 if the ICAO is not in the configured set."""
        if icao not in config.AIRPORTS:
            raise HTTPException(status_code=404, detail=f"Unknown airport: {icao}")
        redis_client: redis.Redis = app.state.redis
        redis_client.set(SELECTED_AIRPORT_KEY, icao)
        return {"airport": icao}

    @app.get("/lineage")
    async def lineage() -> PlainTextResponse:
        """Serve docs/lineage.md as markdown; 404 if the file does not exist.

        The file is authored by the frontend agent and may not be present yet.
        """
        if not _LINEAGE_MD.is_file():
            raise HTTPException(status_code=404, detail="lineage.md not found")
        return PlainTextResponse(
            _LINEAGE_MD.read_text(encoding="utf-8"),
            media_type="text/markdown; charset=utf-8",
        )

    @app.post("/confirm/{advisory_id}")
    async def confirm(advisory_id: str) -> dict:
        """Persist a controller confirmation; idempotent on repeat clicks.

        Uses SET NX so the first click writes "now" and repeat clicks return the
        already-stored timestamp instead of overwriting it. The first write also
        appends a confirm shift event so the decision shows in the shift log.
        """
        redis_client: redis.Redis = app.state.redis
        key = f"{CONFIRMED_KEY_PREFIX}{advisory_id}"
        now_iso = _utc_now_iso()
        # nx=True → only sets if absent; returns None if the key already existed.
        created = redis_client.set(key, now_iso, nx=True)
        if created:
            xadd_shift_event(
                redis_client,
                kind=KIND_CONFIRM,
                summary=f"Advisory {advisory_id} confirmed by controller",
                ref=advisory_id,
                timestamp=now_iso,
            )
        confirmed_at = now_iso if created else redis_client.get(key)
        return {"advisory_id": advisory_id, "confirmed_at": confirmed_at}

    @app.post("/dismiss/{advisory_id}")
    async def dismiss(advisory_id: str, request: Request) -> dict:
        """Persist a controller dismissal; idempotent on repeat clicks.

        Human-in-the-loop is not just "confirm": the controller may reject the
        escalation. Mirrors /confirm — SET NX so the first click writes "now" and
        repeats return the stored timestamp, and the first write appends a dismiss
        shift event for the relief-briefing narrative.

        The dismissed_at key stays a bare ISO timestamp (unchanged contract); an
        optional body {"reason": <enum>} is stored separately under
        towerguard:dismiss_reason:{id} and folded into the dismiss shift-event
        summary so the chosen chip surfaces in the shift log.
        """
        reason = await _parse_dismiss_reason(request)
        redis_client: redis.Redis = app.state.redis
        key = f"{DISMISSED_KEY_PREFIX}{advisory_id}"
        now_iso = _utc_now_iso()
        created = redis_client.set(key, now_iso, nx=True)
        if created:
            if reason is not None:
                redis_client.set(f"{DISMISS_REASON_KEY_PREFIX}{advisory_id}", reason)
            summary = f"Advisory {advisory_id} dismissed by controller"
            if reason is not None:
                summary = f"{summary} ({reason})"
            xadd_shift_event(
                redis_client,
                kind=KIND_DISMISS,
                summary=summary,
                ref=advisory_id,
                timestamp=now_iso,
            )
        dismissed_at = now_iso if created else redis_client.get(key)
        return {"advisory_id": advisory_id, "dismissed_at": dismissed_at}

    @app.post("/reassess/{advisory_id}")
    async def reassess(advisory_id: str):
        """Publish a controller-initiated re-assess request; capped at 2/advisory.

        Increments a per-advisory Redis counter; the third request returns 429
        {"error": "reassess_limit"} instead of publishing. Otherwise a
        reassess_request envelope is published to towerguard:reassess_request for
        the Orchestrator, which must always reply (never silent) on the advisory
        / advisory_lifecycle topics. The shift-event log entry for the re-assess
        is written by the Orchestrator when it acts, not here.
        """
        redis_client: redis.Redis = app.state.redis
        count_key = f"{REASSESS_COUNT_KEY_PREFIX}{advisory_id}"
        count = redis_client.incr(count_key)
        if count > REASSESS_MAX_PER_ADVISORY:
            return JSONResponse(status_code=429, content={"error": "reassess_limit"})

        request_id = f"RAS-{secrets.token_hex(2)}"
        requested_at = _utc_now_iso()
        payload = {
            "type": "reassess_request",
            "request_id": request_id,
            "advisory_id": advisory_id,
            "requested_at": requested_at,
            "reason": "controller_manual",
        }
        redis_client.publish(
            TOPIC_REASSESS_REQUEST, json.dumps(payload, separators=(",", ":"))
        )
        return {
            "advisory_id": advisory_id,
            "request_id": request_id,
            "requested_at": requested_at,
        }

    @app.post("/demo/{flag}/{state}")
    async def set_demo_flag(flag: str, state: str) -> dict:
        """Toggle a director switch: SET towerguard:demo:{flag} on, DEL off.

        404 on an unknown flag or state. The runner reads these keys each cycle
        (degraded → OpenSky-unavailable path; sparse → 2-aircraft background;
        workload_surge → staffing forced to 60%). Returns the full flag map.
        """
        if flag not in DEMO_FLAGS:
            raise HTTPException(status_code=404, detail=f"Unknown demo flag: {flag}")
        if state not in DEMO_STATES:
            raise HTTPException(status_code=404, detail=f"Unknown demo state: {state}")
        redis_client: redis.Redis = app.state.redis
        key = f"{DEMO_FLAG_KEY_PREFIX}{flag}"
        if state == "on":
            redis_client.set(key, "1")
        else:
            redis_client.delete(key)
        return _demo_state(redis_client)

    @app.get("/demo")
    async def get_demo() -> dict:
        """Return the current {flag: bool} state of every director switch."""
        return _demo_state(app.state.redis)

    @app.get("/health")
    async def health() -> dict:
        """Liveness + Redis reachability."""
        redis_client: redis.Redis = app.state.redis
        try:
            redis_ok = bool(redis_client.ping())
        except Exception:
            redis_ok = False
        return {"status": "ok", "redis": redis_ok}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(app, host="127.0.0.1", port=8800)
