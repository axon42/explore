"""Cheap, replaceable overview formatting; no provider calls or storage access."""


class OverviewStrategy:
    def build(self, memory, fallback=""):
        # The full structured record remains in memory and reports. This is only the
        # compact existing UI's display projection, not a checkpoint for future reasoning.
        items = memory["claims"][-8:]
        return {
            "summary": "\n".join(
                ("Hypothesis: " if item["basis"] == "inferred" else "") + item["text"]
                for item in items
            )[:2000]
            or fallback,
            "input_version": memory["cursor"],
            "context_version": memory["context_version"],
        }
