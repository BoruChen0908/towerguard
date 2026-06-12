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
                                 repeat). Returns {"advisory_id", "dismissed_at"}.
                                 Also XADDs a dismiss shift event.
  GET  /lineage                → docs/lineage.md as text/markdown; 404 if absent.
  GET  /health                 → {"status": "ok", "redis": bool}

Same-origin only (no CORS). Run with uvicorn on 127.0.0.1:8800.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

import config
from dashboard.bridge import PubSubBridge
from dashboard.shift_stream import KIND_CONFIRM, KIND_DISMISS, xadd_shift_event
from dashboard.topics import SELECTED_AIRPORT_KEY

logger = logging.getLogger(__name__)

# Key prefixes for the persisted human-in-the-loop decisions (contact.md §4).
CONFIRMED_KEY_PREFIX = "towerguard:confirmed:"
DISMISSED_KEY_PREFIX = "towerguard:dismissed:"

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


def create_app() -> FastAPI:
    """Application factory — keeps the app testable with a custom lifespan."""
    app = FastAPI(title="TowerGuard Dashboard", lifespan=lifespan)

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
    async def dismiss(advisory_id: str) -> dict:
        """Persist a controller dismissal; idempotent on repeat clicks.

        Human-in-the-loop is not just "confirm": the controller may reject the
        escalation. Mirrors /confirm — SET NX so the first click writes "now" and
        repeats return the stored timestamp, and the first write appends a dismiss
        shift event for the relief-briefing narrative.
        """
        redis_client: redis.Redis = app.state.redis
        key = f"{DISMISSED_KEY_PREFIX}{advisory_id}"
        now_iso = _utc_now_iso()
        created = redis_client.set(key, now_iso, nx=True)
        if created:
            xadd_shift_event(
                redis_client,
                kind=KIND_DISMISS,
                summary=f"Advisory {advisory_id} dismissed by controller",
                ref=advisory_id,
                timestamp=now_iso,
            )
        dismissed_at = now_iso if created else redis_client.get(key)
        return {"advisory_id": advisory_id, "dismissed_at": dismissed_at}

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
