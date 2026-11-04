// API client: URLs, query strings and error handling
import { describe, expect, it, vi } from "vitest";

import { ApiError, buildUrl, request } from "@/lib/api/client";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("api client", () => {
  it("builds URLs and drops empty query values", () => {
    const url = buildUrl("/datasets/x/companies", { page: 2, q: "", split: undefined, descending: true }, "http://api/v1");
    expect(url).toBe("http://api/v1/datasets/x/companies?page=2&descending=true");
  });

  it("returns parsed JSON on success", async () => {
    const fetchImpl = vi.fn(async () => json(200, { status: "ok" }));
    await expect(request("GET", "/health", { fetchImpl })).resolves.toEqual({ status: "ok" });
  });

  it("maps backend error bodies to ApiError", async () => {
    const fetchImpl = vi.fn(async () => json(404, { error: { code: "not_found", message: "dataset 'x' not found", details: {} } }));
    const error = await request("GET", "/datasets/x", { fetchImpl }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).code).toBe("not_found");
    expect((error as ApiError).message).toContain("not found");
  });

  it("maps FastAPI validation errors", async () => {
    const fetchImpl = vi.fn(async () => json(422, { detail: [{ loc: ["query", "page"], msg: "must be >= 1" }] }));
    const error = (await request("GET", "/x", { fetchImpl }).catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("validation_error");
    expect(error.message).toBe("page: must be >= 1");
  });

  it("reports an unreachable backend", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const error = (await request("GET", "/health", { fetchImpl }).catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("network_error");
  });

  it("sends JSON bodies for POST", async () => {
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => json(202, { id: "job" }));
    await request("POST", "/datasets", { body: { dataset_id: "d" }, fetchImpl });
    const init = fetchImpl.mock.calls[0]![1]!;
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"dataset_id":"d"}');
  });
});
