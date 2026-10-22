import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { confirmLoginCode, requestLoginCode, resendLoginCode } from "../api/auth";
import { keys, useMe } from "../api/hooks";
import { CodeEntry } from "../components/CodeEntry";
import { Icon } from "../components/icons";
import { Alert, Button, ErrorText, PageLoading } from "../components/ui";

export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return "/";
  return next;
}

export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-shell">
      <div className="auth-panel">
        <div className="auth-card">
          <div className="row" style={{ fontWeight: 700, fontSize: "1.05rem" }}>
            <Icon.Logo width={34} height={34} /> Blueprint to CAD
          </div>
          {children}
        </div>
      </div>
      <div className="auth-art" aria-hidden>
        <h2>From customer print to a checked solid, without retyping the drawing.</h2>
        <ul>
          <li>Every modeled feature traces back to a drawing callout</li>
          <li>Nominal and mid-tolerance STEP, holes coloured by type</li>
          <li>Export-controlled drawings stay on your own server</li>
        </ul>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { data: me, isLoading } = useMe();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState("");
  const [step, setStep] = useState<"email" | "code">("email");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  if (isLoading) return <PageLoading />;
  if (me) {
    if (next.startsWith("/admin") && !me.is_staff) {
      return (
        <AuthShell>
          <Alert tone="warn" title="Administrator access required">
            You are signed in as {me.email}, which is not an administrator account.
          </Alert>
          <Button onClick={() => navigate("/")}>Go to my workspace</Button>
        </AuthShell>
      );
    }
    if (next.startsWith("/admin")) {
      window.location.assign(next);
      return <PageLoading />;
    }
    return <Navigate to={next} replace />;
  }

  async function onEmail(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await requestLoginCode(email.trim());
      setStep("code");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function onCode(code: string) {
    await confirmLoginCode(code);
    await queryClient.invalidateQueries({ queryKey: keys.me });
    if (next.startsWith("/admin")) window.location.assign(next);
    else navigate(next, { replace: true });
  }

  return (
    <AuthShell>
      {step === "email" ? (
        <form className="stack" onSubmit={onEmail}>
          <div>
            <h1>Sign in</h1>
            <p className="muted" style={{ marginTop: 6 }}>
              Enter your work email. We will send you a one-time code; there is no password.
            </p>
          </div>
          <div className="field">
            <label htmlFor="email">Email address</label>
            <input
              id="email"
              className="input"
              type="email"
              autoComplete="email"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@yourshop.com"
            />
          </div>
          <ErrorText error={error} />
          <Button variant="primary" size="lg" type="submit" busy={busy} disabled={!email.includes("@")}>
            Email me a code
          </Button>
          <p className="subtle">
            New here? Accounts are created from an invitation sent by your shop's workspace owner.
          </p>
        </form>
      ) : (
        <CodeEntry
          email={email}
          onSubmit={onCode}
          onResend={resendLoginCode}
          onChangeEmail={() => {
            setStep("email");
            setError(null);
          }}
        />
      )}
    </AuthShell>
  );
}
