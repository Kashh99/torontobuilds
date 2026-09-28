"""Cross-source dedup.

dedup_hash = sha1(normalized title | local date | rough location). "Rough location"
is only online vs in-person: sources disagree on venue names and addresses far too
often to use them, but an event never switches between online and in-person.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict

from .models import Event, RawEvent
from .normalize import clean_text, neighborhood_for

# Words that sources add or drop freely around the same event name.
NOISE_WORDS = {
    "the", "a", "an", "and", "of", "at", "in", "on", "for", "with", "by", "to",
    "toronto", "yyz", "meetup", "event", "events", "edition", "in-person",
    "inperson", "person", "virtual", "online", "hybrid", "free", "tickets",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}

# When the same event is on several sources, the first one here wins for field values.
SOURCE_PRIORITY = ["meetup", "luma", "eventbrite"]


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    tokens = [t for t in text.split() if t not in NOISE_WORDS and not re.fullmatch(r"(19|20)\d\d", t)]
    # Sorted so "AI Tinkerers Toronto" == "Toronto AI Tinkerers"
    return " ".join(sorted(set(tokens)))


def dedup_hash(raw: RawEvent) -> str:
    key = "|".join([
        normalize_title(raw.title),
        raw.start_time.date().isoformat(),
        "online" if raw.online else "in-person",
    ])
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def _priority(raw: RawEvent) -> int:
    return SOURCE_PRIORITY.index(raw.source) if raw.source in SOURCE_PRIORITY else len(SOURCE_PRIORITY)


def merge(raws: list[RawEvent]) -> list[Event]:
    groups: dict[str, list[RawEvent]] = defaultdict(list)
    for raw in raws:
        groups[dedup_hash(raw)].append(raw)

    events = []
    for h, group in groups.items():
        group.sort(key=_priority)
        best = group[0]

        def first(attr: str):
            return next((getattr(r, attr) for r in group if getattr(r, attr)), None)

        # Prefer a record that has a real time over a date-only one (Eventbrite listings are date-only).
        timed = next((r for r in group if (r.start_time.hour, r.start_time.minute) != (0, 0)), best)
        descriptions = [clean_text(r.description) for r in group]

        events.append(Event(
            dedup_hash=h,
            source=best.source,
            title=best.title.strip(),
            start_time=timed.start_time,
            end_time=timed.end_time or first("end_time"),
            url=best.url,
            description=max(descriptions, key=len),
            venue_name=first("venue_name"),
            address=first("address"),
            neighborhood=next((n for r in group if (n := neighborhood_for(r))), None),
            online=best.online,
            image_url=first("image_url"),
            source_urls=list(dict.fromkeys(r.url for r in group)),
            trusted=any(r.trusted for r in group),
        ))
    return events
