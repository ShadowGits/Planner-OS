#!/usr/bin/env python3
"""Deliver a verified APK to the user's established latest-app folder."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
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
    metadata_path = source.parent / "output-metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text())
        artifact = next(item for item in metadata["elements"] if item["outputFile"] == source.name)
        version = artifact["versionName"]
    except (OSError, ValueError, KeyError, StopIteration, TypeError):
        parser.error("Build metadata is missing or does not match this APK; use the APK from its Gradle output folder")
    if not isinstance(version, str) or not re.fullmatch(r"\d+(?:\.\d+)*(?:[-+][A-Za-z0-9.-]+)?", version):
        parser.error("Build metadata contains an invalid APK version")
    filename = f"Planner-OS-Android-{version}.apk"
    for folder in (ROOT / "android/artifacts", ROOT / "artifacts", DESTINATION):
        folder.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".planner-apk-", dir=folder)
        try:
            with os.fdopen(fd, "wb") as target, source.open("rb") as original:
                shutil.copyfileobj(original, target)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, folder / filename)
        finally:
            Path(temporary).unlink(missing_ok=True)
        (folder / (filename + ".sha256")).write_text(digest + "  " + filename + "\n")
        # Replace the identical old unnamed copy, preserving all other releases.
        legacy = folder / "Planner-OS-Android.apk"
        if legacy.exists() and hashlib.sha256(legacy.read_bytes()).hexdigest() == digest:
            legacy.unlink()
            (folder / "Planner-OS-Android.apk.sha256").unlink(missing_ok=True)
        print(folder / filename)
    print("SHA-256:", digest)


if __name__ == "__main__":
    main()
