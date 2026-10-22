import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router";

import { logout } from "../api/auth";
import { useSearch } from "../api/hooks";
import type { Me } from "../api/types";
import { useWorkspace } from "../auth/workspace";
import { Icon } from "./icons";

function useClickOutside(onOutside: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onOutside();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onOutside]);
  return ref;
}

function initials(me: Me) {
  const source = me.full_name || me.email;
  return source
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");
}

export function UserMenu({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const ref = useClickOutside(() => setOpen(false));
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  async function signOut() {
    await logout();
    queryClient.clear();
    navigate("/login", { replace: true });
  }
  return (
    <div className="menu" ref={ref}>
      <button className="btn btn-ghost" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open}>
        <span className="avatar">{initials(me)}</span>
        <span className="small nowrap" style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>
          {me.full_name || me.email}
        </span>
      </button>
      {open && (
        <div className="menu-list" role="menu">
          <div className="subtle" style={{ padding: "6px 10px" }}>{me.email}</div>
          <Link to="/account" onClick={() => setOpen(false)}>Account and sessions</Link>
          {me.is_staff && <Link to="/system" onClick={() => setOpen(false)}>System status</Link>}
          {me.is_staff && <a href="/admin/">Django admin</a>}
          <div className="divider" />
          <button onClick={signOut}>Sign out</button>
        </div>
      )}
    </div>
  );
}

function WorkspaceSwitcher() {
  const { me, orgId } = useWorkspace();
  const navigate = useNavigate();
  if (me.memberships.length < 2) return null;
  return (
    <select
      className="select"
      style={{ width: 220 }}
      value={orgId}
      aria-label="Workspace"
      onChange={(e) => navigate(`/w/${e.target.value}`)}
    >
      {me.memberships.map((m) => (
        <option key={m.organization.id} value={m.organization.id}>{m.organization.name}</option>
      ))}
    </select>
  );
}

function SearchBox() {
  const { orgId } = useWorkspace();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const ref = useClickOutside(() => setOpen(false));
  const { data, isFetching } = useSearch(orgId, q);
  const hasResults = data && (data.parts.length || data.projects.length || data.customers.length);
  return (
    <div className="search-box" ref={ref}>
      <input
        className="input"
        type="search"
        placeholder="Search part numbers, projects, POs, customers…"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        aria-label="Search"
      />
      {open && q.trim().length >= 2 && (
        <div className="search-results">
          {isFetching && !data && <div className="group">Searching…</div>}
          {data && !hasResults && <div className="group">No matches. Have we made this before? Not under that name.</div>}
          {data && data.parts.length > 0 && <div className="group">Parts</div>}
          {data?.parts.map((p) => (
            <Link key={p.id} to={`/w/${orgId}/parts/${p.id}`} onClick={() => setOpen(false)}>
              <strong>{p.part_number}</strong>{" "}
              <span className="subtle">
                {p.description} · {p.project_name}
                {p.latest_revision ? ` · rev ${p.latest_revision.drawing_revision || "?"}` : ""}
              </span>
            </Link>
          ))}
          {data && data.projects.length > 0 && <div className="group">Projects</div>}
          {data?.projects.map((p) => (
            <Link key={p.id} to={`/w/${orgId}/projects/${p.id}`} onClick={() => setOpen(false)}>
              <strong>{p.name}</strong> <span className="subtle">{p.reference} {p.customer_name ?? ""}</span>
            </Link>
          ))}
          {data && data.customers.length > 0 && <div className="group">Customers</div>}
          {data?.customers.map((c) => (
            <Link key={c.id} to={`/w/${orgId}?customer=${c.id}`} onClick={() => setOpen(false)}>{c.name}</Link>
          ))}
        </div>
      )}
    </div>
  );
}

export function WorkspaceLayout({ children }: { children: ReactNode }) {
  const { orgId, membership, me, can } = useWorkspace();
  const base = `/w/${orgId}`;
  const link = (to: string, label: string, IconCmp: (p: object) => ReactNode, end = false) => (
    <NavLink to={to} end={end} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
      <IconCmp />
      {label}
    </NavLink>
  );
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Icon.Logo width={30} height={30} />
          <div>
            Blueprint to CAD
            <small>{membership.organization.name}</small>
          </div>
        </div>
        <div className="nav-section">Work</div>
        {link(base, "Projects", Icon.Dashboard, true)}
        {link(`${base}/jobs`, "Jobs", Icon.Jobs)}
        {link(`${base}/benchmark`, "Geometry benchmark", Icon.Cube)}
        <div className="nav-section">Workspace</div>
        {link(`${base}/members`, "Members", Icon.Users)}
        {link(`${base}/settings`, "Settings", Icon.Settings)}
        {can("manage") && link(`${base}/audit`, "Audit log", Icon.Audit)}
        {me.is_staff && (
          <>
            <div className="nav-section">Administration</div>
            {link("/system", "System status", Icon.Server)}
          </>
        )}
        <div className="sidebar-footer">Roles: {membership.roles.join(", ")}</div>
      </aside>
      <div className="main">
        <header className="topbar">
          <SearchBox />
          <div className="spacer" />
          <WorkspaceSwitcher />
          <UserMenu me={me} />
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}

export function PlainLayout({ me, children }: { me: Me; children: ReactNode }) {
  return (
    <div className="main" style={{ minHeight: "100vh" }}>
      <header className="topbar">
        <Link to="/" className="row" style={{ color: "inherit", fontWeight: 700 }}>
          <Icon.Logo width={28} height={28} /> Blueprint to CAD
        </Link>
        <div className="spacer" />
        <UserMenu me={me} />
      </header>
      <main className="content" style={{ margin: "0 auto" }}>{children}</main>
    </div>
  );
}
