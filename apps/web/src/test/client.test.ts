import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, messageFrom, request } from "../api/client";
import { formatValue, relativeTime } from "../lib/format";
import { safeNext } from "../pages/LoginPage";
import { filenamePreview } from "../pages/SettingsPage";

describe("messageFrom", () => {
  it("reads allauth errors", () => {
    const result = messageFrom({ status: 400, errors: [{ message: "Incorrect code.", code: "incorrect_code" }] }, 400);
    expect(result).toEqual({ message: "Incorrect code.", code: "incorrect_code" });
  });

  it("reads DRF field errors and the upload code", () => {
    const result = messageFrom({ file: ["The file is larger than the 25 MB limit."], code: ["too_large"] }, 400);
    expect(result.message).toBe("The file is larger than the 25 MB limit.");
    expect(result.code).toBe("too_large");
  });

  it("labels other fields", () => {
    expect(messageFrom({ part_number: ["This part is already in the project."] }, 400).message).toBe(
      "part number: This part is already in the project.",
    );
  });

  it("falls back by status", () => {
    expect(messageFrom(null, 404).message).toBe("Not found.");
    expect(messageFrom(null, 502).message).toMatch(/server/);
  });
});

describe("request", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.cookie = "bpcad_csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("sends the CSRF token on writes", async () => {
    document.cookie = "bpcad_csrftoken=tok123";
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await request("POST", "/api/v1/projects/", { name: "x" }, { idempotencyKey: "k1" });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["X-CSRFToken"]).toBe("tok123");
    expect(init.headers["Idempotency-Key"]).toBe("k1");
    expect(init.credentials).toBe("same-origin");
  });

  it("throws ApiError with a readable message", async () => {
    const body = JSON.stringify({ detail: "Only engineers can change projects, parts or drawings." });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response(body, { status: 403 })));
    await expect(request("GET", "/api/v1/x/")).rejects.toMatchObject({
      status: 403,
      message: "Only engineers can change projects, parts or drawings.",
    });
    await expect(request("GET", "/api/v1/x/")).rejects.toBeInstanceOf(ApiError);
  });

  it("accepts statuses the caller expects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 401 }), { status: 401 })));
    const result = await request("GET", "/_allauth/browser/v1/auth/session", undefined, { okStatuses: [401] });
    expect(result.status).toBe(401);
  });
});

describe("helpers", () => {
  it("only follows same-site next links", () => {
    expect(safeNext("/w/abc")).toBe("/w/abc");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });

  it("previews file names with units stamped", () => {
    expect(filenamePreview("{part}_REV{rev}_{kind}", "in")).toBe("BP-1001_REVC_NOMINAL-IN.step");
    expect(filenamePreview("{customer} {part}/{rev}", "mm")).toBe("Acme_BP-1001_C_NOMINAL-MM.step");
  });

  it("formats values", () => {
    expect(formatValue([1.5, 2], "in")).toBe("(1.5, 2)");
    expect(formatValue(0.25025, "in")).toBe("0.25025 in");
    expect(formatValue(null)).toBe("—");
    expect(relativeTime(new Date(Date.now() - 5 * 60_000).toISOString())).toBe("5 min ago");
  });
});
