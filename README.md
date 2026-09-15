# Axon Community Connect camera tracker

Weekly, reproducible snapshots of the public Community Connect directory and its organization camera statistics. Built for reporting on changes over time. No account credentials or API secrets are required.

## Open the data

- **[Latest report](data/latest/report.md)** — coverage, largest inventories, growth leaders, declines, and change events.
- **[Excel workbook](data/latest/camera_statistics.xlsx)** — overview, organizations, every directory entry, growth, rankings, state summaries, change events, and an inventory chart. Use GitHub's **Download raw file** button.
- **[Organization CSV](data/latest/organizations.csv)** — one row per distinct `org`; use this for totals.
- **[Community CSV](data/latest/communities.csv)** — every original directory listing and field, plus its statistics. Do not sum this file without deduplicating `org`.
- **[Growth CSV](data/latest/growth.csv)** and **[rankings CSV](data/latest/rankings.csv)** — all six metrics, previous observation and 28/91-day comparisons.
- **[State summary](data/latest/state_summary.csv)** — sums and matched-organization changes, with coverage counts.
- **[Full organization history](data/history/organizations.csv)** and **[event history](data/history/changes.csv)**.
- **[Dated reports and change log](data/CHANGELOG.md)**; **[all timestamped captures](data/runs/)**.

The first observation establishes a baseline. The tracker does not invent historical growth. Leaderboards populate after valid observations at least six days apart; 28- and 91-day comparisons need that much history.

## Schedule

The **Weekly camera statistics** GitHub Actions workflow runs **Mondays at 13:23 UTC** (07:23 MDT / 06:23 MST). It can also be started from **Actions → Weekly camera statistics → Run workflow**. GitHub may delay scheduled jobs; the actual capture times are recorded.

Each run:

1. Downloads the current directory once.
2. Fetches the explicitly listed organization identifiers, deduplicated, at no more than one request per second by default.
3. Saves the original responses, retrieval metadata, and SHA-256 hashes.
4. Compares valid observations with earlier accepted runs.
5. Exports timestamped CSV, JSON, XLSX, and Markdown files.
6. Commits data and updates stable `data/latest/` links and the cumulative history.
7. Uploads a downloadable Actions artifact (90-day retention). Committed snapshots remain in Git history independently of artifact expiry.

Failures make the workflow fail after preserving available diagnostics. Use GitHub's workflow notification settings for failure alerts. Very low coverage and abrupt directory loss are not silently promoted to comparison baselines.

## Sources and scope

- Directory: https://axoncommunityconnect.com/locations.json
- Public directory page: https://axoncommunityconnect.com/communities/
- Statistics: `https://api.fususone.com/api/public/organizations/{org}/stats/`
- Vendor terminology: https://axoncommunityconnect.com/faqs/
- Discovery reference: https://github.com/saviorSEC/axon-communities

This implementation retrieves only the public directory and the public aggregate stats endpoint for identifiers in that directory. It does not enumerate unlisted agencies, log in, submit forms, retrieve individual camera records or footage, or access storage buckets. Directory membership is not asserted to cover every Axon/Fusus customer. Publicly reported counts are not independently verified operational inventories.

## Interpreting the metrics

The tracker retains the upstream names rather than assigning unsupported meanings:

| Field | Treatment |
|---|---|
| `totalRegisteredCameras` | Registered-camera count returned by the API |
| `totalIntegratedCameras` | Integrated-camera count; default report growth metric |
| `totalOwnedCameras` | API's owned count; legal ownership definition unverified |
| `totalSharedCameras` | API's shared count; relationship to other totals unverified |
| `totalMaxCameras` | API field preserved without interpreting it as installed capacity |
| `subscribedCameras` | API field preserved; subscription/licensing semantics unverified |

**Never add the six categories together.** They can overlap. Even after deduplicating `org`, totals across agencies may double-count shared physical cameras. A change in reported counts may reflect registration, integration, sharing, configuration, cleanup, or accounting changes; it does not establish physical installations or active livestream availability.

The vendor distinguishes registration from live integration. A registered camera is not necessarily available for live viewing. Exact field definitions should be confirmed with Axon and the relevant agency before publication.

## Analysis methodology

### Organization identity and duplicates

`org` is the statistics join key. Every directory entry stays in `communities`, but an org is requested once and has one row in `organizations`. Programs sharing an org get the same counts. Metadata changes, org reassignments, and directory additions/removals appear in the event log. The identity history is not automatically merged across changed org identifiers.

### Changes and rankings

