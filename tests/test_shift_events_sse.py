"""Tests for shift-event SSE delivery in dashboard/bridge.py.

Covers:
  - replay_shift_events: most-recent-N in time order, as shift_event SSEMessages
  - shift events are NOT cached (they are a log, not a last-of-type snapshot)
  - end-to-end: a stream entry XADDed after start() reaches a registered client
"""

import asyncio
import json
import time

import fakeredis

from dashboard.bridge import PubSubBridge, SSEMessage
from dashboard.shift_stream import KIND_ADVISORY, xadd_shift_event
from dashboard.topics import EVENT_SHIFT_EVENT


class TestReplayShiftEvents:
    def test_replay_returns_time_ordered_shift_messages(self):
        loop = asyncio.new_event_loop()
        try:
            fake = fakeredis.FakeRedis(decode_responses=True)
            for i in range(3):
                xadd_shift_event(
                    fake, kind=KIND_ADVISORY, summary=f"s{i}", ref=f"ADV-{i}"
                )
            bridge = PubSubBridge(fake, loop)

            replayed = bridge.replay_shift_events()
            assert all(m.event == EVENT_SHIFT_EVENT for m in replayed)
            summaries = [json.loads(m.data)["summary"] for m in replayed]
            assert summaries == ["s0", "s1", "s2"]
        finally:
            loop.close()

    def test_replay_empty_stream_is_empty(self):
        loop = asyncio.new_event_loop()
        try:
            fake = fakeredis.FakeRedis(decode_responses=True)
            bridge = PubSubBridge(fake, loop)
            assert bridge.replay_shift_events() == []
        finally:
            loop.close()


class TestShiftEventsNotCached:
    def test_dispatch_with_cache_false_skips_cache_but_fans_out(self):
        loop = asyncio.new_event_loop()
        try:
            fake = fakeredis.FakeRedis(decode_responses=True)
            bridge = PubSubBridge(fake, loop)
            queue = bridge.register()

            msg = SSEMessage(event=EVENT_SHIFT_EVENT, data='{"kind":"advisory"}')
            bridge._dispatch(msg, cache=False)
            loop.call_soon(loop.stop)
            loop.run_forever()

            # delivered to the client...
            assert queue.get_nowait() == msg
            # ...but not retained in the last-message cache
            assert EVENT_SHIFT_EVENT not in bridge._cache
        finally:
            loop.close()


class TestStreamLoopEndToEnd:
    def test_xadded_event_reaches_registered_client(self):
        """Start the bridge, register a client, XADD an entry, and confirm it is
        delivered as a shift_event (the stream loop tails new entries)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            fake = fakeredis.FakeRedis(decode_responses=True)
            bridge = PubSubBridge(fake, loop)
            bridge.start()
            try:
                queue = bridge.register()
                # Let the stream thread reach its XREAD($) baseline before XADD.
                time.sleep(0.3)
                xadd_shift_event(
                    fake, kind=KIND_ADVISORY, summary="live advisory", ref="ADV-9"
                )

                async def wait_for_message():
                    return await asyncio.wait_for(queue.get(), timeout=3.0)

                message = loop.run_until_complete(wait_for_message())
                assert message.event == EVENT_SHIFT_EVENT
                payload = json.loads(message.data)
                assert payload["summary"] == "live advisory"
                assert payload["ref"] == "ADV-9"
            finally:
                bridge.stop()
        finally:
            loop.close()
            asyncio.set_event_loop(None)
