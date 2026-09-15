"""Small, rate-limited public JSON client. No credentials, cookies, or guessed orgs."""
from __future__ import annotations

import datetime as dt
import email.utils
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request

from .model import iso


class PublicClient:
    def __init__(self, delay=1.0, timeout=25, retries=2, user_agent="axon-community-tracker/1.0 (public aggregate statistics)"):
        self.delay, self.timeout, self.retries = delay, timeout, retries
        self.user_agent = user_agent
        self.last_request = 0.0

    def get(self, url, raw_path):
        record = {"source_url": url}
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            self.last_request = time.monotonic()
            record.update(retrieved_at=iso(dt.datetime.now(dt.timezone.utc)), attempts=attempt + 1)
            try:
                request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read(10_000_001)
                    if len(body) > 10_000_000:
                        raise ValueError("Response exceeds the 10 MB limit")
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_path.write_bytes(body)
                    record.update(http_status=response.status, final_url=response.url,
                                  bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                                  headers={k: v for k, v in response.headers.items() if k.lower() in
                                           {"content-type", "content-encoding", "date", "etag", "last-modified", "cache-control", "age"}})
                    decoded = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
                    record["payload"] = json.loads(decoded)
                    return record
            except urllib.error.HTTPError as exc:
                record.update(http_status=exc.code, error=f"HTTP {exc.code}")
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == self.retries:
                    return record
                # Do not retry sooner than Retry-After; stop this org on long server delays.
                delay = 2 ** (attempt + 1)
                retry_after = exc.headers.get("Retry-After", "")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        try:
                            until = email.utils.parsedate_to_datetime(retry_after)
                            delay = max(delay, (until - dt.datetime.now(dt.timezone.utc)).total_seconds())
                        except (ValueError, TypeError):
                            pass
                if delay > 120:
                    record["error"] += "; Retry-After exceeds 120 seconds; deferred until next run"
                    return record
                time.sleep(delay)
            except (OSError, ValueError, EOFError) as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                if attempt == self.retries or isinstance(exc, (ValueError, EOFError)):
                    return record
                time.sleep(2 ** (attempt + 1))
            # A transient failure followed by success must not leave a stale error.
            record.pop("error", None)
        return record
