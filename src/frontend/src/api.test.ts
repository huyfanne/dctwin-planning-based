import { describe, it, expect, vi, beforeEach } from "vitest";
import { listPlans, createPlan, approvePlan, setToken } from "./api";

beforeEach(() => {
  setToken("op-tok");
  vi.stubGlobal("fetch", vi.fn());
});

describe("api client", () => {
  it("createPlan posts with auth header", async () => {
    (fetch as any).mockResolvedValue({ ok: true, json: async () => ({ plan_id: "p1", status: "queued" }) });
    const res = await createPlan({ week_start: "2013-11-11" });
    expect(res.plan_id).toBe("p1");
    const [, opts] = (fetch as any).mock.calls[0];
    expect(opts.headers.Authorization).toBe("Bearer op-tok");
    expect(opts.method).toBe("POST");
  });

  it("listPlans GETs /api/plans", async () => {
    (fetch as any).mockResolvedValue({ ok: true, json: async () => [{ plan_id: "p1" }] });
    const res = await listPlans();
    expect(res[0].plan_id).toBe("p1");
  });

  it("throws on non-ok response", async () => {
    (fetch as any).mockResolvedValue({ ok: false, status: 403, json: async () => ({ detail: "nope" }) });
    await expect(approvePlan("p1")).rejects.toThrow();
  });
});
