import asyncio
import json

import pytest

from app.zoom_rtms import RTMSClient, StreamError, TranscriptNormalizer, zoom_url


@pytest.mark.parametrize(
    "url",
    [
        "ws://rtms-us.zoom.us",
        "wss://localhost",
        "wss://127.0.0.1",
        "wss://rtms-us.zoom.us.evil.test",
        "wss://rtms-us.zoom.us:444",
        "wss://user:secret@rtms-us.zoom.us",
        "wss://rtms-us.zoom.us/#x",
    ],
)
def test_unapproved_endpoints(url):
    with pytest.raises(StreamError):
        zoom_url(url)


def test_packet_identity_and_speakers():
    normalizer = TranscriptNormalizer("stream-one")
    packet = {"timestamp": 10000, "user_id": 1, "user_name": "Test", "data": "Synthetic text"}
    first = normalizer.event(packet)
    assert first == normalizer.event(packet)
    assert first.start_ms == first.end_ms == 0
    assert first.speaker_id == "zoom-1"
    assert normalizer.event({**packet, "timestamp": 12000}).start_ms == 2000
    assert normalizer.event({**packet, "data": "Different"}).event_id != first.event_id
    assert normalizer.event({**packet, "user_id": 2}).event_id != first.event_id
    assert TranscriptNormalizer("stream-two").event(packet).event_id != first.event_id


@pytest.mark.parametrize(
    "change", [{"timestamp": True}, {"user_id": "1"}, {"data": ""}, {"data": "x" * 20001}]
)
def test_invalid_packets(change):
    with pytest.raises(StreamError):
        TranscriptNormalizer("test").event(
            {"timestamp": 100, "user_id": 1, "data": "Test", **change}
        )


async def test_handshakes_keepalive_transcript_and_cancellation():
    class Socket:
        def __init__(self, messages):
            self.messages = asyncio.Queue()
            for item in messages:
                self.messages.put_nowait(json.dumps(item))
            self.sent = []
            self.closed = False

        async def send(self, message):
            self.sent.append(json.loads(message))

        async def recv(self):
            return await self.messages.get()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

    signaling = Socket(
        [
            {"msg_type": 12, "timestamp": 100},
            {
                "msg_type": 2,
                "status_code": 0,
                "media_server": {"server_urls": {"transcript": "wss://rtms-us.zoom.us/media"}},
            },
        ]
    )
    media = Socket(
        [
            {"msg_type": 4, "status_code": 0},
            {
                "msg_type": 17,
                "content": {"timestamp": 100, "user_id": 1, "data": "Synthetic transcript"},
            },
        ]
    )
    sockets = iter([signaling, media])
    received = asyncio.Event()
    events = []
    ready_count = []

    def connector(url, **options):
        assert options["proxy"] is None and options["max_queue"] == 16
        return next(sockets)

    async def deliver(event):
        events.append(event)
        received.set()

    async def ready():
        ready_count.append(1)

    task = asyncio.create_task(
        RTMSClient("key", "secret", connector).run(
            {
                "session_id": "session",
                "rtms_stream_id": "stream",
                "server_urls": "wss://rtms-us.zoom.us/signal",
            },
            deliver,
            ready,
        )
    )
    await asyncio.wait_for(received.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert signaling.closed and media.closed
    assert ready_count == [1]
    assert events[0].text == "Synthetic transcript"
    assert media.sent[0]["media_type"] == 8
    assert signaling.sent[1] == {"msg_type": 13, "timestamp": 100}
    assert signaling.sent[-1]["msg_type"] == 7
