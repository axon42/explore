"""Persist the local application's analysis choice, independently of provider secrets."""

from .models import DomainError


class AnalysisPreferences:
    def __init__(self, storage, initial_strategy="legacy"):
        self.storage = storage
        self.initial_strategy = initial_strategy

    def get(self):
        with self.storage.connection() as db:
            row = db.execute(
                "SELECT strategy, revision FROM analysis_preferences WHERE id=1"
            ).fetchone()
            return dict(row) if row else {"strategy": self.initial_strategy, "revision": 0}

    def update(self, strategy, revision):
        if strategy not in ("legacy", "topics"):
            raise DomainError("invalid_strategy", "Unknown analysis mode.", 422)
        with self.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision FROM analysis_preferences WHERE id=1").fetchone()
            current = row["revision"] if row else 0
            if revision != current:
                raise DomainError(
                    "conflict",
                    "Analysis mode changed in another tab. Review the setting and retry.",
                )
            db.execute(
                "INSERT INTO analysis_preferences VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET strategy=excluded.strategy, "
                "revision=excluded.revision",
                (strategy, current + 1),
            )
            return {"strategy": strategy, "revision": current + 1}
