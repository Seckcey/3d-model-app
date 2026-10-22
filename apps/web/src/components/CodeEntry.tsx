import { useEffect, useState, type FormEvent } from "react";

import { Button, ErrorText } from "./ui";

const RESEND_SECONDS = 60;

/** Six-digit code entry with auto-submit and a visible resend countdown. */
export function CodeEntry({
  email,
  onSubmit,
  onResend,
  onChangeEmail,
  purpose = "sign in",
}: {
  email: string;
  onSubmit: (code: string) => Promise<void>;
  onResend: () => Promise<void>;
  onChangeEmail?: () => void;
  purpose?: string;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(RESEND_SECONDS);
  const [resent, setResent] = useState(false);

  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  async function submit(value: string) {
    if (busy || value.length !== 6) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(value);
    } catch (err) {
      setError(err);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    try {
      await onResend();
      setResent(true);
      setWait(RESEND_SECONDS);
    } catch (err) {
      setError(err);
    }
  }

  function onForm(event: FormEvent) {
    event.preventDefault();
    void submit(code);
  }

  return (
    <form className="stack" onSubmit={onForm}>
      <div>
        <h1>Check your email</h1>
        <p className="muted" style={{ marginTop: 6 }}>
          We sent a 6-digit code to <strong>{email}</strong> to {purpose}. It expires in 10 minutes and works once.
        </p>
      </div>
      <input
        className="input code-input"
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]{6}"
        maxLength={6}
        value={code}
        aria-label="6-digit code"
        autoFocus
        onChange={(e) => {
          const digits = e.target.value.replace(/\D/g, "").slice(0, 6);
          setCode(digits);
          if (digits.length === 6) void submit(digits);
        }}
      />
      <ErrorText error={error} />
      {resent && !error && <p className="subtle">A new code is on its way. The previous code no longer works.</p>}
      <Button variant="primary" size="lg" type="submit" busy={busy} disabled={code.length !== 6}>
        Continue
      </Button>
      <div className="row-between small">
        <button type="button" className="btn btn-ghost btn-sm" onClick={resend} disabled={wait > 0}>
          {wait > 0 ? `Resend code in ${wait}s` : "Resend code"}
        </button>
        {onChangeEmail && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onChangeEmail}>
            Use a different email
          </button>
        )}
      </div>
    </form>
  );
}
