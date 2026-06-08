import { describe, it, expect, vi, beforeEach } from "vitest";
import { listPlans, createPlan, approvePlan, setToken, getToken, clearToken, verifyToken } from "./api";

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

describe("token helpers", () => {
  it("getToken / setToken / clearToken round-trip via localStorage", () => {
    setToken("abc");
    expect(getToken()).toBe("abc");
    expect(localStorage.getItem("token")).toBe("abc");
    clearToken();
    expect(getToken()).toBe("");
    expect(localStorage.getItem("token")).toBeNull();
  });

  it("verifyToken probes /api/plans with the given token and returns true on 200, without mutating the stored token", async () => {
    setToken("orig");
    (fetch as any).mockResolvedValue({ ok: true, json: async () => [] });
    const ok = await verifyToken("probe-tok");
    expect(ok).toBe(true);
    const [url, opts] = (fetch as any).mock.calls[0];
    expect(url).toBe("/api/plans");
    expect(opts.headers.Authorization).toBe("Bearer probe-tok");
    expect(getToken()).toBe("orig");          // verifyToken must NOT store the probed token
  });

  it("verifyToken returns false on 401", async () => {
    (fetch as any).mockResolvedValue({ ok: false, status: 401, json: async () => ({}) });
    expect(await verifyToken("bad")).toBe(false);
  });
});
