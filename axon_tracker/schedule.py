"""python -m axon_tracker.schedule [--data-dir data]: decide whether this week's capture is still due."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from .model import date


def capture_due(manifest, now):
    """Due unless an accepted capture already exists in the current ISO week (UTC).

    latest/manifest.json reflects the last completed run, accepted or not; a directory
    failure leaves the previous one in place. Either way, a missed week stays due.
    """
    if not manifest or not manifest.get("quality_ok"):
        return True
    return date(manifest["captured_at"]).isocalendar()[:2] != now.isocalendar()[:2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    path = Path(args.data_dir) / "latest" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    due = capture_due(manifest, dt.datetime.now(dt.timezone.utc))
    latest = f"{manifest['captured_at']} (quality_ok={manifest['quality_ok']})" if manifest else "none"
    print(f"Latest capture: {latest}. Capture due: {due}", flush=True)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"due={str(due).lower()}\n")


if __name__ == "__main__":
    main()
