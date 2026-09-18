"""Explicit synthetic participants for tests that exercise a running interview."""

from app.discovery import Discovery
from app.lifecycle import Lifecycle
from app.manual_analysis import ManualAnalysis
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


def start(client, mid, automatic=True):
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
    detail = response.json()
    if automatic:
        sid = detail["session"]["id"]
        current = client.get(f"/sessions/{sid}/experiment").json()["scheduling"]
        client.patch(
            f"/sessions/{sid}/analysis-scheduling",
            json={"mode": "automatic", "revision": current["revision"]},
        ).raise_for_status()
    return detail


def start_local(storage, mid):
    life = Lifecycle(storage)
    life.test_mode(True)
    roster = Reports(storage).participants(mid)
    if not roster["participants"]:
        roster = Reports(storage).participants(mid, roster["revision"], PEOPLE)
    life.start(mid, roster["revision"], "test")
    detail = Discovery(storage).detail(mid)
    prefs = ManualAnalysis(storage)
    sid = detail["session"]["id"]
    prefs.update(sid, "automatic", prefs.settings(sid)["revision"])
    return detail


def session(storage, title):
    draft = Discovery(storage).create("default", title)
    return start_local(storage, draft["meeting_id"])["session"]


def automatic_session(storage, title):
    """Legacy automatic-analysis tests explicitly opt into that schedule."""
    result = storage.create(title)
    ManualAnalysis(storage).update(result["id"], "automatic", 0)
    return result
