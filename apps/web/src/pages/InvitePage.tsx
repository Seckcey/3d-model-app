import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";

import {
  confirmLoginCode,
  logout,
  requestLoginCode,
  resendEmailCode,
  resendLoginCode,
  signupWithEmail,
  verifyEmailCode,
} from "../api/auth";
import { api } from "../api/client";
import { keys, useMe } from "../api/hooks";
import type { InvitationPreview } from "../api/types";
import { CodeEntry } from "../components/CodeEntry";
import { Alert, Button, ErrorText, PageLoading } from "../components/ui";
import { ROLE_LABELS, formatDate } from "../lib/format";
import { AuthShell } from "./LoginPage";

export function InvitePage() {
  const { token = "" } = useParams();
  const { data: me, isLoading: meLoading } = useMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [step, setStep] = useState<"start" | "code">("start");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const preview = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => api.get<InvitationPreview>(`/api/v1/invitations/${encodeURIComponent(token)}/`),
    retry: false,
  });

  if (meLoading || preview.isLoading) return <PageLoading />;
  if (preview.error || !preview.data) {
    return (
      <AuthShell>
        <h1>Invitation not found</h1>
        <Alert tone="warn">This invitation link is not valid. Ask the workspace owner to send a new one.</Alert>
      </AuthShell>
    );
  }
  const invitation = preview.data;
  const roles = invitation.roles.map((r) => ROLE_LABELS[r] ?? r).join(", ");

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{ organization: { id: string } }>(
        `/api/v1/invitations/${encodeURIComponent(token)}/accept/`,
      );
      await queryClient.invalidateQueries({ queryKey: keys.me });
      navigate(`/w/${result.organization.id}`, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      if (invitation.account_exists) await requestLoginCode(invitation.email);
      else await signupWithEmail(invitation.email);
      setStep("code");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function onCode(code: string) {
    if (invitation.account_exists) await confirmLoginCode(code);
    else await verifyEmailCode(code);
    await queryClient.invalidateQueries({ queryKey: keys.me });
    await accept();
  }

  const header = (
    <div>
      <h1>Join {invitation.organization.name}</h1>
      <p className="muted" style={{ marginTop: 6 }}>
        {invitation.invited_by ? `${invitation.invited_by} invited you` : "You were invited"} as {roles}.
      </p>
    </div>
  );

  if (invitation.status !== "pending") {
    const text = {
      accepted: "This invitation was already accepted. Sign in to continue.",
      revoked: "This invitation was withdrawn. Ask the workspace owner for a new one.",
      expired: `This invitation expired on ${formatDate(invitation.expires_at)}. Ask the workspace owner to resend it.`,
      pending: "",
    }[invitation.status];
    return (
      <AuthShell>
        {header}
        <Alert tone="warn">{text}</Alert>
        <Button onClick={() => navigate("/login")}>Go to sign in</Button>
      </AuthShell>
    );
  }

  if (me) {
    const matches = me.email.toLowerCase() === invitation.email.toLowerCase();
    return (
      <AuthShell>
        {header}
        {matches ? (
          <>
            <ErrorText error={error} />
            <Button variant="primary" size="lg" busy={busy} onClick={accept}>Accept invitation</Button>
          </>
        ) : (
          <>
            <Alert tone="warn" title="Different account">
              You are signed in as {me.email}, but this invitation is for {invitation.email}.
            </Alert>
            <Button
              onClick={async () => {
                await logout();
                queryClient.clear();
                setStep("start");
              }}
            >
              Sign out and continue
            </Button>
          </>
        )}
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      {step === "start" ? (
        <div className="stack">
          {header}
          <div className="field">
            <label>Email address</label>
            <input className="input" value={invitation.email} readOnly />
            <span className="help">You will sign in with a one-time code sent to this address. No password.</span>
          </div>
          <ErrorText error={error} />
          <Button variant="primary" size="lg" busy={busy} onClick={start}>Email me a code</Button>
        </div>
      ) : (
        <CodeEntry
          email={invitation.email}
          purpose={invitation.account_exists ? "sign in" : "confirm your address"}
          onSubmit={onCode}
          onResend={invitation.account_exists ? resendLoginCode : resendEmailCode}
        />
      )}
    </AuthShell>
  );
}
