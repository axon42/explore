"""Explicit synthetic participants for tests that exercise a running interview."""

from app.discovery import Discovery
from app.lifecycle import Lifecycle
from app.reports import Reports

PEOPLE = [
    {
        "speaker_id": "cofounder",
        "name": "Alex Test",
        "interview_role": "interviewer",
        "job_role": "Cofounder",
    },
    {
        "speaker_id": "customer",
        "name": "Sam Test",
        "interview_role": "customer",
        "job_role": "Operations lead",
    },
]


def start(client, mid):
    client.put("/settings/test-mode", json={"enabled": True}).raise_for_status()
    roster = client.get(f"/meetings/{mid}/participants").json()
    if not roster["participants"]:
        roster = client.put(
            f"/meetings/{mid}/participants",
            json={"revision": roster["revision"], "participants": PEOPLE},
        ).json()
    response = client.post(
        f"/meetings/{mid}/start", json={"revision": roster["revision"], "mode": "test"}
    )
    response.raise_for_status()
    return response.json()


def start_local(storage, mid):
    life = Lifecycle(storage)
    life.test_mode(True)
    roster = Reports(storage).participants(mid)
    if not roster["participants"]:
        roster = Reports(storage).participants(mid, roster["revision"], PEOPLE)
    life.start(mid, roster["revision"], "test")
    return Discovery(storage).detail(mid)


def session(storage, title):
    draft = Discovery(storage).create("default", title)
    return start_local(storage, draft["meeting_id"])["session"]
