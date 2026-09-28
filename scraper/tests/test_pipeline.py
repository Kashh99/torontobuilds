from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from torontobuilds import enrich as enrich_mod
from torontobuilds.dedup import dedup_hash, merge, normalize_title
from torontobuilds.fetchers import TORONTO, parse_ics, parse_jsonld
from torontobuilds.models import RawEvent
from torontobuilds.normalize import neighborhood_for

FIXTURES = Path(__file__).parent / "fixtures"


def raw(**kw) -> RawEvent:
    base = dict(source="meetup", title="Toronto AI Tinkerers", start_time=datetime(2026, 10, 5, 18, 30, tzinfo=TORONTO), url="https://x/1")
    return RawEvent(**{**base, **kw})


# ---------- parsers (fixtures are trimmed copies of real pages) ----------

def test_eventbrite_listing_parses_events_with_postal_codes():
    events = parse_jsonld((FIXTURES / "eventbrite_listing.html").read_text(), "eventbrite")
    assert len(events) == 8
    impact = next(e for e in events if e.title == "Impact AI Toronto")
    assert impact.postal_code == "M5A 1B6"
    assert impact.start_time.tzinfo is not None
    assert not impact.online


def test_meetup_find_page_marks_virtual_events_online():
    events = parse_jsonld((FIXTURES / "meetup_find.html").read_text(), "meetup")
    assert len(events) == 12
    online = next(e for e in events if e.title.startswith("Automatic Writing"))
    assert online.online and online.venue_name is None
    techtalk = next(e for e in events if e.title.startswith("TechTalk"))
    assert techtalk.postal_code == "M5V 1Z4"
    # 22:00Z is 18:00 in Toronto (EDT)
    assert (techtalk.start_time.hour, techtalk.start_time.minute) == (18, 0)


def test_luma_listing_parses():
    events = parse_jsonld((FIXTURES / "luma_listing.html").read_text(), "luma")
    assert len(events) == 20
    assert all(e.url.startswith("https://luma.com/") for e in events)


def test_meetup_ics_without_location_is_not_online():
    events = parse_ics((FIXTURES / "torontojs.ics").read_text(), "meetup")
    assert len(events) == 1
    e = events[0]
    assert e.url == "https://www.meetup.com/torontojs/events/316396828/"
    assert e.start_time == datetime(2026, 9, 29, 18, 0, tzinfo=TORONTO)
    assert not e.online


# ---------- dedup ----------

def test_title_normalization_ignores_order_city_and_dates():
    assert normalize_title("AI Tinkerers Toronto - October 2026") == normalize_title("Toronto AI Tinkerers (In-Person)")


def test_same_event_on_two_sources_merges_and_keeps_both_urls():
    a = raw(source="eventbrite", url="https://eb/1", start_time=datetime(2026, 10, 5, 0, 0, tzinfo=TORONTO), postal_code="M5V 1Z4")
    b = raw(source="meetup", url="https://meetup/1", title="AI Tinkerers Toronto")
    events = merge([a, b])
    assert len(events) == 1
    e = events[0]
    assert e.source == "meetup"  # higher priority source wins
    assert e.start_time.hour == 18  # timed record beats Eventbrite's date-only one
    assert e.source_urls == ["https://meetup/1", "https://eb/1"]
    assert e.neighborhood == "King West"  # filled from the Eventbrite record


def test_online_and_in_person_versions_stay_separate():
    assert dedup_hash(raw()) != dedup_hash(raw(online=True))


def test_different_days_stay_separate():
    assert dedup_hash(raw()) != dedup_hash(raw(start_time=datetime(2026, 10, 6, 18, 30, tzinfo=TORONTO)))


# ---------- neighborhoods ----------

@pytest.mark.parametrize("kw,expected", [
    (dict(postal_code="M5V 1Z4"), "King West"),
    (dict(postal_code="L4V 1E8"), "GTA (outside Toronto)"),
    (dict(postal_code="M1P 4P5"), "Scarborough"),
    (dict(lat=43.6445, lng=-79.3952), "King West"),
    (dict(lat=44.5, lng=-79.0), None),
    (dict(online=True, postal_code="M5V 1Z4"), "Online"),
])
def test_neighborhood(kw, expected):
    assert neighborhood_for(raw(**kw)) == expected


# ---------- enrichment ----------

def test_keyword_fallback_drops_non_tech_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    events = merge([raw(title="Kubernetes Operators Deep Dive"), raw(title="Chess in the Park", url="https://x/2")])
    kept = enrich_mod.enrich(events)
    assert [e.title for e in kept] == ["Kubernetes Operators Deep Dive"]
    assert kept[0].category == "cloud-devops"


def test_claude_labels_are_applied(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    events = merge([raw(title="Rust Toronto"), raw(title="Real Estate AI Riches", url="https://x/2", start_time=datetime(2026, 10, 7, tzinfo=TORONTO))])
    parsed = enrich_mod.LabelBatch(results=[
        enrich_mod.EventLabel(key="0", is_tech=True, category="web-dev", tags=["Rust", "talks"], summary="Monthly Rust talks."),
        enrich_mod.EventLabel(key="1", is_tech=False, category="other", tags=[], summary="Not for developers."),
    ])

    class FakeMessages:
        def parse(self, **kwargs):
            assert kwargs["output_format"] is enrich_mod.LabelBatch
            return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)

    monkeypatch.setattr(enrich_mod.anthropic, "Anthropic", lambda: SimpleNamespace(messages=FakeMessages()))
    kept = enrich_mod.enrich(events)
    assert [e.title for e in kept] == ["Rust Toronto"]
    assert kept[0].tags == ["rust", "talks"]
    assert kept[0].summary == "Monthly Rust talks."


def test_claude_refusal_falls_back_to_keywords(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    class FakeMessages:
        def parse(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", parsed_output=None)

    monkeypatch.setattr(enrich_mod.anthropic, "Anthropic", lambda: SimpleNamespace(messages=FakeMessages()))
    kept = enrich_mod.enrich(merge([raw(title="LLM Evals Night")]))
    assert kept[0].category == "ai"
