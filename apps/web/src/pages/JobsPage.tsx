import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import { api } from "../api/client";
import { useJob, useJobs } from "../api/hooks";
import type { Job } from "../api/types";
import { useWorkspace } from "../auth/workspace";
import { JOB_KIND_LABELS, JobStateBadge } from "../components/status";
import { errorMessage, useToast } from "../components/toast";
import { Button, Card, Empty, Modal, Spinner } from "../components/ui";
import { formatDateTime, relativeTime } from "../lib/format";

function JobDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useWorkspace();
  const job = useJob(id);
  const toast = useToast();
  const queryClient = useQueryClient();
  async function cancel() {
    try {
      await api.post(`/api/v1/jobs/${id}/cancel/`);
      await queryClient.invalidateQueries({ queryKey: ["job", id] });
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  }
  const j = job.data;
  const active = j && ["queued", "running", "waiting_input"].includes(j.state);
  return (
    <Modal
      title={j ? JOB_KIND_LABELS[j.kind] ?? j.kind : "Job"}
      subtitle={j ? `Job ${j.id}` : undefined}
      onClose={onClose}
      wide
      footer={
        <>
          {active && can("edit") && !j?.cancel_requested && <Button variant="danger" onClick={cancel}>Cancel job</Button>}
          <Button onClick={onClose}>Close</Button>
        </>
      }
    >
      {!j ? (
        <Spinner />
      ) : (
        <div className="stack">
          <div className="row">
            <JobStateBadge state={j.state} />
            {j.stage && <span className="chip">Stage: {j.stage}</span>}
            <span className="chip">Attempt {j.attempts} of {j.max_attempts}</span>
            <span className="chip">Processing: {j.processing_location}</span>
            {j.cancel_requested && <span className="chip">Cancellation requested</span>}
          </div>
          {j.error_message && (
            <div className="alert danger"><div><strong>{j.error_code || "Error"}</strong>{j.error_message}</div></div>
          )}
          <div className="grid-2">
            <dl className="kv">
              <dt>Queued</dt><dd>{formatDateTime(j.queued_at)}</dd>
              <dt>Started</dt><dd>{formatDateTime(j.started_at)}</dd>
              <dt>Finished</dt><dd>{formatDateTime(j.finished_at)}</dd>
              <dt>Elapsed</dt><dd>{j.elapsed_seconds !== null ? `${j.elapsed_seconds.toFixed(2)} s` : "—"}</dd>
              <dt>Requested by</dt><dd>{j.requested_by_email ?? "—"}</dd>
              <dt>File</dt><dd>{j.source_file_name ?? "—"}</dd>
            </dl>
            <dl className="kv">
              {Object.entries(j.engine_versions).map(([k, v]) => (
                <span key={k} style={{ display: "contents" }}><dt>{k}</dt><dd className="mono">{String(v)}</dd></span>
              ))}
              {Object.entries(j.usage).map(([k, v]) => (
                <span key={k} style={{ display: "contents" }}><dt>{k}</dt><dd className="mono">{v === null ? "—" : String(v)}</dd></span>
              ))}
            </dl>
          </div>
          <div>
            <h3 style={{ marginBottom: 8 }}>Timeline</h3>
            <ol className="timeline">
              {j.events?.map((e, i) => (
                <li key={i}><time>{formatDateTime(e.at)}</time><span>{e.message || e.state}</span></li>
              ))}
            </ol>
          </div>
          {Object.keys(j.result).length > 0 && (
            <details className="disclosure">
              <summary>Result data</summary>
              <pre className="json">{JSON.stringify(j.result, null, 2)}</pre>
            </details>
          )}
        </div>
      )}
    </Modal>
  );
}

export function JobsPage() {
  const { orgId } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const state = params.get("state") ?? "";
  const filters: Record<string, string> = { organization: orgId };
  if (state) filters.state = state;
  const jobs = useJobs(filters);
  const selected = params.get("job");

  const open = (job: Job) => {
    const next = new URLSearchParams(params);
    next.set("job", job.id);
    setParams(next);
  };

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Jobs</h1>
          <p>Background work with durable records: every attempt, retry and failure reason is kept.</p>
        </div>
        <select className="select" style={{ width: 200 }} value={state} aria-label="State"
          onChange={(e) => { const n = new URLSearchParams(params); if (e.target.value) n.set("state", e.target.value); else n.delete("state"); setParams(n); }}>
          <option value="">All states</option>
          <option value="queued">Queued</option>
          <option value="running">Running</option>
          <option value="succeeded">Succeeded</option>
          <option value="failed">Failed</option>
          <option value="unsupported">Unsupported</option>
          <option value="canceled">Canceled</option>
        </select>
      </div>
      <Card flush>
        {jobs.isLoading ? (
          <div className="card-body"><Spinner /></div>
        ) : !jobs.data?.results.length ? (
          <Empty title="No jobs">Jobs appear here when drawings are uploaded or the geometry benchmark runs.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Job</th><th>State</th><th>Stage</th><th>File</th><th>Requested by</th><th>Queued</th><th>Duration</th></tr></thead>
              <tbody>
                {jobs.data.results.map((j) => (
                  <tr key={j.id} className="clickable" onClick={() => open(j)}>
                    <td><strong>{JOB_KIND_LABELS[j.kind] ?? j.kind}</strong></td>
                    <td><JobStateBadge state={j.state} /></td>
                    <td className="small">{j.stage || "—"}</td>
                    <td className="small">{j.source_file_name ?? "—"}</td>
                    <td className="small">{j.requested_by_email ?? "system"}</td>
                    <td className="subtle nowrap">{relativeTime(j.queued_at)}</td>
                    <td className="num">{j.elapsed_seconds !== null ? `${j.elapsed_seconds.toFixed(1)} s` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {selected && <JobDetail id={selected} onClose={() => { const n = new URLSearchParams(params); n.delete("job"); setParams(n); }} />}
    </div>
  );
}
