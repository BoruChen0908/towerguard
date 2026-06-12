"""TowerGuard dashboard server — FastAPI + SSE bridge over Redis pub/sub.

Interface contract (frozen with the frontend agent):
  GET  /                       → dashboard/static/index.html
  GET  /static/*               → static files
  GET  /events                 → SSE stream; `event: <type>\\ndata: <json>\\n\\n`
                                 type ∈ {traffic_density, conflict_geometry,
                                 workload_index, advisory, aircraft_snapshot,
                                 briefing}. First five forward the Redis topic
                                 JSON verbatim; briefing data is
                                 {"advisory_id", "markdown"}.
  POST /confirm/{advisory_id}  → SET towerguard:confirmed:{id} <ISO8601 UTC>,
                                 idempotent (returns the existing timestamp on
                                 repeat). Returns {"advisory_id", "confirmed_at"}.
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
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

import config
from dashboard.bridge import PubSubBridge

logger = logging.getLogger(__name__)

# Key prefix for the persisted confirmation timestamps (contact.md §4).
CONFIRMED_KEY_PREFIX = "towerguard:confirmed:"

_STATIC_DIR = Path(__file__).parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"


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
        """SSE stream: replay cached last-of-each-type, then live messages."""
        bridge: PubSubBridge = request.app.state.bridge
        queue = bridge.register()

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

    @app.post("/confirm/{advisory_id}")
    async def confirm(advisory_id: str) -> dict:
        """Persist a controller confirmation; idempotent on repeat clicks.

        Uses SET NX so the first click writes "now" and repeat clicks return the
        already-stored timestamp instead of overwriting it.
        """
        redis_client: redis.Redis = app.state.redis
        key = f"{CONFIRMED_KEY_PREFIX}{advisory_id}"
        now_iso = _utc_now_iso()
        # nx=True → only sets if absent; returns None if the key already existed.
        created = redis_client.set(key, now_iso, nx=True)
        confirmed_at = now_iso if created else redis_client.get(key)
        return {"advisory_id": advisory_id, "confirmed_at": confirmed_at}

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
