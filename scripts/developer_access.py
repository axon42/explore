"""Print the local owner's developer key for entry into Explore; never a provider key."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Settings


def main():
    path = Settings().data_dir / "developer-admin.key"
    if not path.is_file():
        raise SystemExit("Start Explore once to create its local developer admin key.")
    print(path.read_text().strip())


if __name__ == "__main__":
    main()
