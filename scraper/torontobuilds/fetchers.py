"""Turn source pages into RawEvents.

Two parsers cover every source we use:
- JSON-LD: Eventbrite, Luma and Meetup listing pages all embed schema.org Event objects.
- ICS: Meetup groups publish an iCalendar feed at /<group>/events/ical/.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from icalendar import Calendar

from .models import RawEvent

TORONTO = ZoneInfo("America/Toronto")
USER_AGENT = "Mozilla/5.0 (compatible; TorontoBuildsBot/1.0)"
POSTAL_RE = re.compile(r"\b([A-Z]\d[A-Z])\s?(\d[A-Z]\d)\b", re.I)


def fetch(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.text


# ---------- JSON-LD ----------

def _walk_events(node: Any) -> Iterator[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _walk_events(item)
    elif isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(isinstance(t, str) and t.endswith("Event") for t in types):
            yield node
            return
        for value in node.values():
            yield from _walk_events(value)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = dateparser.isoparse(value)
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, time())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TORONTO)
    return dt.astimezone(TORONTO)


def _find_postal(*texts: str | None) -> str | None:
    for text in texts:
        if text and (m := POSTAL_RE.search(text)):
            return f"{m.group(1)} {m.group(2)}".upper()
    return None


def _jsonld_to_raw(obj: dict, source: str) -> RawEvent | None:
    title = (obj.get("name") or "").strip()
    start = _parse_dt(obj.get("startDate"))
    url = obj.get("url") or obj.get("@id")
    if not (title and start and url):
        return None

    loc = obj.get("location") or {}
    if isinstance(loc, list):
        loc = next((l for l in loc if isinstance(l, dict) and l.get("@type") == "Place"), loc[0] if loc else {})
    online = "Online" in str(obj.get("eventAttendanceMode", "")) or loc.get("@type") == "VirtualLocation"

    addr = loc.get("address") or {}
    if isinstance(addr, str):
        address = addr
        postal = None
    else:
        parts = [addr.get("streetAddress"), addr.get("addressLocality")]
        address = ", ".join(p for p in parts if p) or None
        postal = addr.get("postalCode")
    geo = loc.get("geo") or {}

    image = obj.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")

    return RawEvent(
        source=source,
        title=title,
        start_time=start,
        end_time=_parse_dt(obj.get("endDate")),
        url=url,
        description=(obj.get("description") or "").strip(),
        venue_name=None if online else loc.get("name"),
        address=None if online else address,
        postal_code=_find_postal(postal, address),
        lat=_to_float(geo.get("latitude")),
        lng=_to_float(geo.get("longitude")),
        online=online,
        image_url=image,
    )


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_jsonld(html: str, source: str) -> list[RawEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[RawEvent] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        for obj in _walk_events(data):
            if raw := _jsonld_to_raw(obj, source):
                events.append(raw)
    return events


# ---------- ICS ----------

def _ics_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    dt = value.dt
    if not isinstance(dt, datetime):
        dt = datetime.combine(dt, time())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TORONTO)
    return dt.astimezone(TORONTO)


def parse_ics(text: str, source: str) -> list[RawEvent]:
    cal = Calendar.from_ical(text)
    events: list[RawEvent] = []
    for comp in cal.walk("VEVENT"):
        title = str(comp.get("SUMMARY", "")).strip()
        start = _ics_dt(comp.get("DTSTART"))
        url = str(comp.get("URL", "")).strip()
        if not (title and start and url):
            continue
        location = str(comp.get("LOCATION", "")).strip()
        # No LOCATION means "not published yet", not "online"
        online = bool(re.search(r"online|zoom|https?://", location, re.I))
        # Meetup writes LOCATION as "Venue (street, city, ...)"
        venue, address = location, None
        if m := re.match(r"^(.*?)\s*\((.*)\)\s*$", location):
            venue, address = m.group(1), m.group(2)
        geo = comp.get("GEO")
        events.append(
            RawEvent(
                source=source,
                title=title,
                start_time=start,
                end_time=_ics_dt(comp.get("DTEND")),
                url=url,
                description=str(comp.get("DESCRIPTION", "")).strip(),
                venue_name=None if online else venue or None,
                address=None if online else address,
                postal_code=_find_postal(location),
                lat=geo.latitude if geo else None,
                lng=geo.longitude if geo else None,
                online=online,
            )
        )
    return events


PARSERS = {"jsonld": parse_jsonld, "ics": parse_ics}
