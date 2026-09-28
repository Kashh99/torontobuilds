"""Claude pass: decide relevance, assign category/tags, write a one-line summary.

Scraped descriptions are messy (HTML fragments, agendas, sponsor blurbs). Keyword rules
can't tell a "Python for data teams" meetup from a "data-driven real estate investing"
seminar; Claude can. Without ANTHROPIC_API_KEY we fall back to keyword rules so the
pipeline still runs.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Literal

import anthropic
from pydantic import BaseModel

from .models import Event

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
BATCH_SIZE = 20
DESCRIPTION_CHARS = 1500

Category = Literal["ai", "web-dev", "data", "cloud-devops", "security", "hardware", "startup", "design-product", "career", "other"]
CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]

SYSTEM = """You classify events scraped from Eventbrite, Meetup and Luma for TorontoBuilds, \
a listing of tech events in Toronto for software developers, AI/ML people and startup founders.

For each event return:
- is_tech: true only if a working developer, engineer, data/AI practitioner or tech founder \
would plausibly go. Generic business networking, real estate, trading/crypto get-rich pitches, \
MLM, wellness, arts and hobby events are false even if they mention "tech" or "AI".
- category: the single best fit.
- tags: 1-5 short lowercase tags (technologies, formats like "talks", "hackathon", "workshop").
- summary: one plain sentence, max 20 words, saying why a Toronto developer would go. \
No hype words, no emoji, don't repeat the title.

Return one result per input event, echoing its key."""


class EventLabel(BaseModel):
    key: str
    is_tech: bool
    category: Category
    tags: list[str]
    summary: str


class LabelBatch(BaseModel):
    results: list[EventLabel]


KEYWORD_CATEGORIES = [
    ("ai", r"\b(ai|ml|llm|gpt|machine learning|genai|agents?|deep learning|nlp)\b"),
    ("security", r"\b(security|cyber\w*|infosec|owasp|pentest)\b"),
    ("cloud-devops", r"\b(cloud|aws|azure|gcp|kubernetes|devops|sre|infra|platform engineering)\b"),
    ("data", r"\b(data|analytics|sql|dbt|spark|warehouse)\b"),
    ("hardware", r"\b(hardware|robot\w*|iot|embedded|arduino|3d print\w*)\b"),
    ("web-dev", r"\b(javascript|typescript|react|node|web|frontend|css|python|rust|golang|developer)\b"),
    ("design-product", r"\b(ux|ui|design|product manag\w*|figma)\b"),
    ("startup", r"\b(startup|founder|vc|yc|y combinator|pitch|fundrais\w*|accelerator)\b"),
    ("career", r"\b(career|hiring|job fair|resume|interview)\b"),
]


def keyword_label(event: Event) -> None:
    text = f"{event.title} {event.description[:800]}".lower()
    event.category = next((c for c, pat in KEYWORD_CATEGORIES if re.search(pat, text)), "other")
    event.tags = [event.category]
    event.is_tech = event.category != "other"


def _prompt_for(batch: list[Event]) -> str:
    parts = []
    for i, e in enumerate(batch):
        parts.append(
            f"<event key=\"{i}\">\n<title>{e.title}</title>\n"
            f"<venue>{'online' if e.online else (e.venue_name or 'unknown')}</venue>\n"
            f"<description>{e.description[:DESCRIPTION_CHARS]}</description>\n</event>"
        )
    return "\n".join(parts)


def enrich(events: list[Event]) -> list[Event]:
    """Label events in place. Returns only the events judged to be tech events."""
    if not events:
        return []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set; using keyword labels for %d events", len(events))
        for e in events:
            keyword_label(e)
        return [e for e in events if e.is_tech]

    client = anthropic.Anthropic()
    for start in range(0, len(events), BATCH_SIZE):
        batch = events[start:start + BATCH_SIZE]
        try:
            response = client.messages.parse(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=[{"role": "user", "content": _prompt_for(batch)}],
                output_format=LabelBatch,
            )
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError) as err:
            log.error("Claude call failed for batch at %d (%s); using keyword labels", start, err)
            for e in batch:
                keyword_label(e)
            continue

        if response.stop_reason == "refusal" or response.parsed_output is None:
            log.warning("No structured output for batch at %d (stop_reason=%s); using keyword labels", start, response.stop_reason)
            for e in batch:
                keyword_label(e)
            continue

        by_key = {r.key: r for r in response.parsed_output.results}
        for i, e in enumerate(batch):
            label = by_key.get(str(i))
            if label is None:
                keyword_label(e)
                continue
            e.is_tech = label.is_tech
            e.category = label.category
            e.tags = [t.strip().lower() for t in label.tags if t.strip()][:5]
            e.summary = label.summary.strip()

    return [e for e in events if e.is_tech]
