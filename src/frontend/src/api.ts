export interface PlanParams {
  week_start: string; days?: number; grid?: number;
  beam_width?: number; levels?: number; n_workers?: number;
}
export interface PlanSummary {
  plan_id: string; week_start: string; status: string;
  energy_kwh: number | null; reduction_pct: number | null;
}
export interface Recommendation {
  status: string;
  setpoints: Record<string, number>;
  predicted_kpis: Record<string, number | null>;
}
export interface PlanDetail { plan_id: string; status: string; recommendation: Recommendation | null; }
export interface Progress { level?: number; evals?: number; best_score?: number; }

// ── Digital-twin hall topology (GET /api/topology) ──
export type Vec3 = [number, number, number];
export interface TopoCRAH { id: string; pos: Vec3; wall?: string; }
export interface TopoRackRow { id?: string; pos: Vec3; aisle: 'cold' | 'hot'; nracks: number; }
export interface TopoPlant { chiller: number; coolingTower: number; pumps: number; pos?: Vec3; }
export interface TopoLink { from: string; to: string; }
export interface Topology {
  hall: { name: string; size: Vec3 };
  crahs: TopoCRAH[];
  rack_rows: TopoRackRow[];
  plant: TopoPlant;
  links: TopoLink[];
}

let TOKEN = localStorage.getItem("token") || "";
export function setToken(t: string) { TOKEN = t; localStorage.setItem("token", t); }

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${TOKEN}`, ...(init.headers || {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(`${res.status}: ${(body as any).detail ?? "request failed"}`);
  }
  return res.json() as Promise<T>;
}

export const createPlan = (p: PlanParams) =>
  req<{ plan_id: string; status: string }>("/api/plans", { method: "POST", body: JSON.stringify(p) });
export const listPlans = () => req<PlanSummary[]>("/api/plans");
export const getPlan = (id: string) => req<PlanDetail>(`/api/plans/${id}`);
export const getProgress = (id: string) => req<Progress>(`/api/plans/${id}/progress`);
export const approvePlan = (id: string) => req(`/api/plans/${id}/approve`, { method: "POST" });
export const rejectPlan = (id: string) => req(`/api/plans/${id}/reject`, { method: "POST" });
export const editSetpoints = (id: string, sp: Record<string, number>) =>
  req(`/api/plans/${id}/setpoints`, { method: "PATCH", body: JSON.stringify(sp) });
export const getTopology = (hall = "1f 2a") =>
  req<Topology>(`/api/topology?hall=${encodeURIComponent(hall)}`);
