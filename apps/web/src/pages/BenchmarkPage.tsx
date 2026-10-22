import { useQueryClient } from "@tanstack/react-query";
import { Suspense, lazy, useMemo, useState } from "react";
import { Link } from "react-router";

import { api, newIdempotencyKey } from "../api/client";
import { useBenchmark, useOrganization } from "../api/hooks";
import type { Artifact, BenchmarkPart, Check } from "../api/types";
import { useWorkspace } from "../auth/workspace";
import { Icon } from "../components/icons";
import { JobStateBadge } from "../components/status";
import { errorMessage, useToast } from "../components/toast";
import { Alert, Badge, Button, Card, Empty, Spinner } from "../components/ui";
import { formatBytes, formatDateTime, formatValue, humanize } from "../lib/format";

const ModelViewer = lazy(() => import("../viewer/ModelViewer"));

export const HOLE_LEGEND: [string, string][] = [
  ["Tapped", "#1a73e6"],
  ["Reamed", "#db2929"],
  ["Bored", "#f28c1a"],
  ["Clearance", "#33a852"],
  ["Drilled", "#9461cc"],
  ["Counterbore", "#14a8a8"],
];

const PREF_LABELS: Record<string, string> = {
  tap_drill: "tap-drill diameter",
  tap_drill_with_major_step: "tap drill + major-diameter step",
  major_diameter: "major diameter",
  minor_diameter: "minor diameter",
};

