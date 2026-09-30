#!/usr/bin/env python3
"""Deliver a verified APK to the user's established latest-app folder."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = Path.home() / "Library/CloudStorage/GoogleDrive-sparsh0304@gmail.com/My Drive/ChatGPT projects/PLANNER OS LATEST APP"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "android/app/build/outputs/apk/debug/app-debug.apk")
    parser.add_argument("--sha256", required=True, help="SHA-256 of the APK whose build and signing identity were verified")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != args.sha256.lower():
        parser.error("APK does not match the verified build's SHA-256; refusing delivery")
    with zipfile.ZipFile(source) as apk:
        if not {"AndroidManifest.xml", "classes.dex"}.issubset(apk.namelist()) or apk.testzip():
            parser.error("APK contents are invalid")
    for folder in (ROOT / "android/artifacts", ROOT / "artifacts", DESTINATION):
        folder.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".planner-apk-", dir=folder)
        try:
            with os.fdopen(fd, "wb") as target, source.open("rb") as original:
                shutil.copyfileobj(original, target)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, folder / "Planner-OS-Android.apk")
        finally:
            Path(temporary).unlink(missing_ok=True)
        (folder / "Planner-OS-Android.apk.sha256").write_text(digest + "  Planner-OS-Android.apk\n")
        print(folder / "Planner-OS-Android.apk")
    print("SHA-256:", digest)


if __name__ == "__main__":
    main()
