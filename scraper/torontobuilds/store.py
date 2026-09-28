"""Write events to Supabase through its PostgREST API.

Uses the service role key, which bypasses RLS. Never ship that key to the browser;
the frontend reads with the anon key and a read-only policy.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from .models import Event


class Store:
    def __init__(self, url: str | None = None, key: str | None = None):
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/") + "/rest/v1"
        key = key or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.session = requests.Session()
        self.session.headers.update({
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })

    def source_ids(self) -> dict[str, int]:
        resp = self.session.get(f"{self.url}/sources", params={"select": "id,name"}, timeout=30)
        resp.raise_for_status()
        return {row["name"]: row["id"] for row in resp.json()}

    def existing_labels(self, hashes: list[str]) -> dict[str, dict]:
        """Labels already written for these events, so Claude only sees new ones."""
        found: dict[str, dict] = {}
        for i in range(0, len(hashes), 100):
            chunk = hashes[i:i + 100]
            resp = self.session.get(
                f"{self.url}/events",
                params={
                    "select": "dedup_hash,category,tags,summary",
                    "dedup_hash": f"in.({','.join(chunk)})",
                    "summary": "not.is.null",
                },
                timeout=30,
            )
            resp.raise_for_status()
            found.update({row["dedup_hash"]: row for row in resp.json()})
        return found

    def upsert(self, events: list[Event]) -> int:
        if not events:
            return 0
        ids = self.source_ids()
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "dedup_hash": e.dedup_hash,
                "source_id": ids[e.source],
                "title": e.title,
                "description": e.description,
                "summary": e.summary,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat() if e.end_time else None,
                "venue_name": e.venue_name,
                "address": e.address,
                "neighborhood": e.neighborhood,
                "online": e.online,
                "url": e.url,
                "source_urls": e.source_urls,
                "image_url": e.image_url,
                "category": e.category,
                "tags": e.tags,
                "scraped_at": now,
            }
            for e in events
        ]
        resp = self.session.post(
            f"{self.url}/events",
            params={"on_conflict": "dedup_hash"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=rows,
            timeout=60,
        )
        resp.raise_for_status()
        return len(rows)
