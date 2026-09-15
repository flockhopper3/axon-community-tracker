"""python -m axon_tracker [--data-dir data] [--delay 1.0]"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from .collect import PublicClient
from .export import csv_file, exports, json_file
from .model import (DIRECTORY_URL, STATS_BASE, METRICS, ORG_PATTERN, changes, growth, iso,
                    make_communities, make_orgs, quality, rankings, summaries, validate_directory)


def load_history(data_dir):
    history = []
    for path in sorted((data_dir / "runs").glob("*/snapshot.json")):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if snapshot.get("schema_version") != 1:
            raise ValueError(f"Unsupported snapshot schema in {path}")
        history.append(snapshot)
    return history


def run(args):
    now = dt.datetime.now(dt.timezone.utc)
    captured_at, run_id = iso(now), now.strftime("%Y-%m-%dT%H%M%SZ")
    data_dir = Path(args.data_dir)
    root = data_dir / "runs" / run_id
    root.mkdir(parents=True, exist_ok=False)
    history = load_history(data_dir)
    accepted = [snapshot for snapshot in history if snapshot["manifest"]["quality_ok"]]
    previous = accepted[-1] if accepted else None
    client = PublicClient(delay=args.delay, timeout=args.timeout, retries=args.retries)
    print(f"Collecting {DIRECTORY_URL}", flush=True)
    directory = client.get(DIRECTORY_URL, root / "raw" / "locations.json")
    capture_manifest = [{k: v for k, v in directory.items() if k != "payload"}]
    try:
        if directory.get("error"):
            raise ValueError(directory["error"])
        locations = validate_directory(directory.get("payload"))
    except ValueError as exc:
        json_file(root / "capture-manifest.json", capture_manifest)
        json_file(root / "failure.json", {"captured_at": captured_at, "error": str(exc)})
        print(f"Directory failed: {exc}. Existing latest exports were retained.", file=sys.stderr)
        return 1
    orgs = sorted({row["org"] for row in locations if isinstance(row.get("org"), str) and ORG_PATTERN.fullmatch(row["org"])})
    responses = {}
    for index, org in enumerate(orgs, 1):
        response = client.get(STATS_BASE + org + "/stats/", root / "raw" / "stats" / f"{org}.json")
        responses[org] = response
        capture_manifest.append({k: v for k, v in response.items() if k != "payload"})
        if index % 25 == 0 or response.get("error") or index == len(orgs):
            print(f"[{index}/{len(orgs)}] {org}: {response.get('error', 'retrieved')}", flush=True)
    org_rows = make_orgs(locations, responses, captured_at)
    community_rows = make_communities(locations, org_rows, captured_at)
    assessment = quality(locations, org_rows, previous, args.min_coverage)
    manifest = {"schema_version": 1, "run_id": run_id, "captured_at": captured_at,
                "finished_at": iso(dt.datetime.now(dt.timezone.utc)), "directory_url": DIRECTORY_URL,
                "stats_url_template": STATS_BASE + "{org}/stats/",
                "previous_accepted_run": previous["manifest"]["run_id"] if previous else None,
                "git_commit": os.environ.get("GITHUB_SHA"), **assessment}
    deltas = growth(org_rows, accepted) if assessment["quality_ok"] else []
    # Do not report apparent removals/changes from a run that failed quality checks.
    events = changes(locations, org_rows, previous, accepted) if assessment["quality_ok"] else [
        {"event": "collection_quality_failed", "org": "", "field": "coverage", "previous": None,
         "current": assessment["coverage"], "note": "; ".join(assessment["quality_reasons"])}]
    ranked = [row for metric in METRICS for period in ("previous", "28d", "91d") for row in rankings(deltas, metric, period)]
    state_rows = summaries(org_rows, deltas)
    snapshot = {"schema_version": 1, "manifest": manifest, "locations": locations, "orgs": org_rows, "changes": events}
    json_file(root / "capture-manifest.json", capture_manifest)
    json_file(root / "manifest.json", manifest)
    exports(root, run_id, manifest, org_rows, community_rows, events, deltas, state_rows, ranked)
    # Write the history marker only after all required exports finish successfully.
    json_file(root / "snapshot.json", snapshot)
    checksums = [hashlib.sha256(path.read_bytes()).hexdigest() + "  " + str(path.relative_to(root))
                 for path in sorted(root.rglob("*")) if path.is_file()]
    (root / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    latest = data_dir / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    latest.mkdir(parents=True)
    for path in root.iterdir():
        if path.suffix in (".csv", ".xlsx", ".md"):
            # Stable links are aliases; timestamped originals remain immutable in runs/.
            shutil.copy2(path, latest / path.name.replace("_" + run_id, ""))
    json_file(latest / "manifest.json", manifest)
    all_snapshots = [*history, snapshot]
    history_rows = [{"quality_ok": s["manifest"]["quality_ok"], **row} for s in all_snapshots for row in s["orgs"]]
    all_changes = [{"snapshot_at": s["manifest"]["captured_at"], **event} for s in all_snapshots for event in s["changes"]]
    csv_file(data_dir / "history" / "organizations.csv", history_rows)
    csv_file(data_dir / "history" / "changes.csv", all_changes)
    index_lines = ["# Collection change log", "", "Each link opens that run's report; dated snapshots are retained.", ""]
    for s in reversed(all_snapshots):
        rid = s["manifest"]["run_id"]
        label = "accepted" if s["manifest"]["quality_ok"] else "needs review"
        index_lines.append(f"- [{rid}](runs/{rid}/report_{rid}.md) — {len(s['orgs'])} organizations, "
                           f"{s['manifest']['coverage']:.1%} complete, {label}; {len(s['changes'])} change events")
    (data_dir / "CHANGELOG.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write((root / f"report_{run_id}.md").read_text(encoding="utf-8"))
    print(f"Saved {root}: {len(org_rows)} organizations, {assessment['coverage']:.1%} complete", flush=True)
    return 0 if assessment["quality_ok"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--delay", type=float, default=1.0, help="Minimum seconds between requests (default 1)")
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--min-coverage", type=float, default=.8)
    args = parser.parse_args()
    if args.delay < .25 or args.timeout <= 0 or not 0 <= args.retries <= 5 or not 0 < args.min_coverage <= 1:
        parser.error("delay >= .25, timeout > 0, retries 0..5, and min-coverage in (0,1] required")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
