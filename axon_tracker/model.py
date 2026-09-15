"""Pure transformations. A missing observation is never interpreted as zero."""
from __future__ import annotations

import collections
import datetime as dt
import json
import re

DIRECTORY_URL = "https://axoncommunityconnect.com/locations.json"
STATS_BASE = "https://api.fususone.com/api/public/organizations/"
METRICS = (
    "totalRegisteredCameras", "totalIntegratedCameras", "totalOwnedCameras",
    "totalSharedCameras", "totalMaxCameras", "subscribedCameras",
)
PRIMARY = "totalIntegratedCameras"
ORG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def iso(value):
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def date(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def valid_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def flatten(value, prefix=""):
    """Preserve all directory fields, including unexpected future fields."""
    out = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict) and item:
            out.update(flatten(item, name))
        elif isinstance(item, (dict, list)):
            out[name] = json.dumps(item, ensure_ascii=False, sort_keys=True)
        else:
            out[name] = item
    return out


def validate_directory(value):
    if not isinstance(value, list) or not value:
        raise ValueError("Directory must be a nonempty JSON array; refusing an empty baseline.")
    if any(not isinstance(row, dict) for row in value):
        raise ValueError("Every directory entry must be an object.")
    if not any(isinstance(row.get("org"), str) and ORG_PATTERN.fullmatch(row["org"]) for row in value):
        raise ValueError("Directory contains no usable organization identifiers.")
    return value


def make_orgs(locations, responses, captured_at):
    grouped = collections.defaultdict(list)
    for item in locations:
        org = item.get("org")
        if isinstance(org, str) and ORG_PATTERN.fullmatch(org):
            grouped[org].append(item)
    rows = []
    for org, programs in sorted(grouped.items()):
        response = responses.get(org, {})
        payload = response.get("payload")
        stats = payload if isinstance(payload, dict) else {}
        missing = [key for key in METRICS if not valid_count(stats.get(key))]
        states = sorted({str(p.get("location", {}).get("state") or "Unknown") for p in programs
                         if isinstance(p.get("location", {}), dict)})
        row = {
            "snapshot_at": captured_at, "observed_at": response.get("retrieved_at", captured_at),
            "org": org, "program_count": len(programs),
            "programs": " / ".join(sorted({str(p.get("title", "")) for p in programs})),
            "city": " / ".join(sorted({str(p.get("location", {}).get("city", "")) for p in programs
                                          if isinstance(p.get("location", {}), dict)})),
            "state": states[0] if len(states) == 1 else "Multiple / unknown",
            "status": "error" if response.get("error") or not isinstance(payload, dict)
                       else "partial" if missing else "ok",
            "http_status": response.get("http_status"), "error": response.get("error", ""),
            "missing_metrics": ";".join(missing),
            "source_url": STATS_BASE + org + "/stats/",
        }
        for key in METRICS:
            row[key] = stats.get(key) if valid_count(stats.get(key)) else None
        row.update({"stats." + key: val for key, val in flatten(stats).items() if key not in METRICS})
        rows.append(row)
    return rows


def make_communities(locations, orgs, captured_at):
    by_org = {r["org"]: r for r in orgs}
    rows = []
    for index, item in enumerate(locations):
        org = item.get("org")
        stats = by_org.get(org) if isinstance(org, str) else None
        row = {"snapshot_at": captured_at, "directory_row": index + 1, **flatten(item)}
        if stats:
            row.update({"collection." + k: stats[k] for k in
                        ("status", "observed_at", "http_status", "error", "source_url", "missing_metrics", "program_count")})
            row.update({"stats." + key: stats[key] for key in METRICS})
            row.update({key: val for key, val in stats.items() if key.startswith("stats.")})
        else:
            row["collection.status"] = "missing_org" if not org else "invalid_org"
            row["collection.error"] = "No valid public organization identifier. No request made."
            row.update({"stats." + key: None for key in METRICS})
        rows.append(row)
    return rows


def quality(locations, orgs, previous, min_coverage=.8):
    complete = sum(r["status"] == "ok" for r in orgs)
    coverage = complete / len(orgs) if orgs else 0
    valid_entries = sum(isinstance(x.get("org"), str) and bool(ORG_PATTERN.fullmatch(x["org"])) for x in locations)
    ratio = len(locations) / len(previous["locations"]) if previous else 1
    reasons = []
    if coverage < min_coverage:
        reasons.append(f"Complete statistics coverage {coverage:.1%} is below {min_coverage:.1%}.")
    if valid_entries / len(locations) < min_coverage:
        reasons.append("Too many directory entries lack valid organization identifiers.")
    if ratio < .75:
        reasons.append("Directory shrank by more than 25%; requires review before accepting a new baseline.")
    return {"quality_ok": not reasons, "quality_reasons": reasons, "coverage": coverage,
            "complete_orgs": complete, "distinct_orgs": len(orgs), "directory_entries": len(locations),
            "invalid_directory_entries": len(locations) - valid_entries, "directory_size_ratio": ratio}


