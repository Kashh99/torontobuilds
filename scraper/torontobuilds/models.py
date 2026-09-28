from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawEvent:
    """One event as a single source describes it, before dedup and enrichment."""

    source: str
    title: str
    start_time: datetime
    url: str
    description: str = ""
    end_time: datetime | None = None
    venue_name: str | None = None
    address: str | None = None
    postal_code: str | None = None
    lat: float | None = None
    lng: float | None = None
    online: bool = False
    image_url: str | None = None


@dataclass
class Event:
    """A deduplicated event, ready to write to the events table."""

    dedup_hash: str
    source: str
    title: str
    start_time: datetime
    url: str
    description: str = ""
    end_time: datetime | None = None
    venue_name: str | None = None
    address: str | None = None
    neighborhood: str | None = None
    online: bool = False
    image_url: str | None = None
    source_urls: list[str] = field(default_factory=list)
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    summary: str | None = None
    is_tech: bool = True
