"""Redis pub/sub → per-client asyncio queue bridge.

A single background thread blocks on ``pubsub.listen()`` and, for every message:
  1. re-shapes it into an ``SSEMessage`` (event type + data string),
  2. stores it as the "last known" message for that type (memory cache),
  3. fans it out to every connected SSE client's asyncio queue.

The listen loop runs in a plain thread (Redis-py pub/sub is blocking); client
queues live on the asyncio event loop, so cross-thread hand-off goes through
``loop.call_soon_threadsafe``. This keeps the event loop unblocked while still
delivering messages with no polling.

New clients are seeded with the cached last message of each type before they
start receiving live traffic, so a freshly opened dashboard renders immediately
instead of waiting up to a full 60 s runner cycle.
"""

import json
import logging
import threading
import time
from asyncio import AbstractEventLoop, Queue
from dataclasses import dataclass
from typing import Optional

import redis

from dashboard.topics import (
    SUBSCRIBED_TOPICS,
    TOPIC_BRIEFING,
    TOPIC_TO_EVENT,
)

logger = logging.getLogger(__name__)

# Bounded per-client queue: if a client falls catastrophically behind we drop
# the oldest message rather than grow memory without limit. 100 messages is far
# more than the ~6 types ever buffer at the runner's 60 s cadence.
_CLIENT_QUEUE_MAXSIZE = 100


@dataclass(frozen=True)
class SSEMessage:
    """One SSE-ready message: an event type and its JSON `data` payload string."""

    event: str
    data: str


class PubSubBridge:
    """Owns the Redis subscription thread, the last-message cache, and clients."""

    def __init__(self, redis_client: redis.Redis, loop: AbstractEventLoop) -> None:
        self._redis = redis_client
        self._loop = loop
        # event_type -> last SSEMessage seen (for replay on new connections)
        self._cache: dict[str, SSEMessage] = {}
        # Connected client queues. Guarded by _lock because the listen thread
        # iterates it while request coroutines add/remove from it.
        self._clients: set[Queue[SSEMessage]] = set()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self._stop = threading.Event()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Subscribe and spawn the background listen thread (idempotent)."""
        if self._thread is not None:
            return
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        self._pubsub.subscribe(*SUBSCRIBED_TOPICS)
        self._thread = threading.Thread(
            target=self._listen_loop, name="towerguard-pubsub", daemon=True
        )
        self._thread.start()
        logger.info("PubSubBridge subscribed to %s", ", ".join(SUBSCRIBED_TOPICS))

    def stop(self) -> None:
        """Signal the listen thread to exit and tear down the subscription."""
        self._stop.set()
        if self._pubsub is not None:
            # Closing the connection unblocks the listen() call.
            try:
                self._pubsub.close()
            except Exception as exc:  # pragma: no cover - best-effort teardown
                logger.debug("pubsub close during shutdown raised: %s", exc)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # -- client registration ----------------------------------------------

    def register(self) -> Queue[SSEMessage]:
        """Create a queue for a new client, seeded with the cached last message
        of each type (replay), then return it for live streaming."""
        queue: Queue[SSEMessage] = Queue(maxsize=_CLIENT_QUEUE_MAXSIZE)
        with self._lock:
            for message in self._cache.values():
                queue.put_nowait(message)
            self._clients.add(queue)
        return queue

    def unregister(self, queue: "Queue[SSEMessage]") -> None:
        """Remove a client queue (on disconnect)."""
        with self._lock:
            self._clients.discard(queue)

    def cached_messages(self) -> list[SSEMessage]:
        """Snapshot of the current last-message cache (used in tests)."""
        with self._lock:
            return list(self._cache.values())

    # -- listen loop -------------------------------------------------------

    def _listen_loop(self) -> None:
        assert self._pubsub is not None
        # Poll with get_message() instead of blocking listen(): redis-py >= 8
        # applies a default socket timeout, so listen() raises TimeoutError on
        # a quiet subscription. Polling also lets us honour _stop promptly.
        while not self._stop.is_set():
            try:
                raw = self._pubsub.get_message(timeout=1.0)
            except TimeoutError:
                continue
            except Exception as exc:  # pragma: no cover - thread-level guard
                if self._stop.is_set():
                    break
                logger.error("pubsub listen loop error: %s", exc, exc_info=True)
                time.sleep(1.0)
                continue
            if raw is None:
                continue
            message = self._to_sse_message(raw)
            if message is not None:
                self._dispatch(message)

    @staticmethod
    def _to_sse_message(raw: dict) -> Optional[SSEMessage]:
        """Convert a raw redis-py pub/sub message into an SSEMessage.

        For every type except `briefing` the topic JSON is forwarded verbatim.
        `briefing` is re-shaped to {"advisory_id", "markdown"} per the dashboard
        contract (the producer is expected to publish that shape; we forward it
        through but normalise the data to a compact JSON string).
        """
        if raw.get("type") != "message":
            return None
        channel = _as_str(raw.get("channel"))
        event = TOPIC_TO_EVENT.get(channel)
        if event is None:
            return None

        data = _as_str(raw.get("data"))
        if channel == TOPIC_BRIEFING:
            data = _normalise_briefing(data)
        return SSEMessage(event=event, data=data)

    def _dispatch(self, message: SSEMessage) -> None:
        """Cache the message and fan it out to every client queue.

        Runs on the listen thread; queue mutations are scheduled onto the event
        loop with call_soon_threadsafe so asyncio internals stay single-thread.
        """
        with self._lock:
            self._cache[message.event] = message
            clients = list(self._clients)
        for queue in clients:
            self._loop.call_soon_threadsafe(self._offer, queue, message)

    @staticmethod
    def _offer(queue: "Queue[SSEMessage]", message: SSEMessage) -> None:
        """Put a message on a client queue, dropping the oldest if full."""
        if queue.full():
            try:
                queue.get_nowait()
            except Exception:  # pragma: no cover - race with consumer
                pass
        try:
            queue.put_nowait(message)
        except Exception as exc:  # pragma: no cover - bounded queue race
            logger.debug("dropping message for slow client: %s", exc)


def _as_str(value: object) -> str:
    """Coerce a redis-py field (bytes or str depending on decode_responses)."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return "" if value is None else str(value)


def _normalise_briefing(data: str) -> str:
    """Validate/compact the briefing payload to {"advisory_id", "markdown"}.

    The producer (mock_katherine / Narrator) is expected to publish exactly this
    shape; if it doesn't parse we forward the raw string unchanged rather than
    drop the message, leaving the malformed payload visible rather than silent.
    """
    try:
        parsed = json.loads(data)
        shaped = {
            "advisory_id": parsed.get("advisory_id", ""),
            "markdown": parsed.get("markdown", ""),
        }
        return json.dumps(shaped, separators=(",", ":"))
    except (ValueError, AttributeError):
        return data