def growth(current, history):
    """Per-metric last valid observations; 28/91-day baselines must precede their target."""
    observations = collections.defaultdict(list)
    for snapshot in history:
        if not snapshot["manifest"]["quality_ok"]:
            continue
        for row in snapshot["orgs"]:
            for metric in METRICS:
                if valid_count(row.get(metric)):
                    observations[row["org"], metric].append(row)
    result = []
    for row in current:
        for metric in METRICS:
            now = row.get(metric)
            if not valid_count(now):
                continue
            when = date(row["observed_at"])
            earlier = sorted((old for old in observations[row["org"], metric]
                              if date(old["observed_at"]) < when), key=lambda old: old["observed_at"])
            for period, days in (("previous", None), ("28d", 28), ("91d", 91)):
                candidates = earlier if days is None else [old for old in earlier if
                              date(old["observed_at"]) <= when - dt.timedelta(days=days)]
                if not candidates:
                    continue
                old = candidates[-1]
                elapsed = (when - date(old["observed_at"])).total_seconds() / 86400
                if elapsed <= 0:
                    continue
                before = old[metric]
                delta = now - before
                result.append({"org": row["org"], "programs": row["programs"], "city": row["city"],
                    "state": row["state"], "metric": metric, "period": period,
                    "previous_at": old["observed_at"], "current_at": row["observed_at"],
                    "elapsed_days": round(elapsed, 6), "previous_count": before, "current_count": now,
                    "change": delta, "change_pct": delta / before if before else None,
                    "change_per_week": delta * 7 / elapsed, "from_zero": before == 0,
                    "ranking_eligible": elapsed >= 6, "source_url": row["source_url"]})
    return result


def directory_index(locations):
    grouped = collections.defaultdict(list)
    for row in locations:
        grouped[str(row.get("id") or row.get("url") or row.get("org") or "unknown")].append(row)
    # Retain duplicate IDs without silently choosing a winner.
    return {key: sorted(value, key=lambda x: json.dumps(x, sort_keys=True)) for key, value in grouped.items()}


def changes(locations, orgs, previous, history):
    events = []
    def add(kind, org="", field="", old=None, new=None, note=""):
        events.append({"event": kind, "org": org, "field": field, "previous": old,
                       "current": new, "note": note})
    if not previous:
        add("baseline", new=len(orgs), note="Initial observation; growth cannot yet be measured.")
    else:
        old_index, new_index = directory_index(previous["locations"]), directory_index(locations)
        all_past = {k for snapshot in history for k in directory_index(snapshot["locations"])}
        for key in sorted(old_index.keys() | new_index.keys()):
            old, new = old_index.get(key), new_index.get(key)
            org = str((new or old)[0].get("org", ""))
            if old is None:
                add("listing_reappeared" if key in all_past else "listing_added", org, key, new=new,
                    note="Directory membership change; not proof of newly installed cameras.")
            elif new is None:
                add("listing_removed", org, key, old=old,
                    note="Missing from directory; camera counts were not changed to zero.")
            elif old != new:
                add("listing_changed", org, key, old, new)
        old_orgs = {r["org"]: r for r in previous["orgs"]}
        for row in orgs:
            old = old_orgs.get(row["org"])
            if not old:
                continue
            if row["status"] != old["status"]:
                add("collection_status_changed", row["org"], "status", old["status"], row["status"])
            for metric in METRICS:
                a, b = old.get(metric), row.get(metric)
                if a == b:
                    continue
                event = "metric_changed" if valid_count(a) and valid_count(b) else "metric_availability_changed"
                add(event, row["org"], metric, a, b)
    for row in orgs:
        if row["status"] != "ok":
            add("collection_issue", row["org"], "status", new=row["status"],
                note=row["error"] or "Missing or invalid metric: " + row["missing_metrics"])
    return events


def summaries(orgs, deltas):
    groups = collections.defaultdict(list)
    for row in orgs:
        groups[row["state"]].append(row)
    result = []
    for state, rows in sorted(groups.items()):
        for metric in METRICS:
            valid = [r for r in rows if valid_count(r.get(metric))]
            pairs = [g for g in deltas if g["state"] == state and g["metric"] == metric and
                     g["period"] == "previous" and g["ranking_eligible"]]
            result.append({"state": state, "metric": metric, "orgs_listed": len(rows),
                "orgs_with_metric": len(valid), "reported_sum": sum(r[metric] for r in valid) if valid else None,
                "compared_orgs": len(pairs), "comparable_previous_sum": sum(g["previous_count"] for g in pairs) if pairs else None,
                "comparable_current_sum": sum(g["current_count"] for g in pairs) if pairs else None,
                "comparable_change": sum(g["change"] for g in pairs) if pairs else None})
    return result


def rankings(deltas, metric=PRIMARY, period="previous"):
    eligible = [g for g in deltas if g["metric"] == metric and g["period"] == period and g["ranking_eligible"]]
    modes = {
        "fastest_absolute": (lambda g: g["change"], [g for g in eligible if g["change"] > 0], True),
        "fastest_weekly_rate": (lambda g: g["change_per_week"], [g for g in eligible if g["change"] > 0], True),
        "fastest_percentage": (lambda g: g["change_pct"], [g for g in eligible if g["change"] > 0 and g["previous_count"] >= 25], True),
        "largest_declines": (lambda g: g["change"], [g for g in eligible if g["change"] < 0], False),
    }
    out = []
    for name, (key, values, reverse) in modes.items():
        for rank, row in enumerate(sorted(values, key=key, reverse=reverse), 1):
            out.append({"ranking": name, "rank": rank, **row})
    return out
