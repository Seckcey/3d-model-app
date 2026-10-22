import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { api, newIdempotencyKey, upload } from "../api/client";
import { useJobs, usePart, useRevisions } from "../api/hooks";
import type { IntakeReport, Revision, SourceFile } from "../api/types";
import { useWorkspace } from "../auth/workspace";
import { Icon } from "../components/icons";
import { ExportControlBadge, IntakeBadge, JOB_KIND_LABELS, JobStateBadge, RevisionStateBadge } from "../components/status";
import { errorMessage, useToast } from "../components/toast";
import { Alert, Badge, Button, Card, Empty, ErrorText, Field, Modal, PageLoading, Spinner } from "../components/ui";
import { formatBytes, formatDateTime, humanize, relativeTime, shortHash } from "../lib/format";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";

function hasReport(report: SourceFile["intake_report"]): report is IntakeReport {
  return Boolean(report && "pages" in report);
}

function DropZone({ revision, onUploaded }: { revision: Revision; onUploaded: () => void }) {
  const [active, setActive] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const input = useRef<HTMLInputElement>(null);
  const toast = useToast();

  async function send(files: FileList | File[]) {
    setError(null);
    for (const file of Array.from(files)) {
      try {
        setProgress(0);
        await upload<SourceFile>(`/api/v1/revisions/${revision.id}/files/`, file, setProgress);
        toast(`${file.name} uploaded. Intake check started.`);
        onUploaded();
      } catch (err) {
        setError(new Error(`${file.name}: ${errorMessage(err)}`));
      } finally {
        setProgress(null);
      }
    }
  }

  return (
    <div className="stack-sm">
      <div
        className={`dropzone ${active ? "active" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setActive(true);
        }}
        onDragLeave={() => setActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setActive(false);
          if (e.dataTransfer.files.length) void send(e.dataTransfer.files);
        }}
      >
        <Icon.Upload width={28} height={28} />
        <div style={{ fontWeight: 600, marginTop: 6 }}>Drop the customer drawing here, or click to choose</div>
        <div className="subtle">PDF (vector PDFs work best), PNG or JPEG · originals are stored unchanged and hashed</div>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) void send(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {progress !== null && (
        <div className="progress" aria-label="Upload progress"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
      )}
      <ErrorText error={error} />
    </div>
  );
}

function Hints({ report }: { report: IntakeReport }) {
  const hints = report.hints;
  if (!hints) return <p className="subtle">No vector text to read hints from (scanned page). OCR arrives in Phase 2.</p>;
  const row = (label: string, value: React.ReactNode) => (
    <>
      <dt>{label}</dt>
      <dd>{value || <span className="subtle">not found</span>}</dd>
    </>
  );
  return (
    <dl className="kv">
      {row("Units", hints.units ? (hints.units === "in" ? "Inches" : "Millimetres") : null)}
      {row("Projection", hints.projection ? humanize(hints.projection) : null)}
      {row("Revision in text", hints.revision_candidates.join(", "))}
      {row("Material", hints.material_candidates.join(" · "))}
      {row("Outside processes", hints.outside_processes.length ? (
        <span className="chips">{hints.outside_processes.map((p) => <span className="chip" key={p}>{p}</span>)}</span>
      ) : null)}
      {row("Thread callouts", hints.thread_callouts.length ? (
        <span className="chips">{hints.thread_callouts.map((t) => <span className="chip mono" key={t}>{t}</span>)}</span>
      ) : null)}
      {row("General tolerance block", hints.general_tolerance_block ? "Present" : null)}
    </dl>
  );
}

function FileCard({ file, canDownload, canEdit, revision, onChanged }: {
  file: SourceFile;
  canDownload: boolean;
  canEdit: boolean;
  revision: Revision;
  onChanged: () => void;
}) {
  const [preview, setPreview] = useState<{ page: number; id: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const report = hasReport(file.intake_report) ? file.intake_report : null;
  const markings = report?.export_control.markings ?? [];

  async function rerun() {
    setBusy(true);
    try {
      await api.post(`/api/v1/revisions/${revision.id}/jobs/`, { target: "intake_check", source_file: file.id }, {
        idempotencyKey: newIdempotencyKey(`intake-rerun:${file.id}`),
      });
      toast("Intake check queued");
      onChanged();
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3>{file.original_name}</h3>
          <p className="subtle">
            {file.page_count} page{file.page_count === 1 ? "" : "s"} · {formatBytes(file.size_bytes)} · uploaded {relativeTime(file.created_at)}
            {file.uploaded_by_email ? ` by ${file.uploaded_by_email}` : ""} · SHA-256 <span className="mono" title={file.sha256}>{shortHash(file.sha256)}</span>
          </p>
        </div>
        <div className="row">
          <IntakeBadge status={file.intake_status} />
          {canEdit && file.intake_status !== "pending" && <Button size="sm" busy={busy} onClick={rerun}>Re-check</Button>}
          {canDownload && (
            <a className="btn btn-sm" href={`/api/v1/files/${file.id}/download/`}>
              <Icon.Download width={14} height={14} /> Original
            </a>
          )}
        </div>
      </div>
      <div className="card-body stack">
        {file.thumbnails.length > 0 ? (
          <div className="thumbs">
            {file.thumbnails.map((t) => (
              <button key={t.page} className="thumb" onClick={() => t.page_image && setPreview({ page: t.page, id: t.page_image })} title="Open page preview">
                {t.thumbnail ? <img src={`/api/v1/artifacts/${t.thumbnail}/download/?inline=1`} alt={`Page ${t.page}`} loading="lazy" /> : null}
                <span>Page {t.page}{report?.pages[t.page - 1] ? ` · ${report.pages[t.page - 1].width_in ?? "?"}×${report.pages[t.page - 1].height_in ?? "?"} in` : ""}</span>
              </button>
            ))}
          </div>
        ) : file.intake_status === "pending" ? (
          <Spinner label="Rendering pages and checking the drawing…" />
        ) : null}

        {markings.some((m) => m.severity === "block") && (
          <Alert tone="danger" title="Export-control or restricted marking found">
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {markings.filter((m) => m.severity === "block").map((m, i) => (
                <li key={i}><strong>{m.kind}</strong> (page {m.page}): <span className="muted">“{m.text}”</span></li>
              ))}
            </ul>
          </Alert>
        )}
        {report && report.warnings.length > 0 && (
          <Alert tone="warn" title="Intake warnings">
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {report.warnings.map((w, i) => (
                <li key={i}>{w.page ? `Page ${w.page}: ` : ""}{w.message}</li>
              ))}
            </ul>
          </Alert>
        )}
        {report && (
          <details className="disclosure" open>
            <summary>Drawing hints (unverified text matches for the reviewer)</summary>
            <div style={{ marginTop: 10 }}><Hints report={report} /></div>
          </details>
        )}
        {markings.some((m) => m.severity === "info") && (
          <p className="subtle">Also noted: {markings.filter((m) => m.severity === "info").map((m) => m.kind).join(", ")}</p>
        )}
      </div>
      {preview && (
        <Modal title={`${file.original_name} · page ${preview.page}`} onClose={() => setPreview(null)} wide>
          <div className="lightbox"><img src={`/api/v1/artifacts/${preview.id}/download/?inline=1`} alt={`Page ${preview.page}`} /></div>
        </Modal>
      )}
    </div>
  );
}

function ExportControlPanel({ revision, onChanged }: { revision: Revision; onChanged: () => void }) {
  const { can } = useWorkspace();
  const [decision, setDecision] = useState<"cleared" | "confirmed" | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/revisions/${revision.id}/export-control/`, { decision, reason });
      setDecision(null);
      setReason("");
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const detected = revision.export_control === "detected";
  return (
    <div className="stack-sm">
      <div className="row">
        <Icon.Shield width={18} height={18} />
        <strong>Export control</strong>
        <ExportControlBadge value={revision.export_control} />
        {revision.effective_external_ai ? <Badge tone="warn">External AI may be used</Badge> : <Badge tone="ok">Processed only on this server</Badge>}
      </div>
      <p className="subtle">
        {detected
          ? "A restricted marking was found. External processing is locked. An owner must confirm the drawing is controlled or clear it with a reason."
          : revision.export_control === "cleared"
            ? "An owner recorded that this drawing is not export controlled."
            : revision.export_control === "confirmed"
              ? "An owner confirmed this drawing is controlled. It will only ever be processed locally."
              : "Drawings are treated as controlled until an owner clears them. No marking found is not proof of clearance."}
      </p>
      {can("manage") && revision.export_control !== "confirmed" && (
        <div className="row">
          <Button size="sm" variant="danger" onClick={() => setDecision("confirmed")}>Mark as controlled</Button>
          {revision.export_control !== "cleared" && revision.source_files.length > 0 && (
            <Button size="sm" onClick={() => setDecision("cleared")}>Clear: not controlled</Button>
          )}
        </div>
      )}
      {decision && (
        <Modal
          title={decision === "confirmed" ? "Mark drawing as controlled" : "Clear export-control review"}
          subtitle="This decision and your reason are recorded in the audit log."
          onClose={() => setDecision(null)}
          footer={<><Button onClick={() => setDecision(null)}>Cancel</Button><Button variant="primary" busy={busy} onClick={submit} disabled={reason.trim().length < 5}>Record decision</Button></>}
        >
          <div className="stack">
            {decision === "cleared" && (
              <Alert tone="warn">
                Only clear a drawing when you know its jurisdiction (for example EAR99 or a commercial part with no
                export classification). This is not legal advice; ask export counsel when unsure.
              </Alert>
            )}
            <Field label="Reason" help="e.g. ITAR Cat. VIII per customer PO, or Commercial part, EAR99 per customer">
              {(id) => <textarea id={id} className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} />}
            </Field>
            <ErrorText error={error} />
          </div>
        </Modal>
      )}
    </div>
  );
}