function ChecksTable({ checks }: { checks: Check[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>Check</th><th>Dims</th><th>Expected</th><th>Measured on solid</th><th>Result</th></tr></thead>
        <tbody>
          {checks.map((c, i) => (
            <tr key={i}>
              <td>{c.label || humanize(c.check)}</td>
              <td className="small mono">{c.dims.join(", ") || "—"}</td>
              <td className="num">{formatValue(c.expected, c.units)}</td>
              <td className="num">{formatValue(c.measured, c.units)}</td>
              <td>
                {c.status === "pass" ? <Badge tone="ok">Pass</Badge> : c.status === "fail" ? <Badge tone="danger">Fail</Badge> : <Badge>N/A</Badge>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PartResult({ part, artifacts }: { part: BenchmarkPart; artifacts: Artifact[] }) {
  const [showChecks, setShowChecks] = useState(false);
  const [show3d, setShow3d] = useState(part.variant === "nominal");
  const step = artifacts.find((a) => a.kind === "step");
  const glb = artifacts.find((a) => a.kind === "glb");
  const report = artifacts.find((a) => a.kind === "report");
  const v = part.validation;
  return (
    <Card
      title={<span className="row"><span className="mono">{part.part}</span> {part.title && <span className="muted" style={{ fontWeight: 500 }}>{part.title}</span>}</span>}
      subtitle={part.variant === "nominal" ? "Nominal model" : "Mid-tolerance model (asymmetric tolerances moved to the middle of the band)"}
      actions={v.passed ? <Badge tone="ok">{v.summary.passed}/{v.summary.total} checks passed</Badge> : <Badge tone="danger">{v.summary.failed} failed</Badge>}
    >
      <div className="stack">
        <div className="row">
          {step && (
            <a className="btn btn-primary btn-sm" href={`/api/v1/artifacts/${step.id}/download/`}>
              <Icon.Download width={14} height={14} /> {step.filename} <span className="subtle" style={{ color: "inherit", opacity: 0.8 }}>({formatBytes(step.size_bytes)})</span>
            </a>
          )}
          {report && <a className="btn btn-sm" href={`/api/v1/artifacts/${report.id}/download/`}>Check report (JSON)</a>}
          {glb && <Button size="sm" variant="ghost" onClick={() => setShow3d((s) => !s)}>{show3d ? "Hide 3D preview" : "Show 3D preview"}</Button>}
          <Button size="sm" variant="ghost" onClick={() => setShowChecks((s) => !s)}>{showChecks ? "Hide checks" : `Show all ${v.summary.total} checks`}</Button>
        </div>
        {show3d && glb && (
          <Suspense fallback={<div className="viewer"><div className="center-page"><Spinner /></div></div>}>
            <ModelViewer url={`/api/v1/artifacts/${glb.id}/download/?inline=1`} />
          </Suspense>
        )}
        {show3d && (
          <div className="legend">
            {HOLE_LEGEND.map(([label, color]) => <span key={label}><i style={{ background: color }} />{label}</span>)}
          </div>
        )}
        {(showChecks || !v.passed) && <ChecksTable checks={showChecks ? v.checks : v.checks.filter((c) => c.status === "fail")} />}
      </div>
    </Card>
  );
}

export function BenchmarkPage() {
  const { orgId, can } = useWorkspace();
  const benchmark = useBenchmark(orgId);
  const org = useOrganization(orgId);
  const queryClient = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      await api.post(`/api/v1/organizations/${orgId}/benchmark/`, {}, { idempotencyKey: newIdempotencyKey("benchmark") });
      await queryClient.invalidateQueries({ queryKey: ["benchmark", orgId] });
      toast("Benchmark queued");
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  }

  const latest = benchmark.data?.latest ?? null;
  const parts = (latest?.result?.parts as BenchmarkPart[] | undefined) ?? [];
  const byKey = useMemo(() => {
    const map = new Map<string, Artifact[]>();
    for (const a of benchmark.data?.artifacts ?? []) {
      const key = `${a.metadata.part}|${a.variant}`;
      map.set(key, [...(map.get(key) ?? []), a]);
    }
    return map;
  }, [benchmark.data]);
  const prefs = org.data?.preferences;
  const running = latest && ["queued", "running"].includes(latest.state);

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Geometry benchmark</h1>
          <p>
            Phase 0 evidence: three reference parts built by the isolated CAD engine, checked independently, and
            exported as STEP files for you to open in your own CAM software.
          </p>
        </div>
        {can("edit") && <Button variant="primary" busy={busy || Boolean(running)} onClick={run}>{running ? "Running…" : "Run benchmark"}</Button>}
      </div>

      <div className="grid-2">
        <Card title="What gets built">
          <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
            {benchmark.data?.specs.map((s) => (
              <li key={s.part}><span className="mono">{s.part}</span> · {s.title} <span className="subtle">({s.family})</span></li>
            ))}
          </ul>
          <p className="subtle" style={{ marginTop: 10 }}>
            Each part is checked for a valid single solid, overall size, origin on the datums, closed-form volume,
            every hole's diameter, position and depth, and a STEP reopen with the right units.
          </p>
        </Card>
        <Card title="Using your shop preferences" actions={<Link to={`/w/${orgId}/settings`} className="btn btn-sm">Change</Link>}>
          {prefs ? (
            <dl className="kv">
              <dt>Tapped holes</dt><dd>{PREF_LABELS[prefs.tapped_hole_model] ?? prefs.tapped_hole_model}</dd>
              <dt>STEP units</dt><dd>{prefs.step_units === "drawing" ? "Same as the drawing (no conversion)" : prefs.step_units}</dd>
              <dt>Mid-tolerance copy</dt><dd>{prefs.also_export_mid_tolerance ? "Exported too" : "Off"}</dd>
              <dt>Hole colours</dt><dd>{prefs.color_faces_by_hole_type ? "On" : "Off"}</dd>
              <dt>File names</dt><dd className="mono">{prefs.filename_pattern}</dd>
            </dl>
          ) : <Spinner />}
        </Card>
      </div>

      <Alert tone="info" title="Your part of Phase 0">
        Download the STEP files and open them in the Fusion and Mastercam versions you use. Confirm: units are inches,
        sizes match (plate 6.000 × 4.000 × .500), the origin sits on the datum corner, hole colours show, and hole
        recognition finds every hole. Record the result and your CAD versions; that completes the Phase 0 exit gate.
      </Alert>

      {benchmark.isLoading ? (
        <Spinner />
      ) : !latest ? (
        <Card><Empty title="No benchmark run yet" action={can("edit") ? <Button variant="primary" onClick={run} busy={busy}>Run benchmark</Button> : undefined}>Runs take a few seconds on the CAD worker.</Empty></Card>
      ) : (
        <>
          <div className="row">
            <strong>Latest run</strong>
            <JobStateBadge state={latest.state} />
            <span className="subtle">{formatDateTime(latest.created_at)} by {latest.requested_by_email ?? "system"}</span>
            {latest.engine_versions.cadquery && (
              <span className="subtle">CadQuery {latest.engine_versions.cadquery} · OCP {latest.engine_versions.ocp}</span>
            )}
            <Link to={`/w/${orgId}/jobs?job=${latest.id}`} className="small">Job details</Link>
          </div>
          {latest.state === "failed" && <Alert tone="danger" title={latest.error_code}>{latest.error_message}</Alert>}
          {latest.state === "unsupported" && <Alert tone="warn" title="Unsupported">{latest.error_message}</Alert>}
          {running && <Card><Spinner label="Building and checking parts in the CAD worker…" /></Card>}
          {parts.map((p) => (
            <PartResult key={`${p.part}-${p.variant}`} part={p} artifacts={byKey.get(`${p.part}|${p.variant}`) ?? []} />
          ))}
        </>
      )}
    </div>
  );
}
