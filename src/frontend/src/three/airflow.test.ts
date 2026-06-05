import { describe, it, expect } from 'vitest';
import { particleSpeed, tempColor, tempColorRGB, clamp, lerp } from './airflow';

describe('clamp / lerp', () => {
  it('clamps below, within, above', () => {
    expect(clamp(-1, 0, 1)).toBe(0);
    expect(clamp(0.5, 0, 1)).toBe(0.5);
    expect(clamp(2, 0, 1)).toBe(1);
  });
  it('lerps endpoints and midpoint', () => {
    expect(lerp(0, 10, 0)).toBe(0);
    expect(lerp(0, 10, 1)).toBe(10);
    expect(lerp(0, 10, 0.5)).toBe(5);
  });
});

describe('particleSpeed', () => {
  it('is in ~[0.2, 1] across the flow band', () => {
    expect(particleSpeed(4.8)).toBeCloseTo(0.2, 5);
    expect(particleSpeed(13.8)).toBeCloseTo(1.0, 5);
    const mid = particleSpeed(9.3);
    expect(mid).toBeGreaterThan(0.2);
    expect(mid).toBeLessThan(1.0);
  });

  it('increases monotonically with flow', () => {
    expect(particleSpeed(13.8)).toBeGreaterThan(particleSpeed(9.3));
    expect(particleSpeed(9.3)).toBeGreaterThan(particleSpeed(4.8));
    // Higher recommended airflow ⇒ visibly faster particles.
    expect(particleSpeed(12)).toBeGreaterThan(particleSpeed(6));
  });

  it('clamps flows outside the band', () => {
    expect(particleSpeed(0)).toBeCloseTo(0.2, 5);
    expect(particleSpeed(100)).toBeCloseTo(1.0, 5);
  });

  it('respects custom bounds', () => {
    expect(particleSpeed(5, 0, 10)).toBeCloseTo(0.2 + 0.8 * 0.5, 5);
  });

  it('does not divide by zero for a degenerate band', () => {
    expect(particleSpeed(5, 10, 10)).toBeCloseTo(0.2, 5);
  });
});

describe('tempColor / tempColorRGB', () => {
  const SAT = 22;
  const INLET_MAX = 27;

  it('is blue-ish at the supply-air anchor (t = sat)', () => {
    const c = tempColorRGB(SAT, SAT, INLET_MAX);
    expect(c.b).toBeGreaterThan(c.r); // blue dominates red at the cold end
    expect(c.b).toBeGreaterThan(0.7);
    expect(c.r).toBeLessThan(0.2);
  });

  it('is red-ish at the inlet-max anchor (t = inletMax)', () => {
    const c = tempColorRGB(INLET_MAX, SAT, INLET_MAX);
    expect(c.r).toBeGreaterThan(c.b); // red dominates blue at the hot end
    expect(c.r).toBeGreaterThan(0.7);
    expect(c.b).toBeLessThan(0.4);
  });

  it('warms (red rises, blue falls) as temperature increases', () => {
    const cold = tempColorRGB(SAT, SAT, INLET_MAX);
    const warm = tempColorRGB((SAT + INLET_MAX) / 2, SAT, INLET_MAX);
    const hot = tempColorRGB(INLET_MAX, SAT, INLET_MAX);
    expect(warm.r).toBeGreaterThan(cold.r);
    expect(hot.r).toBeGreaterThan(warm.r);
    expect(hot.b).toBeLessThan(cold.b);
  });

  it('clamps out-of-range temperatures to the endpoints', () => {
    expect(tempColorRGB(0, SAT, INLET_MAX)).toEqual(tempColorRGB(SAT, SAT, INLET_MAX));
    expect(tempColorRGB(99, SAT, INLET_MAX)).toEqual(tempColorRGB(INLET_MAX, SAT, INLET_MAX));
  });

  it('returns a valid #rrggbb hex string', () => {
    const hex = tempColor(SAT, SAT, INLET_MAX);
    expect(hex).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('hex cold end is blue, hot end is red', () => {
    expect(tempColor(SAT, SAT, INLET_MAX)).toMatch(/^#00/); // r channel ~00 at cold
    const hot = tempColor(INLET_MAX, SAT, INLET_MAX);
    const r = parseInt(hot.slice(1, 3), 16);
    const b = parseInt(hot.slice(5, 7), 16);
    expect(r).toBeGreaterThan(b);
  });
});
