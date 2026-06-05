/**
 * airflow.ts — pure, WebGL-free helpers for the digital-twin airflow visual.
 *
 * Kept free of any three.js / DOM imports so they are trivially unit-testable
 * and reusable both in the render loop and in tests.
 */

export function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

/** Linear interpolation. */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/**
 * Map a CRAH air mass-flow setpoint to a normalized particle speed.
 *
 * Flow is expected within the controllable band [lb, ub] (kg/s). The result is
 * a multiplier in roughly [0.2, 1.0] that increases monotonically with flow, so
 * a higher recommended airflow visibly moves particles faster. Flows outside
 * the band are clamped.
 *
 * @param flow  CRAH supply-air mass-flow rate (kg/s)
 * @param lb    lower bound of the flow band (default 4.8)
 * @param ub    upper bound of the flow band (default 13.8)
 */
export function particleSpeed(flow: number, lb = 4.8, ub = 13.8): number {
  const span = ub - lb;
  const norm = span <= 0 ? 0 : clamp((flow - lb) / span, 0, 1);
  // Floor of 0.2 so even minimal flow shows gentle motion; ceiling 1.0.
  return 0.2 + 0.8 * norm;
}

export type RGB = { r: number; g: number; b: number };

/**
 * Thermal color ramp from cold-blue (at the supply-air temperature `sat`) to
 * hot-red (at the rack inlet maximum `inletMax`), passing through cyan/green/
 * amber in between — i.e. the cold-aisle → hot-aisle gradient.
 *
 * @param t         temperature to color (°C)
 * @param sat       supply-air temperature anchor → coldest (blue) (°C)
 * @param inletMax  peak inlet temperature anchor → hottest (red) (°C)
 * @returns RGB with each channel in [0, 1]
 */
export function tempColorRGB(t: number, sat: number, inletMax: number): RGB {
  const span = inletMax - sat;
  const x = span <= 0 ? 0 : clamp((t - sat) / span, 0, 1);

  // Five-stop ramp: blue → cyan → green → amber → red.
  const stops: RGB[] = [
    { r: 0.0,  g: 0.5,  b: 1.0  }, // cold blue
    { r: 0.0,  g: 0.78, b: 1.0  }, // cyan (matches app accent #00c8ff-ish)
    { r: 0.06, g: 0.72, b: 0.51 }, // green
    { r: 0.96, g: 0.62, b: 0.04 }, // amber
    { r: 0.94, g: 0.27, b: 0.27 }, // hot red
  ];

  const segs = stops.length - 1;
  const scaled = x * segs;
  const i = Math.min(Math.floor(scaled), segs - 1);
  const f = scaled - i;
  const a = stops[i];
  const b = stops[i + 1];
  return {
    r: lerp(a.r, b.r, f),
    g: lerp(a.g, b.g, f),
    b: lerp(a.b, b.b, f),
  };
}

/** Same ramp as {@link tempColorRGB}, returned as a `#rrggbb` hex string. */
export function tempColor(t: number, sat: number, inletMax: number): string {
  const { r, g, b } = tempColorRGB(t, sat, inletMax);
  const h = (c: number) =>
    Math.round(clamp(c, 0, 1) * 255)
      .toString(16)
      .padStart(2, '0');
  return `#${h(r)}${h(g)}${h(b)}`;
}
