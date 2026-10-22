import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, Outlet, Route, Routes, useLocation, useNavigate, useParams } from "react-router";

import { api } from "./api/client";
import { useMe } from "./api/hooks";
import type { Me, Organization } from "./api/types";
import { WorkspaceProvider, makeWorkspace, preferredWorkspace, rememberWorkspace } from "./auth/workspace";
import { PlainLayout, WorkspaceLayout } from "./components/Layout";
import { Alert, Button, Card, ErrorText, Field, PageLoading } from "./components/ui";
import { AccountPage } from "./pages/AccountPage";
import { AuditPage } from "./pages/AuditPage";
import { BenchmarkPage } from "./pages/BenchmarkPage";
import { DashboardPage } from "./pages/DashboardPage";
import { InvitePage } from "./pages/InvitePage";
import { JobsPage } from "./pages/JobsPage";
import { LoginPage } from "./pages/LoginPage";
import { MembersPage } from "./pages/MembersPage";
import { PartPage } from "./pages/PartPage";
import { ProjectPage } from "./pages/ProjectPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SystemPage } from "./pages/SystemPage";

const MeContext = createContext<Me | null>(null);

function useSignedInMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useSignedInMe outside RequireAuth");
  return me;
}

function RequireAuth() {
  const { data: me, isLoading, error } = useMe();
  const location = useLocation();
  if (isLoading) return <PageLoading />;
  if (error) return <div className="content"><ErrorText error={error} /></div>;
  if (!me) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return (
    <MeContext.Provider value={me}>
      <Outlet />
    </MeContext.Provider>
  );
}

function WorkspaceRoute() {
  const me = useSignedInMe();
  const { orgId = "" } = useParams();
  const workspace = makeWorkspace(me, orgId);
  useEffect(() => {
    if (workspace) rememberWorkspace(orgId);
  }, [workspace, orgId]);
  if (!workspace) {
    return (
      <PlainLayout me={me}>
        <Alert tone="warn" title="Workspace not available">
          You are not a member of this workspace, or it no longer exists.
        </Alert>
      </PlainLayout>
    );
  }
  return (
    <WorkspaceProvider value={workspace}>
      <WorkspaceLayout>
        <Outlet />
      </WorkspaceLayout>
    </WorkspaceProvider>
  );
}

/** Account and system pages keep the workspace sidebar when the user has one. */
function WithWorkspaceChrome({ children }: { children: ReactNode }) {
  const me = useSignedInMe();
  const orgId = preferredWorkspace(me);
  const workspace = orgId ? makeWorkspace(me, orgId) : null;
  if (!workspace) return <PlainLayout me={me}>{children}</PlainLayout>;
  return (
    <WorkspaceProvider value={workspace}>
      <WorkspaceLayout>{children}</WorkspaceLayout>
    </WorkspaceProvider>
  );
}

function NoWorkspace() {
  const me = useSignedInMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const canCreate = me.signup_mode === "open" || me.is_staff;
  async function create() {
    setBusy(true);
    setError(null);
    try {
      const org = await api.post<Organization>("/api/v1/organizations/", { name });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      navigate(`/w/${org.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <PlainLayout me={me}>
      <div style={{ maxWidth: 560 }} className="stack">
        <h1>Welcome, {me.full_name || me.email}</h1>
        {canCreate ? (
          <Card title="Create your shop's workspace" subtitle="Everything you upload stays inside this workspace. You can invite your team next.">
            <div className="stack">
              <Field label="Shop name">{(id) => <input id={id} className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ralls Precision" />}</Field>
              <ErrorText error={error} />
              <Button variant="primary" busy={busy} disabled={name.trim().length < 2} onClick={create}>Create workspace</Button>
            </div>
          </Card>
        ) : (
          <Alert tone="info" title="You are not in a workspace yet">
            Ask the owner of your shop's workspace to invite {me.email}. The invitation email contains a link that adds you.
          </Alert>
        )}
      </div>
    </PlainLayout>
  );
}

function Home() {
  const me = useSignedInMe();
  const orgId = preferredWorkspace(me);
  if (orgId) return <Navigate to={`/w/${orgId}`} replace />;
  return <NoWorkspace />;
}

function AccountRoute() {
  const me = useSignedInMe();
  return <WithWorkspaceChrome><AccountPage me={me} /></WithWorkspaceChrome>;
}

function SystemRoute() {
  const me = useSignedInMe();
  return <WithWorkspaceChrome><SystemPage me={me} /></WithWorkspaceChrome>;
}

function NotFound() {
  return (
    <div className="center-page">
      <div className="stack" style={{ textAlign: "center" }}>
        <h1>Page not found</h1>
        <a href="/">Go to your workspace</a>
      </div>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/invite/:token" element={<InvitePage />} />
      <Route element={<RequireAuth />}>
        <Route index element={<Home />} />
        <Route path="/account" element={<AccountRoute />} />
        <Route path="/system" element={<SystemRoute />} />
        <Route path="/w/:orgId" element={<WorkspaceRoute />}>
          <Route index element={<DashboardPage />} />
          <Route path="projects/:projectId" element={<ProjectPage />} />
          <Route path="parts/:partId" element={<PartPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="benchmark" element={<BenchmarkPage />} />
          <Route path="members" element={<MembersPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="audit" element={<AuditPage />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
