import { readFile } from "node:fs/promises";
import path from "node:path";
import { createClient } from "@supabase/supabase-js";

export type TechEvent = {
  dedup_hash: string;
  title: string;
  summary: string | null;
  description: string;
  start_time: string;
  end_time: string | null;
  venue_name: string | null;
  address: string | null;
  neighborhood: string | null;
  online: boolean;
  url: string;
  source_urls: string[];
  image_url: string | null;
  category: string | null;
  tags: string[];
};

export const CATEGORIES: Record<string, string> = {
  ai: "AI / ML",
  "web-dev": "Web & dev",
  data: "Data",
  "cloud-devops": "Cloud & DevOps",
  security: "Security",
  hardware: "Hardware",
  startup: "Startups",
  "design-product": "Design & product",
  career: "Career",
};

export const WHEN = {
  week: "Next 7 days",
  weekend: "This weekend",
  month: "Next 30 days",
  all: "Anytime",
} as const;
export type When = keyof typeof WHEN;

export const FORMAT = {
  "in-person": "In person",
  online: "Online",
  any: "In person + online",
} as const;
export type Format = keyof typeof FORMAT;

export type Filters = {
  q: string;
  category: string;
  neighborhood: string;
  when: When;
  format: Format;
};

const COLUMNS =
  "dedup_hash,title,summary,description,start_time,end_time,venue_name,address,neighborhood,online,url,source_urls,image_url,category,tags";

// Without Supabase env vars (local dev), read the file written by
// `python -m torontobuilds.run --dry-run --json ../web/sample-events.json`.
async function loadUpcoming(): Promise<TechEvent[]> {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_ANON_KEY;
  const since = new Date(Date.now() - 3 * 3600_000).toISOString();

  if (!url || !key) {
    const file = path.join(process.cwd(), "sample-events.json");
    const rows: TechEvent[] = JSON.parse(await readFile(file, "utf8").catch(() => "[]"));
    return rows.filter((e) => e.start_time >= since).sort((a, b) => a.start_time.localeCompare(b.start_time));
  }

  const supabase = createClient(url, key, { auth: { persistSession: false } });
  const { data, error } = await supabase
    .from("events")
    .select(COLUMNS)
    .gte("start_time", since)
    .order("start_time")
    .limit(1000);
  if (error) throw new Error(`Supabase: ${error.message}`);
  return data as TechEvent[];
}

function torontoDay(d: Date): number {
  // 0 = Sunday, in Toronto time regardless of server timezone
  const name = d.toLocaleDateString("en-US", { weekday: "short", timeZone: "America/Toronto" });
  return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(name);
}

function matchesWhen(e: TechEvent, when: When, now: Date): boolean {
  const start = new Date(e.start_time);
  const days = (start.getTime() - now.getTime()) / 86_400_000;
  switch (when) {
    case "week":
      return days <= 7;
    case "month":
      return days <= 30;
    case "weekend": {
      // Friday evening through Sunday of the current (or upcoming) weekend
      if (days > 7) return false;
      const day = torontoDay(start);
      const hour = Number(start.toLocaleString("en-US", { hour: "numeric", hour12: false, timeZone: "America/Toronto" }));
      return day === 0 || day === 6 || (day === 5 && hour >= 17);
    }
    default:
      return true;
  }
}

export async function getEvents(filters: Filters) {
  const all = await loadUpcoming();
  const now = new Date();
  const q = filters.q.trim().toLowerCase();

  const neighborhoods = [
    ...new Set(all.map((e) => e.neighborhood).filter((n): n is string => !!n && n !== "Online")),
  ].sort();

  const events = all.filter(
    (e) =>
      (!filters.category || e.category === filters.category) &&
      (!filters.neighborhood || e.neighborhood === filters.neighborhood) &&
      (filters.format === "any" || e.online === (filters.format === "online")) &&
      matchesWhen(e, filters.when, now) &&
      (!q || `${e.title} ${e.summary ?? ""} ${e.tags.join(" ")} ${e.venue_name ?? ""}`.toLowerCase().includes(q)),
  );

  return { events, neighborhoods, total: all.length };
}
