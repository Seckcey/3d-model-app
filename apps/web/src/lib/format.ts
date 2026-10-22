export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

const dateTime = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
const dateOnly = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" });

export function formatDateTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : dateTime.format(date);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  return Number.isNaN(date.getTime()) ? "—" : dateOnly.format(date);
}

export function relativeTime(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return "—";
  const seconds = Math.round((now.getTime() - new Date(value).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}

export function shortHash(sha: string): string {
  return sha ? `${sha.slice(0, 10)}…` : "";
}

export function formatValue(value: unknown, units = ""): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return `${trimNumber(value)}${units && !units.includes("^") ? ` ${units}` : ""}`;
  if (Array.isArray(value)) return `(${value.map((v) => (typeof v === "number" ? trimNumber(v) : String(v))).join(", ")})`;
  return String(value);
}

export function trimNumber(value: number): string {
  if (Math.abs(value) >= 1e-3 || value === 0) return Number(value.toFixed(6)).toString();
  return value.toExponential(2);
}

export const ROLE_LABELS: Record<string, string> = {
  owner: "Owner",
  engineer: "Engineer",
  reviewer: "Reviewer",
  viewer: "Viewer",
};

export const ROLE_HELP: Record<string, string> = {
  owner: "Manages the workspace, members, policies and retention",
  engineer: "Uploads drawings, edits projects and runs jobs",
  reviewer: "Inspects reports and approves revisions",
  viewer: "Views projects and downloads released files",
};

export function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
