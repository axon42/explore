"""The CLI and development endpoint both use this public WebSocket producer."""

import argparse
import asyncio
import json
import os

from websockets.asyncio.client import connect


def demo_events():
    def event(event_id, segment, revision, speaker, start, end, text, final):
        return {
            "event_id": event_id,
            "segment_id": segment,
            "revision": revision,
            "speaker_id": speaker.lower(),
            "speaker_name": speaker,
            "start_ms": start,
            "end_ms": end,
            "text": text,
            "is_final": final,
        }

    first = event(
        "demo-2",
        "demo-a",
        2,
        "Alex",
        0,
        3800,
        "Let's walk through the requests that came in this morning.",
        True,
    )
    return [
        (0.4, event("demo-1", "demo-a", 1, "Alex", 0, 1600, "Let's walk through", False)),
        (2.0, first),
        (1.5, event("demo-3", "demo-b", 1, "Sam", 4500, 6200, "I grouped them by", False)),
        (
            1.6,
            event(
                "demo-4",
                "demo-b",
                2,
                "Sam",
                4500,
                9000,
                "I grouped them by priority. There are three we should look at today.",
                True,
            ),
        ),
        (0.5, first),  # exact duplicate
        (0.5, event("demo-5", "demo-b", 0, "Sam", 4500, 6000, "Old interim", False)),
        (
            1.4,
            event(
                "demo-6",
                "demo-b",
                3,
                "Sam",
                4500,
                9000,
                "I grouped them by priority. There are four we should look at today.",
                True,
            ),
        ),
        (
            1.8,
            event(
                "demo-7", "demo-c", 1, "Alex", 11500, 13500, "That sounds good. Let's start", False
            ),
        ),
        (
            2.0,
            event(
                "demo-8",
                "demo-c",
                2,
                "Alex",
                11500,
                16000,
                "That sounds good. Let's start with the onboarding request and go from there.",
                True,
            ),
        ),
    ]


async def replay(url: str, token: str = "", speed: float = 1):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with connect(url, additional_headers=headers, max_size=65536) as ws:
        for delay, event in demo_events():
            await asyncio.sleep(delay / speed)
            await ws.send(json.dumps(event))
            reply = json.loads(await ws.recv())
            if reply["type"] == "error":
                raise RuntimeError(reply["code"])


def main():
    parser = argparse.ArgumentParser(description="Replay a deterministic two-speaker meeting")
    parser.add_argument("session_id")
    parser.add_argument("--base-url", default="ws://127.0.0.1:8000")
    parser.add_argument("--speed", type=float, default=1)
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("--speed must be positive")
    asyncio.run(
        replay(
            f"{args.base_url}/sessions/{args.session_id}/ingest",
            os.environ.get("INGESTION_TOKEN", ""),
            args.speed,
        )
    )


if __name__ == "__main__":
    main()
