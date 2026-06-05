/**
 * scene.ts — shared, WebGL-free constants & coordinate mapping for the hall scene.
 *
 * Backend positions are [x, y, z] in metres within the hall box where the floor
 * spans size[0] (x) × size[1] (y) and z is the vertical axis. three.js uses Y as
 * the up axis, so we map:
 *
 *     world [x, y, z]  →  three [x - w/2,  z,  y - d/2]
 *
 * i.e. center the floor on the origin and lift "height" (world z) into three Y.
 */
import type { Vec3 } from '../api';

/** Palette mirrored from index.css so the 3D scene matches the cockpit theme. */
export const THEME = {
  bg: '#080c14',
  panel: '#0d1320',
  cyan: '#00c8ff',
  cyanDim: '#0a2a3a',
  border: '#1e4060',
  amber: '#f59e0b',
  green: '#10b981',
  red: '#ef4444',
  violet: '#a78bfa',
  textLabel: '#94a3b8',
} as const;

/** Map a backend world position to a three.js position, centering the floor. */
export function toScene(pos: Vec3, size: Vec3): [number, number, number] {
  const [w, d] = size;
  const [x, y, z] = pos;
  return [x - w / 2, z, y - d / 2];
}
