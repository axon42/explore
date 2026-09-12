"""Build a local ad-hoc signed helper; distribution signing is a separate release step."""

import platform
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app = ROOT / "native/macos/build/Explore Capture.app"
bin_dir = app / "Contents/MacOS"
bin_dir.mkdir(parents=True, exist_ok=True)
shutil.copyfile(ROOT / "native/macos/Info.plist", app / "Contents/Info.plist")
subprocess.run(
    [
        "xcrun",
        "swiftc",
        "-swift-version",
        "5",
        "-O",
        "-target",
        f"{platform.machine()}-apple-macos13.0",
        "-module-cache-path",
        str(ROOT / "native/macos/build/module-cache"),
        str(ROOT / "native/macos/Capture.swift"),
        "-o",
        str(bin_dir / "ExploreCapture"),
    ],
    check=True,
)
subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
subprocess.run([str(bin_dir / "ExploreCapture"), "--self-test"], check=True)
print("Built local Explore Capture helper")
