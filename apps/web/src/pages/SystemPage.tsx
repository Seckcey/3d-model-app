import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { api } from "../api/client";
import type { AdminUser, Health, Me } from "../api/types";
import { errorMessage, useToast } from "../components/toast";
import { Alert, Badge, Button, Card, ErrorText, PageLoading } from "../components/ui";
import { formatBytes, formatDateTime, relativeTime } from "../lib/format";

function Status({ ok }: { ok: boolean | undefined }) {
  return ok ? <Badge tone="ok">OK</Badge> : <Badge tone="danger">Attention</Badge>;
}

function Tile({ title, ok, children }: { title: string; ok?: boolean; children: ReactNode }) {
  return (
    <div className="card stat">
      <div className="row-between"><span className="label">{title}</span>{ok !== undefined && <Status ok={ok} />}</div>
      <div style={{ marginTop: 8 }}>{children}</div>
    </div>
  );
}

export function SystemPage({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get<Health>("/api/v1/system/health/"), refetchInterval: 15_000, enabled: me.is_staff });
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api.get<AdminUser[]>("/api/v1/admin/users/"), enabled: me.is_staff });

  if (!me.is_staff) return <Alert tone="warn">Administrators only.</Alert>;
  if (health.isLoading) return <PageLoading />;
  if (health.error || !health.data) return <ErrorText error={health.error} />;
  const h = health.data;

  async function userAction(user: AdminUser, operation: string) {
    if (operation === "deactivate" && !window.confirm(`Deactivate ${user.email}? They are signed out everywhere immediately.`)) return;
    try {
      const result = await api.post<{ sessions_ended: number }>(`/api/v1/admin/users/${user.id}/${operation}/`);
      toast(`${user.email}: ${operation.replace("-", " ")} (${result.sessions_ended} sessions ended)`);
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  }

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>System status</h1>
          <p>Version {h.version.app} ({h.version.git_sha}) · checked {relativeTime(h.checked_at)} · refreshes every 15 s</p>
        </div>
        <a className="btn" href="/admin/">Django admin</a>
      </div>
      {h.alerts.map((a) => <Alert key={a.code} tone="warn" title={a.title}>{a.message}</Alert>)}
      {h.email.delivery === "outbox" && (
        <Alert tone="info" title="Email is not configured">
          Sign-in codes and invitations are written to the server outbox. Read them on the VM with
          <code> sudo bpcad outbox</code>, or set SMTP settings in <code>/opt/blueprint-cad/.env</code> and run <code>sudo bpcad update</code>.
        </Alert>
      )}
      <div className="grid-3">
        <Tile title="Database" ok={h.database.ok}>{h.database.engine ?? h.database.error}</Tile>
        <Tile title="Cache / broker" ok={h.cache.ok}>{h.queues.available ? "Redis reachable" : h.queues.error ?? "Unavailable"}</Tile>
        <Tile title="Workers" ok={h.workers?.ok}>
          {h.workers?.workers.length ? h.workers.workers.map((w) => (
            <div key={w.name} className="small"><span className="mono">{w.name.split("@")[0]}</span> → {w.queues.join(", ")}</div>
          )) : <span className="muted">No workers answered</span>}
          {h.workers?.missing_queues?.length ? <div className="small" style={{ color: "var(--danger)" }}>Nobody consuming: {h.workers.missing_queues.join(", ")}</div> : null}
        </Tile>
        <Tile title="Queues">
          {h.queues.depths ? Object.entries(h.queues.depths).map(([q, n]) => (
            <div key={q} className="small row-between"><span>{q}</span><span className="mono">{n}</span></div>
          )) : "—"}
          <div className="subtle">Oldest queued job: {h.jobs.oldest_queued_minutes} min</div>
        </Tile>
        <Tile title="Disk" ok={h.disk.ok}>
          <div className="value" style={{ fontSize: "1.3rem" }}>{h.disk.used_percent ?? "—"}%</div>
          <div className="subtle">{h.disk.free_gb} GB free of {h.disk.total_gb} GB · alert at {h.disk.alert_percent}%</div>
        </Tile>
        <Tile title="Backups" ok={h.backups.ok}>
          {h.backups.last_backup ? (
            <>
              <div className="small">Last: {formatDateTime(h.backups.last_backup.at)} ({h.backups.last_backup_age_hours} h ago)</div>
              {h.backups.last_backup.size_bytes ? <div className="subtle">{formatBytes(h.backups.last_backup.size_bytes)}</div> : null}
            </>
          ) : <div className="small">No backup recorded yet</div>}
          <div className="subtle">Restore drill: {h.backups.last_restore_drill ? `${h.backups.last_restore_drill.status} ${relativeTime(h.backups.last_restore_drill.at)}` : "never"}</div>
        </Tile>
        <Tile title="Jobs (24 h)">
          {Object.keys(h.jobs.last_24h).length ? Object.entries(h.jobs.last_24h).map(([state, n]) => (
            <div key={state} className="small row-between"><span>{state}</span><span className="mono">{n}</span></div>
          )) : <span className="muted">No jobs</span>}
        </Tile>
        <Tile title="Email">{h.email.delivery === "smtp" ? "SMTP relay" : "Local outbox (not sent)"}</Tile>
        <Tile title="Sign-up mode">{h.signup_mode === "invite_only" ? "Invitation only" : "Open"}</Tile>
      </div>

      <Card flush title="Users" subtitle="Deactivating a user signs them out everywhere immediately.">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>User</th><th>Workspaces</th><th>Last sign-in</th><th>Status</th><th /></tr></thead>
            <tbody>
              {users.data?.map((u) => (
                <tr key={u.id}>
                  <td><strong>{u.email}</strong>{u.is_staff && <> <Badge tone="info">admin</Badge></>}<div className="subtle">{u.full_name}</div></td>
                  <td className="small">{u.organizations.join(", ") || "—"}</td>
                  <td className="subtle">{relativeTime(u.last_login)}</td>
                  <td>{u.is_active ? <Badge tone="ok">Active</Badge> : <Badge tone="danger">Deactivated</Badge>}</td>
                  <td className="right nowrap">
                    <Button size="sm" onClick={() => userAction(u, "end-sessions")}>End sessions</Button>{" "}
                    {u.id !== me.id && (u.is_active
                      ? <Button size="sm" variant="danger" onClick={() => userAction(u, "deactivate")}>Deactivate</Button>
                      : <Button size="sm" onClick={() => userAction(u, "reactivate")}>Reactivate</Button>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
