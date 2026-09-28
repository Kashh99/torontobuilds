create table sources (
  id serial primary key,
  name text not null unique,
  base_url text not null,
  scraper_type text not null check (scraper_type in ('jsonld', 'ics'))
);

insert into sources (name, base_url, scraper_type) values
  ('eventbrite', 'https://www.eventbrite.ca', 'jsonld'),
  ('meetup', 'https://www.meetup.com', 'jsonld'),
  ('luma', 'https://luma.com', 'jsonld');

create table events (
  id bigint generated always as identity primary key,
  source_id int not null references sources (id),
  title text not null,
  description text not null default '',
  summary text,                          -- one-line "why go", written by Claude
  start_time timestamptz not null,
  end_time timestamptz,
  venue_name text,
  address text,
  neighborhood text,
  online boolean not null default false,
  url text not null,
  source_urls text[] not null default '{}',  -- every listing of this event, across sources
  image_url text,
  category text check (category in ('ai', 'web-dev', 'data', 'cloud-devops', 'security', 'hardware', 'startup', 'design-product', 'career', 'other')),
  tags text[] not null default '{}',
  dedup_hash text not null unique,       -- sha1(normalized title | date | online/in-person)
  scraped_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  search tsvector generated always as (
    to_tsvector('english', title || ' ' || coalesce(summary, '') || ' ' || description)
  ) stored
);

create index events_start_time_idx on events (start_time);
create index events_category_idx on events (category);
create index events_search_idx on events using gin (search);

-- Public read-only. The scraper writes with the service role key, which bypasses RLS.
alter table sources enable row level security;
alter table events enable row level security;
create policy "sources are public" on sources for select using (true);
create policy "events are public" on events for select using (true);
