"""Capture a real live-validation SSE session into a replay file.

Connects to the running dashboard SSE feed, records every named event with
its arrival offset, and writes a JSON array the N18 panel can replay on a
timeline — a bulletproof "real data, no live dependency" demo.

    python3 scripts/capture_live_session.py --seconds 160 \
        --out contracts/live_session.replay.json
"""

import argparse
import json
import time

import requests

DEFAULT_URL = "http://127.0.0.1:8800/events"


def capture(url: str, seconds: float) -> list[dict]:
    frames: list[dict] = []
    t0 = time.perf_counter()
    deadline = t0 + seconds
    event_name: str | None = None

    with requests.get(url, stream=True, timeout=seconds + 10) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if time.perf_counter() >= deadline:
                break
            if raw is None:
                continue
            line = raw.rstrip("\r")
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if not event_name:
                    continue
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = payload
                frames.append(
                    {
                        "offset_s": round(time.perf_counter() - t0, 2),
                        "event": event_name,
                        "data": data,
                    }
                )
                event_name = None
    return frames


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--seconds", type=float, default=160.0)
    ap.add_argument("--out", default="contracts/live_session.replay.json")
    args = ap.parse_args()

    frames = capture(args.url, args.seconds)

    by_type: dict[str, int] = {}
    for f in frames:
        by_type[f["event"]] = by_type.get(f["event"], 0) + 1

    out = {
        "meta": {
            "captured_seconds": args.seconds,
            "frame_count": len(frames),
            "event_counts": by_type,
            "note": "Real captured session from the live validation pipeline "
            "(deterministic modules + Claude phrasing). Replay on a timeline; "
            "no live feed required.",
        },
        "frames": frames,
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"wrote {len(frames)} frames to {args.out}")
    print("event counts:", json.dumps(by_type))


if __name__ == "__main__":
    main()
