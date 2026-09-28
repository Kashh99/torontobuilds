import { CATEGORIES, FORMAT, WHEN, getEvents, type Filters, type Format, type TechEvent, type When } from "@/lib/events";

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

function one(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

const TZ = "America/Toronto";

function dayKey(iso: string) {
  return new Date(iso).toLocaleDateString("en-CA", { timeZone: TZ });
}

function dayLabel(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: TZ });
}

function timeLabel(e: TechEvent) {
  const start = new Date(e.start_time);
  const time = start.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: TZ });
  // Eventbrite listings only publish a date; the scraper stores those at local midnight.
  return time === "12:00 AM" ? "Time TBA" : time;
}

function sourceName(url: string) {
  if (url.includes("meetup.com")) return "Meetup";
  if (url.includes("lu.ma") || url.includes("luma.com")) return "Luma";
  if (url.includes("eventbrite")) return "Eventbrite";
  return new URL(url).hostname;
}

export default async function Home({ searchParams }: { searchParams: SearchParams }) {
  const sp = await searchParams;
  const whenParam = one(sp.when);
  const formatParam = one(sp.format);
  const filters: Filters = {
    q: one(sp.q),
    category: one(sp.category),
    neighborhood: one(sp.neighborhood),
    when: (whenParam in WHEN ? whenParam : "month") as When,
    format: (formatParam in FORMAT ? formatParam : "in-person") as Format,
  };
  const { events, neighborhoods, total } = await getEvents(filters);

  const byDay = new Map<string, TechEvent[]>();
  for (const e of events) {
    const k = dayKey(e.start_time);
    byDay.set(k, [...(byDay.get(k) ?? []), e]);
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">TorontoBuilds</h1>
        <p className="mt-2 text-muted">
          Every Toronto dev, AI and startup event from Eventbrite, Meetup and Luma, in one list with duplicates
          merged. Refreshed nightly.
        </p>
      </header>

      <form className="mb-8 grid grid-cols-2 gap-2 sm:grid-cols-5" action="/">
        <input
          name="q"
          defaultValue={filters.q}
          placeholder="Search: rust, agents, pitch night…"
          className="col-span-2 rounded-md border border-line bg-surface px-3 py-2 sm:col-span-5"
        />
        <select name="category" defaultValue={filters.category} className="rounded-md border border-line bg-surface px-2 py-2">
          <option value="">All topics</option>
          {Object.entries(CATEGORIES).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select name="neighborhood" defaultValue={filters.neighborhood} className="rounded-md border border-line bg-surface px-2 py-2">
          <option value="">All neighborhoods</option>
          {neighborhoods.map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
        <select name="when" defaultValue={filters.when} className="rounded-md border border-line bg-surface px-2 py-2">
          {Object.entries(WHEN).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select name="format" defaultValue={filters.format} className="rounded-md border border-line bg-surface px-2 py-2">
          {Object.entries(FORMAT).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button className="rounded-md bg-accent px-3 py-2 font-medium text-white hover:opacity-90">Filter</button>
      </form>

      <p className="mb-4 text-sm text-muted">
        {events.length} of {total} upcoming events
      </p>

      {events.length === 0 && <p className="py-12 text-center text-muted">Nothing matches. Try a wider date range.</p>}

      {[...byDay.entries()].map(([day, list]) => (
        <section key={day} className="mb-8">
          <h2 className="sticky top-0 bg-background/95 py-2 text-sm font-semibold uppercase tracking-wide text-muted backdrop-blur">
            {dayLabel(list[0].start_time)}
          </h2>
          <ul className="divide-y divide-line">
            {list.map((e) => (
              <li key={e.dedup_hash} className="py-4">
                <div className="flex items-baseline gap-3">
                  <span className="w-20 shrink-0 text-sm tabular-nums text-muted">{timeLabel(e)}</span>
                  <div className="min-w-0">
                    <a href={e.url} target="_blank" rel="noopener noreferrer" className="font-semibold hover:underline">
                      {e.title}
                    </a>
                    {e.summary && <p className="mt-1 text-sm">{e.summary}</p>}
                    <p className="mt-1 text-sm text-muted">
                      {e.online ? "Online" : [e.venue_name, e.neighborhood].filter(Boolean).join(" · ") || "Location TBA"}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                      {e.category && CATEGORIES[e.category] && (
                        <span className="rounded bg-accent/10 px-1.5 py-0.5 font-medium text-accent">{CATEGORIES[e.category]}</span>
                      )}
                      {e.tags
                        .filter((t) => t !== e.category)
                        .map((t) => (
                          <span key={t} className="rounded bg-surface px-1.5 py-0.5 text-muted">
                            {t}
                          </span>
                        ))}
                      <span className="ml-auto text-muted">
                        {e.source_urls.map((u, i) => (
                          <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="hover:underline">
                            {i > 0 && " · "}
                            {sourceName(u)}
                          </a>
                        ))}
                      </span>
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
