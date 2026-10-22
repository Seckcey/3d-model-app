/** django-allauth headless (browser client): email + one-time code. */

import { ApiError, request } from "./client";
import type { UserSession } from "./types";

const BASE = "/_allauth/browser/v1";

interface Flow {
  id: string;
  is_pending?: boolean;
}

interface AuthPayload {
  status: number;
  data?: { flows?: Flow[]; user?: { email: string } };
  meta?: { is_authenticated?: boolean };
}

function pending(payload: AuthPayload, flowId: string): boolean {
  return Boolean(payload.data?.flows?.some((flow) => flow.id === flowId && flow.is_pending));
}

export const CODE_ERRORS: Record<string, string> = {
  too_many_login_attempts: "A code was sent to this address in the last minute. Check your inbox, or wait and try again.",
  incorrect_code: "That code is not right. Check the email and try again.",
};

function friendly(error: unknown): never {
  if (error instanceof ApiError) {
    if (error.code && CODE_ERRORS[error.code]) {
      throw new ApiError(error.status, CODE_ERRORS[error.code], error.data, error.code);
    }
    if (error.status === 409) {
      throw new ApiError(409, "This code has expired or was used up. Request a new code.", error.data, "flow_expired");
    }
  }
  throw error;
}

/** Ask for a sign-in code. Unknown addresses get the same response (no account enumeration). */
export async function requestLoginCode(email: string): Promise<void> {
  try {
    const { data } = await request<AuthPayload>("POST", `${BASE}/auth/code/request`, { email }, { okStatuses: [401] });
    if (!pending(data, "login_by_code")) throw new ApiError(400, "Could not start sign-in. Try again.", data);
  } catch (error) {
    friendly(error);
  }
}

export async function confirmLoginCode(code: string): Promise<void> {
  try {
    await request<AuthPayload>("POST", `${BASE}/auth/code/confirm`, { code: code.trim() });
  } catch (error) {
    friendly(error);
  }
}

export async function resendLoginCode(): Promise<void> {
  try {
    await request("POST", `${BASE}/auth/code/resend`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 429) {
      throw new ApiError(429, "Wait a minute before asking for another code.", error.data);
    }
    friendly(error);
  }
}

/** Invitation signup: creates the account and emails a verification code. */
export async function signupWithEmail(email: string): Promise<void> {
  try {
    const { data } = await request<AuthPayload>("POST", `${BASE}/auth/signup`, { email }, { okStatuses: [401] });
    if (!pending(data, "verify_email")) throw new ApiError(400, "Could not start signup. Try again.", data);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      throw new ApiError(403, "Accounts are created by invitation. Open the link from your invitation email.", error.data);
    }
    friendly(error);
  }
}

export async function verifyEmailCode(code: string): Promise<void> {
  try {
    await request("POST", `${BASE}/auth/email/verify`, { key: code.trim() });
  } catch (error) {
    friendly(error);
  }
}

export async function resendEmailCode(): Promise<void> {
  try {
    await request("POST", `${BASE}/auth/email/verify/resend`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 429) {
      throw new ApiError(429, "Wait a minute before asking for another code.", error.data);
    }
    friendly(error);
  }
}

export async function logout(): Promise<void> {
  await request("DELETE", `${BASE}/auth/session`, undefined, { okStatuses: [401] });
}

export async function listSessions(): Promise<UserSession[]> {
  const { data } = await request<{ data: UserSession[] }>("GET", `${BASE}/auth/sessions`);
  return data.data;
}

export async function endSessions(ids: number[]): Promise<void> {
  await request("DELETE", `${BASE}/auth/sessions`, { sessions: ids });
}
