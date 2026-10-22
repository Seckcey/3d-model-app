import type { ExportControl, JobState, RevisionState, SourceFile } from "../api/types";
import { Badge } from "./ui";

const JOB: Record<JobState, { tone: "ok" | "warn" | "danger" | "info" | "neutral"; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  running: { tone: "info", label: "Running" },
  waiting_input: { tone: "warn", label: "Waiting for input" },
  succeeded: { tone: "ok", label: "Succeeded" },
  failed: { tone: "danger", label: "Failed" },
  unsupported: { tone: "warn", label: "Unsupported" },
  canceled: { tone: "neutral", label: "Canceled" },
};

export function JobStateBadge({ state }: { state: JobState }) {
  const s = JOB[state];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

const REVISION: Record<RevisionState, { tone: "ok" | "warn" | "danger" | "info" | "neutral"; label: string }> = {
  draft: { tone: "neutral", label: "Draft" },
  needs_input: { tone: "warn", label: "Needs input" },
  ready_for_review: { tone: "info", label: "Ready for review" },
  approved: { tone: "ok", label: "Approved" },
  released: { tone: "ok", label: "Released" },
  superseded: { tone: "neutral", label: "Superseded" },
};

export function RevisionStateBadge({ state }: { state: RevisionState }) {
  const s = REVISION[state];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function IntakeBadge({ status }: { status: SourceFile["intake_status"] }) {
  if (status === "pending") return <Badge tone="info">Checking…</Badge>;
  if (status === "ok") return <Badge tone="ok">Intake OK</Badge>;
  if (status === "warning") return <Badge tone="warn">Check warnings</Badge>;
  return <Badge tone="danger">Intake failed</Badge>;
}

export function ExportControlBadge({ value }: { value: ExportControl }) {
  switch (value) {
    case "detected":
      return <Badge tone="danger">Export marking detected</Badge>;
    case "confirmed":
      return <Badge tone="danger">Controlled</Badge>;
    case "cleared":
      return <Badge tone="ok">Cleared by owner</Badge>;
    case "none_found":
      return <Badge tone="neutral">No marking found</Badge>;
    default:
      return <Badge tone="neutral">Not scanned</Badge>;
  }
}

export function AiBadge({ allowed }: { allowed: boolean }) {
  return allowed ? <Badge tone="warn">External AI allowed</Badge> : <Badge tone="ok">Local processing only</Badge>;
}

export const JOB_KIND_LABELS: Record<string, string> = {
  intake_check: "Intake check",
  geometry_benchmark: "Geometry benchmark",
};
