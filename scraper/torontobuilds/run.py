"""Nightly scrape: fetch every source, dedup, label, upsert.

    python -m torontobuilds.run             # full run, writes to Supabase
    python -m torontobuilds.run --dry-run   # print what would be written
    python -m torontobuilds.run --dry-run --json ../web/sample-events.json   # offline data for the frontend
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from .dedup import merge
from .enrich import enrich
from .fetchers import PARSERS, TORONTO, fetch, fill_location, needs_location
from .models import RawEvent

log = logging.getLogger("torontobuilds")

SOURCES_FILE = Path(__file__).resolve().parent.parent / "sources.json"
HORIZON_DAYS = 60
REQUEST_GAP_SECONDS = 1  # be polite: ~40 requests a night, one at a time


def scrape(config: list[dict]) -> tuple[list[RawEvent], list[str]]:
    raws: list[RawEvent] = []
    failures: list[str] = []
    for entry in config:
        parse = PARSERS[entry["parser"]]
        for url in entry["urls"]:
            time.sleep(REQUEST_GAP_SECONDS)
            try:
                found = parse(fetch(url), entry["source"])
                for raw in found:
                    raw.trusted = entry.get("trusted", False)
            except Exception as err:  # one broken source must not sink the run
                log.error("%s failed: %s", url, err)
                failures.append(url)
                continue
            log.info("%-10s %3d events  %s", entry["source"], len(found), url)
            raws.extend(found)
    return raws, failures


def backfill_locations(raws: list[RawEvent]) -> None:
    # The same Meetup event can come from a group feed and the search page; fetch its page once.
    pages: dict[str, str | None] = {}
    for raw in raws:
        if not needs_location(raw):
            continue
        if raw.url not in pages:
            time.sleep(REQUEST_GAP_SECONDS)
            try:
                pages[raw.url] = fetch(raw.url)
            except Exception as err:
                log.warning("location lookup failed for %s: %s", raw.url, err)
                pages[raw.url] = None
        if html := pages[raw.url]:
            fill_location(raw, html)
    log.info("looked up %d Meetup event pages for locations", len(pages))


def in_window(raw: RawEvent, now: datetime) -> bool:
    return now - timedelta(hours=6) <= raw.start_time <= now + timedelta(days=HORIZON_DAYS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", type=Path, help="with --dry-run, also write events to this file")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config = json.loads(SOURCES_FILE.read_text())
    raws, failures = scrape(config)
    now = datetime.now(TORONTO)
    raws = [r for r in raws if in_window(r, now)]
    backfill_locations(raws)  # before dedup: online vs in-person is part of the dedup key
    events = merge(raws)
    log.info("%d raw events -> %d after dedup", len(raws), len(events))

    store = None
    if not args.dry_run:
        from .store import Store
        store = Store()
        known = store.existing_labels([e.dedup_hash for e in events])
        for e in events:
            if label := known.get(e.dedup_hash):
                e.category, e.tags, e.summary = label["category"], label["tags"], label["summary"]
        new = [e for e in events if e.summary is None]
        log.info("%d events already labelled, %d new", len(events) - len(new), len(new))
        kept = [e for e in events if e.summary is not None] + enrich(new)
    else:
        kept = enrich(events)

    log.info("%d tech events kept", len(kept))
    if store:
        store.upsert(kept)
        log.info("upserted %d events", len(kept))
    else:
        if args.json:
            args.json.write_text(json.dumps([asdict(e) for e in kept], default=lambda o: o.isoformat(), indent=1))
            log.info("wrote %s", args.json)
        for e in sorted(kept, key=lambda e: e.start_time):
            print(f"{e.start_time:%a %b %d %H:%M}  [{e.category}] {e.title}  ({e.neighborhood or '?'}; {len(e.source_urls)} source(s))")
            if e.summary:
                print(f"    {e.summary}")

    # Fail the job only if every source failed; partial data beats none.
    total_urls = sum(len(entry["urls"]) for entry in config)
    return 1 if failures and len(failures) == total_urls else 0


if __name__ == "__main__":
    raise SystemExit(main())
