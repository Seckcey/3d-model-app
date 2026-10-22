import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { endSessions, listSessions } from "../api/auth";
import { api } from "../api/client";
import type { Me } from "../api/types";
import { errorMessage, useToast } from "../components/toast";
import { Badge, Button, Card, ErrorText, Field, Spinner } from "../components/ui";
import { formatDateTime } from "../lib/format";

function describeAgent(agent: string): string {
  const browser = /Edg\//.test(agent) ? "Edge" : /Chrome\//.test(agent) ? "Chrome" : /Firefox\//.test(agent) ? "Firefox" : /Safari\//.test(agent) ? "Safari" : "Browser";
  const os = /Windows/.test(agent) ? "Windows" : /Mac OS X/.test(agent) ? "macOS" : /Android/.test(agent) ? "Android" : /iPhone|iPad/.test(agent) ? "iOS" : /Linux/.test(agent) ? "Linux" : "";
  return os ? `${browser} on ${os}` : browser;
}

export function AccountPage({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(me.full_name);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: listSessions });

  async function saveName() {
    setSaving(true);
    setError(null);
    try {
      await api.patch("/api/v1/me/", { full_name: name });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast("Name saved");
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  async function end(ids: number[]) {
    try {
      await endSessions(ids);
      await queryClient.invalidateQueries({ queryKey: ["sessions"] });
      toast(ids.length > 1 ? "Other sessions signed out" : "Session signed out");
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  }

  const others = sessions.data?.filter((s) => !s.is_current) ?? [];
  return (
    <div className="stack" style={{ maxWidth: 900 }}>
      <div className="page-header">
        <div>
          <h1>Account</h1>
          <p>You sign in with a one-time code sent to {me.email}. There is no password to manage.</p>
        </div>
      </div>
      <Card title="Profile">
        <div className="form-grid">
          <Field label="Display name">{(id) => <input id={id} className="input" value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <Field label="Email">{(id) => <input id={id} className="input" value={me.email} readOnly />}</Field>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <Button variant="primary" busy={saving} onClick={saveName}>Save</Button>
          <ErrorText error={error} />
        </div>
      </Card>
      <Card
        flush
        title="Signed-in sessions"
        subtitle="Sessions last 7 days. Sign out anything you do not recognise."
        actions={others.length > 0 && <Button size="sm" variant="danger" onClick={() => end(others.map((s) => s.id))}>Sign out all others</Button>}
      >
        {sessions.isLoading ? <div className="card-body"><Spinner /></div> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Device</th><th>IP address</th><th>Signed in</th><th /></tr></thead>
              <tbody>
                {sessions.data?.map((s) => (
                  <tr key={s.id}>
                    <td>{describeAgent(s.user_agent)} {s.is_current && <Badge tone="ok">This device</Badge>}</td>
                    <td className="mono small">{s.ip}</td>
                    <td className="subtle">{formatDateTime(s.created_at)}</td>
                    <td className="right">{!s.is_current && <Button size="sm" onClick={() => end([s.id])}>Sign out</Button>}</td>
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