function NewRevisionModal({ partId, onClose, onCreated }: { partId: string; onClose: () => void; onCreated: (r: Revision) => void }) {
  const [letter, setLetter] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      const revision = await api.post<Revision>(`/api/v1/parts/${partId}/revisions/`, { drawing_revision: letter, notes });
      onCreated(revision);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="New revision" subtitle="Use this when the customer sends a new drawing revision." onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={submit}>Create revision</Button></>}>
      <div className="stack">
        <Field label="Customer drawing revision">{(id) => <input id={id} className="input" value={letter} maxLength={20} onChange={(e) => setLetter(e.target.value.toUpperCase())} placeholder="e.g. D" />}</Field>
        <Field label="What changed (optional)">{(id) => <textarea id={id} className="textarea" value={notes} onChange={(e) => setNotes(e.target.value)} />}</Field>
        <ErrorText error={error} />
      </div>
    </Modal>
  );
}

export function PartPage() {
  const { partId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const { orgId, can } = useWorkspace();
  const part = usePart(partId);
  const revisions = useRevisions(partId);
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const selectedId = params.get("rev") ?? revisions.data?.[0]?.id ?? "";
  const revision = revisions.data?.find((r) => r.id === selectedId) ?? revisions.data?.[0];
  const jobs = useJobs({ revision: revision?.id ?? "" }, true, Boolean(revision));

  useEffect(() => {
    if (jobs.data?.results.some((j) => j.state === "succeeded")) {
      void queryClient.invalidateQueries({ queryKey: ["revisions", partId] });
    }
  }, [jobs.data, partId, queryClient]);

  if (part.isLoading || revisions.isLoading) return <PageLoading />;
  if (part.error || !part.data) return <ErrorText error={part.error ?? new Error("Part not found.")} />;
  const p = part.data;
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["revisions", partId] });
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
  };
  const editable = revision && can("edit") && (revision.state === "draft" || revision.state === "needs_input");

  return (
    <div className="stack">
      <div>
        <div className="crumbs">
          <Link to={`/w/${orgId}`}>Projects</Link> / <Link to={`/w/${orgId}/projects/${p.project}`}>{p.project_name}</Link> / <span>{p.part_number}</span>
        </div>
        <div className="page-header">
          <div>
            <h1 className="mono" style={{ fontSize: "1.5rem" }}>{p.part_number}</h1>
            <p>{[p.description, p.material, p.customer_name].filter(Boolean).join(" · ") || "No description"}</p>
          </div>
          {can("edit") && <Button onClick={() => setCreating(true)}><Icon.Plus width={16} height={16} /> New revision</Button>}
        </div>
      </div>

      {!revisions.data?.length ? (
        <Card><Empty title="No revisions">Create a revision for the drawing you received.</Empty></Card>
      ) : (
        <>
          <div className="tabs" role="tablist">
            {revisions.data.map((r) => (
              <button
                key={r.id}
                role="tab"
                aria-selected={r.id === revision?.id}
                className={`tab ${r.id === revision?.id ? "active" : ""}`}
                onClick={() => setParams({ rev: r.id })}
              >
                Rev {r.drawing_revision || "?"} <span className="subtle">#{r.sequence}</span>
              </button>
            ))}
          </div>
          {revision && (
            <div className="stack">
              <Card>
                <div className="row-between">
                  <div className="row">
                    <h2>Drawing revision {revision.drawing_revision || "(not set)"}</h2>
                    <RevisionStateBadge state={revision.state} />
                    <span className="subtle">Model iteration #{revision.sequence} · created {formatDateTime(revision.created_at)}</span>
                  </div>
                </div>
                {revision.notes && <p className="muted" style={{ marginTop: 8 }}>{revision.notes}</p>}
                <div className="divider" style={{ margin: "14px 0" }} />
                <ExportControlPanel revision={revision} onChanged={refresh} />
              </Card>

              {editable && <DropZone revision={revision} onUploaded={refresh} />}

              {revision.source_files.length === 0 ? (
                <Card><Empty title="No drawing uploaded yet">Upload the customer's drawing to run the intake check.</Empty></Card>
              ) : (
                revision.source_files.map((f) => (
                  <FileCard key={f.id} file={f} revision={revision} canEdit={Boolean(can("edit"))} canDownload={can("download_sources")} onChanged={refresh} />
                ))
              )}

              <Card flush title="Jobs for this revision" subtitle="Intake checks now; extraction and model generation in later phases">
                {!jobs.data?.results.length ? (
                  <div className="card-body subtle">No jobs yet.</div>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead><tr><th>Job</th><th>State</th><th>File</th><th>Attempts</th><th>Queued</th><th>Duration</th><th>Message</th></tr></thead>
                      <tbody>
                        {jobs.data.results.map((j) => (
                          <tr key={j.id}>
                            <td><Link to={`/w/${orgId}/jobs?job=${j.id}`}>{JOB_KIND_LABELS[j.kind] ?? j.kind}</Link></td>
                            <td><JobStateBadge state={j.state} /></td>
                            <td className="small">{j.source_file_name ?? "—"}</td>
                            <td className="num">{j.attempts}/{j.max_attempts}</td>
                            <td className="subtle nowrap">{relativeTime(j.queued_at)}</td>
                            <td className="num">{j.elapsed_seconds !== null ? `${j.elapsed_seconds.toFixed(1)} s` : "—"}</td>
                            <td className="small">{j.error_message || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </div>
          )}
        </>
      )}
      {creating && (
        <NewRevisionModal
          partId={partId}
          onClose={() => setCreating(false)}
          onCreated={(r) => {
            setCreating(false);
            refresh();
            setParams({ rev: r.id });
          }}
        />
      )}
    </div>
  );
}
