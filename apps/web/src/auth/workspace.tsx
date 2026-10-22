import { createContext, useContext, type ReactNode } from "react";

import type { Capability, Me, Membership } from "../api/types";

export interface Workspace {
  orgId: string;
  membership: Membership;
  me: Me;
  can: (capability: Capability) => boolean;
}

const WorkspaceContext = createContext<Workspace | null>(null);

export function WorkspaceProvider({ value, children }: { value: Workspace; children: ReactNode }) {
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace outside a workspace route");
  return value;
}

export function makeWorkspace(me: Me, orgId: string): Workspace | null {
  const membership = me.memberships.find((m) => m.organization.id === orgId);
  if (!membership) return null;
  return {
    orgId,
    membership,
    me,
    can: (capability) => membership.capabilities.includes(capability),
  };
}

export const LAST_WORKSPACE_KEY = "bpcad:last-workspace";

export function rememberWorkspace(orgId: string) {
  try {
    localStorage.setItem(LAST_WORKSPACE_KEY, orgId);
  } catch {
    /* storage may be unavailable; not important */
  }
}

export function preferredWorkspace(me: Me): string | null {
  let last: string | null = null;
  try {
    last = localStorage.getItem(LAST_WORKSPACE_KEY);
  } catch {
    last = null;
  }
  if (last && me.memberships.some((m) => m.organization.id === last)) return last;
  return me.memberships[0]?.organization.id ?? null;
}
