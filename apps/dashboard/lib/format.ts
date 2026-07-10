// Shared fa-IR formatting helpers (slice 1 extracted from the queue page).
// All strings come from locales/fa.json — never hardcoded here.
import fa from "@/locales/fa.json";

export function faNum(n: number): string {
  return n.toLocaleString("fa-IR");
}

// API timestamps are timezone-aware ISO; normalize defensively if the
// offset is missing.
function parseIso(iso: string): number {
  const normalized = /Z$|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  return Date.parse(normalized);
}

// Relative time, all strings from locales/fa.json.
export function relativeTime(iso: string): string {
  const then = parseIso(iso);
  if (Number.isNaN(then)) return "";
  const minutes = Math.max(0, Math.floor((Date.now() - then) / 60_000));
  if (minutes < 1) return fa.time.just_now;
  if (minutes < 60) return fa.time.minutes_ago.replace("{n}", faNum(minutes));
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return fa.time.hours_ago.replace("{n}", faNum(hours));
  const days = Math.floor(hours / 24);
  if (days === 1) return fa.time.yesterday;
  return fa.time.days_ago.replace("{n}", faNum(days));
}

// Absolute short date+time in fa-IR — used for future timestamps
// (e.g. scheduled_at) where relative time reads wrong.
export function faDateTime(iso: string): string {
  const t = parseIso(iso);
  if (Number.isNaN(t)) return "";
  return new Date(t).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });
}
