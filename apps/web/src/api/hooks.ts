import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "./client";
import type {
  AuditEvent,
  BenchmarkData,
  Customer,
  Invitation,
  Job,
  Me,
  Member,
  Organization,
  Paginated,
  Part,
  Project,
  Revision,
  SearchResults,
} from "./types";

export const keys = {
  me: ["me"] as const,
  org: (orgId: string) => ["org", orgId] as const,
  projects: (orgId: string, params: Record<string, string>) => ["projects", orgId, params] as const,
  project: (id: string) => ["project", id] as const,
  parts: (projectId: string) => ["parts", projectId] as const,
  part: (id: string) => ["part", id] as const,
  revisions: (partId: string) => ["revisions", partId] as const,
  jobs: (params: Record<string, string>) => ["jobs", params] as const,
  job: (id: string) => ["job", id] as const,
  customers: (orgId: string) => ["customers", orgId] as const,
  members: (orgId: string) => ["members", orgId] as const,
  invitations: (orgId: string) => ["invitations", orgId] as const,
  benchmark: (orgId: string) => ["benchmark", orgId] as const,
  audit: (orgId: string, action: string) => ["audit", orgId, action] as const,
  search: (orgId: string, q: string) => ["search", orgId, q] as const,
};

/** The signed-in user, or null when signed out. */
export function useMe() {
  return useQuery<Me | null>({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        return await api.get<Me>("/api/v1/me/");
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return null;
        throw error;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useOrganization(orgId: string) {
  return useQuery({ queryKey: keys.org(orgId), queryFn: () => api.get<Organization>(`/api/v1/organizations/${orgId}/`) });
}

export function useProjects(orgId: string, params: Record<string, string>) {
  const query = new URLSearchParams({ organization: orgId, ...params }).toString();
  return useQuery({
    queryKey: keys.projects(orgId, params),
    queryFn: () => api.get<Paginated<Project>>(`/api/v1/projects/?${query}`),
  });
}

export function useProject(id: string) {
  return useQuery({ queryKey: keys.project(id), queryFn: () => api.get<Project>(`/api/v1/projects/${id}/`) });
}

export function useParts(projectId: string) {
  return useQuery({
    queryKey: keys.parts(projectId),
    queryFn: () => api.get<Paginated<Part>>(`/api/v1/parts/?project=${projectId}&page_size=200`),
  });
}

export function usePart(id: string) {
  return useQuery({ queryKey: keys.part(id), queryFn: () => api.get<Part>(`/api/v1/parts/${id}/`) });
}

const ACTIVE = new Set(["queued", "running", "waiting_input"]);

export function useRevisions(partId: string) {
  return useQuery({
    queryKey: keys.revisions(partId),
    queryFn: () => api.get<Revision[]>(`/api/v1/parts/${partId}/revisions/`),
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.source_files.some((f) => f.intake_status === "pending")) ? 2500 : false,
  });
}

export function useJobs(params: Record<string, string>, poll = true, enabled = true) {
  const query = new URLSearchParams({ page_size: "100", ...params }).toString();
  return useQuery({
    queryKey: keys.jobs(params),
    queryFn: () => api.get<Paginated<Job>>(`/api/v1/jobs/?${query}`),
    enabled,
    refetchInterval: (q) => (poll && q.state.data?.results.some((j) => ACTIVE.has(j.state)) ? 3000 : false),
  });
}

export function useJob(id: string | null) {
  return useQuery({
    queryKey: keys.job(id ?? "none"),
    queryFn: () => api.get<Job>(`/api/v1/jobs/${id}/`),
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.state) ? 2000 : false),
  });
}

export function useCustomers(orgId: string) {
  return useQuery({
    queryKey: keys.customers(orgId),
    queryFn: () => api.get<Customer[]>(`/api/v1/customers/?organization=${orgId}`),
  });
}

export function useMembers(orgId: string) {
  return useQuery({
    queryKey: keys.members(orgId),
    queryFn: () => api.get<Member[]>(`/api/v1/organizations/${orgId}/members/`),
  });
}

export function useInvitations(orgId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.invitations(orgId),
    queryFn: () => api.get<Invitation[]>(`/api/v1/organizations/${orgId}/invitations/`),
    enabled,
  });
}

export function useBenchmark(orgId: string) {
  return useQuery({
    queryKey: keys.benchmark(orgId),
    queryFn: () => api.get<BenchmarkData>(`/api/v1/organizations/${orgId}/benchmark/`),
    refetchInterval: (q) => (q.state.data?.latest && ACTIVE.has(q.state.data.latest.state) ? 2000 : false),
  });
}

export function useAudit(orgId: string, action: string) {
  return useQuery({
    queryKey: keys.audit(orgId, action),
    queryFn: () =>
      api.get<AuditEvent[]>(`/api/v1/organizations/${orgId}/audit/?limit=300${action ? `&action=${encodeURIComponent(action)}` : ""}`),
  });
}

export function useSearch(orgId: string, q: string) {
  return useQuery({
    queryKey: keys.search(orgId, q),
    queryFn: () => api.get<SearchResults>(`/api/v1/search/?organization=${orgId}&q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 2,
  });
}
