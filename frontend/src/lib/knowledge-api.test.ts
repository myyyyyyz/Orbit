import { beforeEach, describe, expect, it, vi } from "vitest";

import { createKnowledgeApi, KnowledgeApiError } from "./knowledge-api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Knowledge API", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("orbit_token", "token-7");
  });

  it("calls the complete run lifecycle with authentication", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ run_id: "r1" }));
    const api = createKnowledgeApi(fetcher);

    await api.planFolder({ path: "fixtures", use_agent: false });
    await api.approve("r1");
    await api.execute("r1");
    await api.evaluate("r1");
    await api.promote("r1");
    await api.rollback("r1");

    expect(fetcher.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([
      "/api/v1/knowledge/plan-folder",
      "/api/v1/knowledge/runs/r1/approve",
      "/api/v1/knowledge/runs/r1/execute",
      "/api/v1/knowledge/runs/r1/evaluate",
      "/api/v1/knowledge/runs/r1/promote",
      "/api/v1/knowledge/runs/r1/rollback",
    ]);
    for (const [, options] of fetcher.mock.calls) {
      expect(options.headers.Authorization).toBe("Bearer token-7");
    }
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      path: "fixtures",
      use_agent: false,
    });
  });

  it("encodes run identifiers before building URLs", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ run_id: "r/1" }));
    const api = createKnowledgeApi(fetcher);

    await api.getRun("r/1");
    await api.getPlan("r/1");

    expect(fetcher.mock.calls[0][0]).toMatch(/runs\/r%2F1$/);
    expect(fetcher.mock.calls[1][0]).toMatch(/runs\/r%2F1\/plan$/);
  });

  it("preserves stable backend error details", async () => {
    const api = createKnowledgeApi(
      vi.fn().mockResolvedValue(jsonResponse({ detail: "run_not_active" }, 409)),
    );

    await expect(api.rollback("r1")).rejects.toEqual(
      new KnowledgeApiError(409, "run_not_active"),
    );
  });

  it("lists runs and reads evaluation and active version", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ items: [], next_cursor: null }))
      .mockResolvedValueOnce(jsonResponse({ status: "passed" }))
      .mockResolvedValueOnce(jsonResponse({ legacy: true }));
    const api = createKnowledgeApi(fetcher);

    await api.listRuns();
    await api.getEvaluation("r1");
    await api.getActiveVersion();

    expect(fetcher.mock.calls.map(([url]) => {
      const parsed = new URL(url);
      return `${parsed.pathname}${parsed.search}`;
    })).toEqual([
      "/api/v1/knowledge/runs?limit=20",
      "/api/v1/knowledge/runs/r1/evaluation",
      "/api/v1/knowledge/active-version",
    ]);
  });

  it("uploads a local file with multipart data and freezes the import", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({ import_id: "i/1" }));
    const api = createKnowledgeApi(fetcher);
    const file = new File(["# doc"], "doc.md", { type: "text/markdown" });

    await api.createImport();
    await api.uploadImportFile("i/1", file, "folder/doc.md");
    await api.completeImport("i/1");

    expect(fetcher.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([
      "/api/v1/knowledge/imports",
      "/api/v1/knowledge/imports/i%2F1/files",
      "/api/v1/knowledge/imports/i%2F1/complete",
    ]);
    const upload = fetcher.mock.calls[1][1];
    expect(upload.body).toBeInstanceOf(FormData);
    expect(upload.headers["Content-Type"]).toBeUndefined();
  });
});
