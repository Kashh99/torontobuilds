"""Location and relevance rules that don't need an LLM."""

from __future__ import annotations

import html
import math
import re

from .models import RawEvent

# Forward sortation areas (first 3 postal code chars) for the parts of the city
# where tech events actually happen. Anything else falls back to a borough.
FSA_NEIGHBORHOODS = {
    "M5V": "King West",
    "M5H": "Financial District",
    "M5X": "Financial District",
    "M5K": "Financial District",
    "M5L": "Financial District",
    "M5J": "Harbourfront",
    "M5E": "St. Lawrence",
    "M5C": "St. Lawrence",
    "M5A": "Corktown / Distillery",
    "M5B": "Downtown Yonge",
    "M5G": "Discovery District",
    "M5T": "Kensington / Chinatown",
    "M5S": "UofT / Annex",
    "M5R": "Annex / Yorkville",
    "M4Y": "Church-Wellesley",
    "M4W": "Rosedale",
    "M4X": "Cabbagetown",
    "M6J": "Trinity Bellwoods",
    "M6K": "Liberty Village / Parkdale",
    "M6G": "Christie Pits",
    "M6H": "Dovercourt",
    "M6R": "Roncesvalles",
    "M6P": "High Park / Junction",
    "M4M": "Leslieville",
    "M4K": "Riverdale",
    "M4L": "Leslieville",
    "M4E": "The Beaches",
    "M4S": "Midtown",
    "M4P": "Midtown",
    "M4R": "Midtown",
    "M4T": "Midtown",
    "M4V": "Midtown",
    "M2N": "North York Centre",
    "M3C": "Don Mills",
}

# Centroids for events that only give lat/lng (Luma often has a venue name but no postal code).
CENTROIDS = {
    "King West": (43.6447, -79.3950),
    "Financial District": (43.6484, -79.3817),
    "Harbourfront": (43.6400, -79.3810),
    "St. Lawrence": (43.6487, -79.3715),
    "Corktown / Distillery": (43.6530, -79.3600),
    "Downtown Yonge": (43.6577, -79.3788),
    "Discovery District": (43.6590, -79.3900),
    "Kensington / Chinatown": (43.6540, -79.4000),
    "UofT / Annex": (43.6629, -79.3957),
    "Annex / Yorkville": (43.6710, -79.3930),
    "Church-Wellesley": (43.6655, -79.3810),
    "Trinity Bellwoods": (43.6480, -79.4140),
    "Liberty Village / Parkdale": (43.6380, -79.4210),
    "Leslieville": (43.6630, -79.3330),
    "Midtown": (43.7060, -79.3980),
    "North York Centre": (43.7680, -79.4130),
}
NEAREST_MAX_KM = 1.5

BOROUGH_BY_PREFIX = {"M1": "Scarborough", "M2": "North York", "M3": "North York", "M8": "Etobicoke", "M9": "Etobicoke"}



def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def neighborhood_for(raw: RawEvent) -> str | None:
    if raw.online:
        return "Online"
    if raw.postal_code:
        fsa = raw.postal_code[:3].upper()
        if fsa in FSA_NEIGHBORHOODS:
            return FSA_NEIGHBORHOODS[fsa]
        if not fsa.startswith("M"):
            return "GTA (outside Toronto)"
        if fsa[:2] in BOROUGH_BY_PREFIX:
            return BOROUGH_BY_PREFIX[fsa[:2]]
    if raw.lat is not None and raw.lng is not None:
        name, dist = min(
            ((n, _haversine_km((raw.lat, raw.lng), c)) for n, c in CENTROIDS.items()),
            key=lambda x: x[1],
        )
        if dist <= NEAREST_MAX_KM:
            return name
    return None
