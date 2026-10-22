import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { useInvitations, useMembers } from "../api/hooks";
import type { Member, Role } from "../api/types";
import { useWorkspace } from "../auth/workspace";
import { errorMessage, useToast } from "../components/toast";
import { Badge, Button, Card, ErrorText, Field, Modal, Spinner } from "../components/ui";
import { ROLE_HELP, ROLE_LABELS, formatDate, relativeTime } from "../lib/format";

const ROLES: Role[] = ["owner", "engineer", "reviewer", "viewer"];

function RolePicker({ value, onChange }: { value: Role[]; onChange: (roles: Role[]) => void }) {
  return (
    <div className="stack-sm">
      {ROLES.map((role) => (
        <label className="checkbox" key={role}>
          <input
            type="checkbox"
            checked={value.includes(role)}
            onChange={(e) => onChange(e.target.checked ? [...value, role] : value.filter((r) => r !== role))}
          />
          <span>
            <strong>{ROLE_LABELS[role]}</strong>
            <span className="help subtle">{ROLE_HELP[role]}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

function EditRoles({ member, onClose }: { member: Member; onClose: () => void }) {
  const { orgId } = useWorkspace();
  const [roles, setRoles] = useState<Role[]>(member.roles);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();
  async function save() {
    setBusy(true);
    try {
      await api.patch(`/api/v1/organizations/${orgId}/members/${member.id}/`, { roles });
      await queryClient.invalidateQueries({ queryKey: ["members", orgId] });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title={`Roles for ${member.user.email}`} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!roles.length} onClick={save}>Save roles</Button></>}>
      <div className="stack">
        <RolePicker value={roles} onChange={setRoles} />
        <ErrorText error={error} />
      </div>
    </Modal>
  );
}

export function MembersPage() {
  const { orgId, can, me } = useWorkspace();
  const members = useMembers(orgId);
  const invitations = useInvitations(orgId, can("manage"));
  const queryClient = useQueryClient();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [roles, setRoles] = useState<Role[]>(["engineer"]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Member | null>(null);

  async function invite(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/v1/organizations/${orgId}/invitations/`, { email: email.trim(), roles });
      setEmail("");
      toast("Invitation sent");
      await queryClient.invalidateQueries({ queryKey: ["invitations", orgId] });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>, message: string) {
    try {
      await fn();
      toast(message);
      await queryClient.invalidateQueries({ queryKey: ["invitations", orgId] });
      await queryClient.invalidateQueries({ queryKey: ["members", orgId] });
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  }

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Members</h1>
          <p>People in this workspace and what they can do. Matching email domains never grant access.</p>
        </div>
      </div>

      <Card flush title="Members">
        {members.isLoading ? <div className="card-body"><Spinner /></div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Person</th><th>Roles</th><th>Last sign-in</th><th>Joined</th>{can("manage") && <th />}</tr></thead>
              <tbody>
                {members.data?.map((m) => (
                  <tr key={m.id}>
                    <td><strong>{m.user.full_name || m.user.email}</strong>{m.user.full_name && <div className="subtle">{m.user.email}</div>}</td>
                    <td><div className="chips">{m.roles.map((r) => <span className="chip" key={r}>{ROLE_LABELS[r]}</span>)}</div></td>
                    <td className="subtle">{relativeTime(m.user.last_login)}</td>
                    <td className="subtle">{formatDate(m.created_at)}</td>
                    {can("manage") && (
                      <td className="right nowrap">
                        <Button size="sm" onClick={() => setEditing(m)}>Roles</Button>{" "}
                        {m.user.id !== me.id && (
                          <Button size="sm" variant="danger" onClick={() => window.confirm(`Remove ${m.user.email} from this workspace? Access ends immediately.`) &&
                            act(() => api.del(`/api/v1/organizations/${orgId}/members/${m.id}/`), "Member removed")}>
                            Remove
                          </Button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {can("manage") && (
        <div className="grid-2">
          <Card title="Invite someone" subtitle="They receive a link and sign in with an emailed code.">
            <form className="stack" onSubmit={invite}>
              <Field label="Email address">
                {(id) => <input id={id} className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@shop.com" />}
              </Field>
              <div>
                <div className="label" style={{ marginBottom: 8 }}>Roles</div>
                <RolePicker value={roles} onChange={setRoles} />
              </div>
              <ErrorText error={error} />
              <Button variant="primary" type="submit" busy={busy} disabled={!email.includes("@") || !roles.length}>Send invitation</Button>
            </form>
          </Card>
          <Card flush title="Invitations">
            {!invitations.data?.length ? <div className="card-body subtle">No invitations yet.</div> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Email</th><th>Status</th><th>Expires</th><th /></tr></thead>
                  <tbody>
                    {invitations.data.map((inv) => (
                      <tr key={inv.id}>
                        <td>{inv.email}<div className="subtle">{inv.roles.map((r) => ROLE_LABELS[r]).join(", ")}</div></td>
                        <td>
                          <Badge tone={inv.status === "pending" ? "info" : inv.status === "accepted" ? "ok" : "neutral"}>{inv.status}</Badge>
                        </td>
                        <td className="subtle">{formatDate(inv.expires_at)}</td>
                        <td className="right nowrap">
                          {inv.status === "pending" && (
                            <>
                              <Button size="sm" onClick={() => act(() => api.post(`/api/v1/organizations/${orgId}/invitations/${inv.id}/resend/`), "Invitation resent (old link disabled)")}>Resend</Button>{" "}
                              <Button size="sm" variant="ghost" onClick={() => act(() => api.del(`/api/v1/organizations/${orgId}/invitations/${inv.id}/`), "Invitation revoked")}>Revoke</Button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}
      {editing && <EditRoles member={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}
