# TorontoBuilds

**Live:** _not deployed yet — add the Vercel URL here_

**Every Toronto dev, AI and startup event from Eventbrite, Meetup and Luma in one list, with the same event posted in two places shown once.**

Checking three sites every week is tedious, and the same meetup often shows up on two of them with slightly different titles. TorontoBuilds scrapes all three nightly, merges duplicates, drops the non-tech noise those "science & tech" categories are full of, and lets you filter by topic, neighborhood and date.

**Tradeoff:** it scrapes public listing pages (schema.org JSON-LD and Meetup iCal feeds) instead of official APIs, so a site redesign can break a source overnight. A broken source is logged and skipped; the rest still update.

**Known gap:** Eventbrite blocks requests from GitHub Actions runners (HTTP 405), so it is disabled in `scraper/sources.json` for now. The parser still handles its pages; it needs a different place to run from or the official API.

## How it works

```
Eventbrite / Luma / Meetup pages ──► scraper (Python, nightly GitHub Action)
    JSON-LD + iCal parsers              │  parse ─► dedup ─► Claude labels ─► upsert
                                        ▼
                                 Postgres (Supabase) ──► Next.js frontend (Vercel)
```

- **Parsing** – `scraper/torontobuilds/fetchers.py`. Eventbrite, Luma and Meetup listing pages all embed schema.org `Event` JSON-LD, so one parser covers them. Individual Meetup groups add their iCal feed. Sources live in `scraper/sources.json`.
- **Dedup** – `scraper/torontobuilds/dedup.py`. `dedup_hash = sha1(normalized title | Toronto date | online/in-person)`. Title normalization lowercases, strips punctuation, drops words sources add freely ("Toronto", "meetup", months, years, "in-person") and sorts the rest, so "AI Tinkerers Toronto – Oct 2026" and "Toronto AI Tinkerers (In-Person)" collide. Merged events keep every source URL, take the time from whichever listing has one (Eventbrite listings are date-only), and fill missing fields from the others.
- **Neighborhood** – postal code prefix (FSA) first, then nearest known centroid within 1.5 km from lat/lng.
- **Claude** – `scraper/torontobuilds/enrich.py`. One structured-output call per 20 new events decides whether it is actually a tech event (the Eventbrite "science & tech" category includes pharmacy conferences and drone courses), assigns a category and tags, and writes a one-line "why go" summary. Events already labelled in the DB are not sent again. Without `ANTHROPIC_API_KEY`, keyword rules take over.

## Run it

### Scraper

```bash
cd scraper
python -m venv ../.venv && ../.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
../.venv/bin/pytest -q
../.venv/bin/python -m torontobuilds.run --dry-run                                  # print results, no DB
../.venv/bin/python -m torontobuilds.run --dry-run --json ../web/sample-events.json  # data for local frontend
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... ANTHROPIC_API_KEY=... ../.venv/bin/python -m torontobuilds.run
```

### Database

Create a Supabase project and run `supabase/migrations/20260927000000_init.sql` (SQL editor or `supabase db push`). Tables are read-only for the public; the scraper writes with the service role key.

### Frontend

```bash
cd web
npm install
npm run dev   # without Supabase env vars it reads web/sample-events.json
```

Set `SUPABASE_URL` and `SUPABASE_ANON_KEY` in Vercel (project root: `web`).

### Nightly job

`.github/workflows/scrape.yml` runs at 09:00 UTC. Add repo secrets `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ANTHROPIC_API_KEY`. It runs the tests first, then the scrape; it fails only if every source fails.

## Adding a source

Add an entry to `scraper/sources.json`. Any page with schema.org `Event` JSON-LD works with `"parser": "jsonld"`; any iCal feed works with `"parser": "ics"`. For a new site, also add a row to the `sources` table.