- Absolute change = current count minus previous count.
- Percentage change = absolute change / previous count. It stays blank for a zero baseline.
- Weekly rate = absolute change × 7 / elapsed days, using each org's actual retrieval timestamp. This is an observed rate, not a prediction.
- `previous` uses that org/metric's latest valid observation in an accepted earlier run. A missed week can therefore produce a longer interval; both timestamps are exported.
- `28d` / `91d` use the latest valid observation on or before the respective target date. Actual intervals may exceed the nominal window and are always shown.
- Rankings require at least six elapsed days. Percentage rankings additionally require at least 25 cameras in the baseline to reduce tiny-denominator effects.
- Rankings distinguish absolute increases, weekly rates, percentage increases, and decreases, for every metric and horizon.
- A newly listed organization has no observed growth until it has a usable earlier observation. Disappearance from the directory is never a zero-camera observation.
- State labels come from directory program locations, not individual camera coordinates. Unknown or conflicting state labels are grouped separately. State comparable sums include only matched org/metric pairs; comparison dates may differ after missing observations.

### Data quality

Genuine zeroes are retained. HTTP failures, absent fields, booleans, negative counts, and non-integer counts stay missing. New fields are retained in raw JSON and flattened exports. Partial responses retain their valid metric values.

A run is excluded from future baselines if:

- fewer than 80% of distinct listed organizations return all six valid metrics;
- fewer than 80% of directory entries have valid org identifiers; or
- the directory is more than 25% smaller than the previous accepted snapshot.

These are review thresholds, not claims about the true system. A legitimate large directory change may require a code/configuration review. Unqualified runs remain visible in the latest exports and history, clearly marked `quality_ok=false`, but their growth rankings and apparent removal/change events are withheld. If the directory itself cannot be read, existing latest exports remain in place and a dated failure file is saved. Check the latest manifest timestamp rather than assuming fresh data.

Error responses are retried only for transient conditions (408/429/5xx, connection errors), at most twice by default. The client respects bounded `Retry-After`; long delays defer that org until the next run. Access denials are not retried. Unknown organization strings are never used as paths. CSV strings are protected against spreadsheet formula injection; raw JSON preserves original values.

## Files

```text
data/
  runs/2026-09-15T231234Z/
    raw/locations.json
    raw/stats/<org>.json
    capture-manifest.json
    manifest.json
    snapshot.json
    organizations_2026-09-15T231234Z.csv
    communities_2026-09-15T231234Z.csv
    growth_2026-09-15T231234Z.csv
    rankings_2026-09-15T231234Z.csv
    state_summary_2026-09-15T231234Z.csv
    changes_2026-09-15T231234Z.csv
    ...matching JSON files...
    camera_statistics_2026-09-15T231234Z.xlsx
    report_2026-09-15T231234Z.md
    SHA256SUMS.txt
  latest/                    # Stable aliases to the most recent completed export
  history/organizations.csv  # All observations, including quality/status columns
  history/changes.csv
  CHANGELOG.md
```

CSV files use UTF-8 with a byte-order mark for Excel compatibility. Count fields are numbers; blank means missing. JSON retains nulls, nested raw responses, and unexpected fields. XLSX files are immutable computed snapshots, with typed numbers, filtered tables, frozen identifiers, and source columns. Calculations are implemented and tested in Python so CSV, JSON, reports, and Excel remain consistent. They are not editable forecasting models.

No claim is made that filesystem modification times are evidence timestamps. Use `captured_at`, `observed_at`, HTTP metadata and hashes.

## Run locally

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m axon_tracker
```

On Windows, activate with `.venv\Scripts\activate`.

Options:

```bash
python -m axon_tracker --data-dir data --delay 1 --timeout 25 --retries 2 --min-coverage 0.8
```

Do not run multiple local collectors against the same data directory simultaneously. Actions runs are serialized. Existing snapshots should not be edited after capture; make corrections in code and preserve the original record.

## GitHub setup and maintenance

The included workflow needs **Contents: write** for its automatic commits. No personal access token or custom secret is used: it relies on the repository-scoped `GITHUB_TOKEN`. Actions are pinned to commit hashes and Python dependencies to versions. Changes to code run tests; data-only bot commits do not start another collection.

If you fork this repository, enable Actions and manually start the collection workflow once. Scheduled workflows execute on the default branch. GitHub may disable schedules in inactive public repositories after 60 days without activity; periodic successful data commits normally maintain repository activity. Check the Actions tab if snapshots stop appearing. Repository rules that require pull requests for all writes can block bot commits; adjust those rules or use a dedicated data branch.

Workflow scheduling documentation: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

Statistics terminology and API structure can change. The preserved raw responses and schema/coverage checks support review when that happens. This repository is independent of Axon and is not an official Axon dataset.
