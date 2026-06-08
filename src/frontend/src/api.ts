export interface PlanParams {
  week_start: string; days?: number; grid?: number;
  beam_width?: number; levels?: number; n_workers?: number;
  time_block?: boolean;
}
export interface PlanSummary {
  plan_id: string; week_start: string; status: string;
  energy_kwh: number | null; reduction_pct: number | null;
  realized_energy_kwh: number | null;
}
export interface ScheduleBlock { label: string; start_hour: number; end_hour: number; setpoints: Record<string, number>; }
export interface Recommendation {
  status: string;
  setpoints: Record<string, number>;
  predicted_kpis: Record<string, number | null>;
  energy_scope?: string;
  baseline?: {
    source: string;
    energy_kwh: number | null;
    setpoints: Record<string, number> | null;
    kpis?: Record<string, number | null>;
  } | null;
  robust?: {
    robust_feasible: boolean;
    cvar_energy_kwh: number;
    confidence_bands: Record<string, { p50: number; p90: number; max: number }>;
    n_scenarios: number;
    calibration_version: string | null;
  } | null;
  schedule?: { cadence: string; blocks: ScheduleBlock[] } | null;
}
export interface RealizedKpis {
  total_hvac_energy_kwh?: number;
  inlet_temp_max_c?: number;
  pue_mean?: number;
  inlet_violation_steps?: number;
}
export interface PlanDetail { plan_id: string; status: string; recommendation: Recommendation | null; realized?: RealizedKpis | null; }
export interface Progress { level?: number; evals?: number; best_score?: number; error?: string; }

// ── Digital-twin hall topology (GET /api/topology) ──
export type Vec3 = [number, number, number];
export interface TopoCRAH { id: string; pos: Vec3; wall?: string; }
export interface TopoRackRow { id?: string; pos: Vec3; aisle: 'cold' | 'hot'; nracks: number; }
export interface TopoPlant { chiller: number; coolingTower: number; pumps: number; pos?: Vec3; }
export interface TopoLink { from: string; to: string; }
export interface HallInfra {
  acuTotal: number;        // air-handling units serving the hall (IDF air loops)
  acuControlled: number;   // agent-controlled ACUs (prototxt); 0 = scheduled
  iteObjects: number;      // ElectricEquipment:ITE objects
  iteUnits: number;        // total modeled ITE units
  itPowerKw: number;       // total IT power (kW)
  hvac: string;            // one-line HVAC summary
}
export interface BuildingHall {
  code: string;            // e.g. "Data Hall 1F 2A"
  level: string;           // "GF" | "1F" | "2F" | "—"
  origin: Vec3;            // world min corner [x,y,z] (m)
  size: Vec3;              // [width_x, depth_y, height_z] (m)
  z0: number;              // floor height in the stack (m)
  controlled: boolean;     // true for the operator-controlled hall
  ite: number;             // ITE object count (back-compat)
  infra: HallInfra;
  crahs: TopoCRAH[];       // this hall's ACU layout
  rackRows: TopoRackRow[]; // this hall's rack layout
}
export interface Building {
  footprint: [number, number];  // [width_x, depth_y] (m)
  height: number;               // top of the stack (m)
  plant: TopoPlant;             // shared cooling plant (chiller/tower/pumps)
  halls: BuildingHall[];        // stacked ground -> top
}
export interface Topology {
  hall: { name: string; size: Vec3 };
  crahs: TopoCRAH[];
  rack_rows: TopoRackRow[];
  plant: TopoPlant;
  links: TopoLink[];
  building: Building;
}

let TOKEN = localStorage.getItem("token") || "";
export function setToken(t: string) { TOKEN = t; localStorage.setItem("token", t); }
export function getToken(): string { return TOKEN; }
export function clearToken(): void { TOKEN = ""; localStorage.removeItem("token"); }

// Validate a token WITHOUT mutating the stored TOKEN: raw GET /api/plans (operator-min;
// an expert token satisfies it too). 200 -> valid, 401/403 -> invalid. May throw on a
// network failure (caller treats that as "backend unreachable").
export async function verifyToken(token: string): Promise<boolean> {
  const res = await fetch("/api/plans", { headers: { Authorization: `Bearer ${token}` } });
  return res.ok;
}

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
export const planStreamUrl = (id: string) => `/api/plans/${id}/stream?token=${encodeURIComponent(TOKEN)}`;
export const approvePlan = (id: string) => req(`/api/plans/${id}/approve`, { method: "POST" });
export const rejectPlan = (id: string) => req(`/api/plans/${id}/reject`, { method: "POST" });
export const editSetpoints = (id: string, sp: Record<string, number>) =>
  req(`/api/plans/${id}/setpoints`, { method: "PATCH", body: JSON.stringify(sp) });
export const deployPlan = (id: string) =>
  req<{ status: string }>(`/api/plans/${id}/deploy`, { method: "POST" });
export const cancelPlan = (id: string) => req(`/api/plans/${id}/cancel`, { method: "POST" });
export const deletePlan = (id: string) => req(`/api/plans/${id}`, { method: "DELETE" });
export const getTopology = (hall = "1f 2a") =>
  req<Topology>(`/api/topology?hall=${encodeURIComponent(hall)}`);

export interface CalibrationState {
  bias: Record<string, number>;
  sigma: Record<string, number>;
  n_weeks: number;
  version: string;
}
export const getCalibration = () => req<CalibrationState>(`/api/calibration`);

export interface WeatherCoverage {
  label: string | null;
  start_md?: string | null;
  end_md?: string | null;
  file?: string | null;
  suggested_week_start: string | null;
}
export const getWeather = () => req<WeatherCoverage>("/api/weather");

export interface TrajRow { step: number; inlet_temp_max_c: number | null; hvac_power_kw: number | null; pue: number | null; }
export interface Trajectory { nominal: TrajRow[]; worst: TrajRow[]; }
export const getTrajectory = (id: string) => req<Trajectory>(`/api/plans/${id}/trajectory`);
