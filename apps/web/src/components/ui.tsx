import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { Icon } from "./icons";

type Tone = "ok" | "warn" | "danger" | "info" | "neutral";

export function Button({
  variant = "default",
  size,
  busy,
  children,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "danger" | "ghost";
  size?: "sm" | "lg";
  busy?: boolean;
}) {
  const classes = ["btn", variant !== "default" ? `btn-${variant}` : "", size ? `btn-${size}` : "", className]
    .filter(Boolean)
    .join(" ");
  return (
    <button className={classes} disabled={busy || props.disabled} {...props}>
      {busy && <span className="spinner" style={{ width: 14, height: 14 }} />}
      {children}
    </button>
  );
}

export function Badge({ tone = "neutral", plain, children }: { tone?: Tone; plain?: boolean; children: ReactNode }) {
  return <span className={`badge ${tone === "neutral" ? "" : tone} ${plain ? "plain" : ""}`}>{children}</span>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row" role="status">
      <span className="spinner" />
      {label && <span className="muted">{label}</span>}
    </span>
  );
}

export function PageLoading() {
  return (
    <div className="center-page">
      <Spinner label="Loading…" />
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  );
}

export function Alert({ tone = "info", title, children }: { tone?: Exclude<Tone, "neutral">; title?: string; children?: ReactNode }) {
  const IconFor = tone === "ok" ? Icon.Check : tone === "info" ? Icon.Info : Icon.Alert;
  return (
    <div className={`alert ${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <IconFor className="icon" />
      <div>
        {title && <strong>{title}</strong>}
        {children}
      </div>
    </div>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return <Alert tone="danger">{message}</Alert>;
}

export function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: ReactNode;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {help && <span className="help">{help}</span>}
    </div>
  );
}

export function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("input, select, textarea, button")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="modal-header">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="muted small" style={{ marginTop: 4 }}>{subtitle}</p>}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">
            <Icon.X width={16} height={16} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

export function Card({ title, subtitle, actions, children, flush }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-header">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {flush ? children : <div className="card-body">{children}</div>}
    </section>
  );
}
