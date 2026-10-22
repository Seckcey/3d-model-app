import { useState } from "react";

import { useAudit } from "../api/hooks";
import { useWorkspace } from "../auth/workspace";
import { Card, Empty, ErrorText, Spinner } from "../components/ui";
import { formatDateTime } from "../lib/format";

const FILTERS = [
  ["", "All events"],
  ["auth.", "Sign-ins"],
  ["file.", "Files"],
  ["artifact.", "Downloads"],
  ["revision.", "Revisions and export control"],
  ["invitation.", "Invitations"],
  ["member.", "Members"],
  ["project.", "Projects"],
  ["job.", "Jobs"],
  ["organization.", "Workspace settings"],
];

export function AuditPage() {
  const { orgId } = useWorkspace();
  const [action, setAction] = useState("");
  const audit = useAudit(orgId, action);
  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Audit log</h1>
          <p>Append-only record of uploads, downloads, approvals, export-control decisions and access changes.</p>
        </div>
        <div className="row">
          <select className="select" style={{ width: 240 }} value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filter">
            {FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <a className="btn" href={`/api/v1/organizations/${orgId}/audit/?export=csv${action ? `&action=${encodeURIComponent(action)}` : ""}`}>Export CSV</a>
        </div>
      </div>
      <Card flush>
        {audit.isLoading ? <div className="card-body"><Spinner /></div> : audit.error ? <div className="card-body"><ErrorText error={audit.error} /></div> : !audit.data?.length ? (
          <Empty title="No events" />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>When</th><th>Event</th><th>Who</th><th>Details</th><th>IP</th></tr></thead>
              <tbody>
                {audit.data.map((e) => (
                  <tr key={e.id}>
                    <td className="nowrap subtle">{formatDateTime(e.created_at)}</td>
                    <td className="mono">{e.action}</td>
                    <td className="small">{e.actor_email || "system"}</td>
                    <td className="small mono" style={{ maxWidth: 420, wordBreak: "break-word" }}>
                      {Object.keys(e.data).length ? JSON.stringify(e.data) : e.target_type ? `${e.target_type}` : "—"}
                    </td>
                    <td className="small mono">{e.ip ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
