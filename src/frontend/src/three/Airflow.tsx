import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { AdditiveBlending, BufferAttribute, type Points } from 'three';
import type { TopoCRAH, TopoRackRow, Vec3 } from '../api';
import { particleSpeed, tempColorRGB } from './airflow';
import { toScene } from './scene';

interface Props {
  crahs: TopoCRAH[];
  rackRows: TopoRackRow[];
  size: Vec3;
  /** CRAH supply-air mass-flow setpoint (kg/s) → drives particle speed. */
  flow: number;
  /** Plan supply-air temperature (°C) → cold anchor of the color ramp. */
  sat: number;
  /** Plan peak inlet temperature (°C) → hot anchor of the color ramp. */
  inletMax: number;
}

const PARTICLES_PER_CRAH = 26;

interface Path {
  // 4-leg loop: CRAH supply → cold-aisle floor → up through rack → hot-aisle return
  pts: [number, number, number][];
  legLen: number[];
  total: number;
}

function buildPath(crah: TopoCRAH, target: [number, number, number], size: Vec3): Path {
  const [sx, , sz] = toScene(crah.pos, size);
  const [tx, , tz] = toScene(target, size);

  // Supply low near floor in the cold aisle, rise into the rack, return up high.
  const pts: [number, number, number][] = [
    [sx, 1.6, sz],          // CRAH supply outlet
    [sx, 0.35, sz],         // drop to under-floor / cold aisle
    [tx, 0.35, tz],         // travel along cold aisle to rack base
    [tx, 2.1, tz],          // rise through rack (heats up here)
    [sx, 3.2, sz],          // hot-aisle return up high back to CRAH
  ];

  const legLen: number[] = [];
  let total = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    const d = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    legLen.push(d);
    total += d;
  }
  return { pts, legLen, total };
}

/** Sample a position along a polyline path at normalized parameter u∈[0,1]. */
function sample(path: Path, u: number): [number, number, number] {
  const dist = u * path.total;
  let acc = 0;
  for (let i = 0; i < path.legLen.length; i++) {
    const len = path.legLen[i];
    if (dist <= acc + len || i === path.legLen.length - 1) {
      const f = len <= 0 ? 0 : (dist - acc) / len;
      const a = path.pts[i];
      const b = path.pts[i + 1];
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
    }
    acc += len;
  }
  const last = path.pts[path.pts.length - 1];
  return [last[0], last[1], last[2]];
}

/**
 * GPU particle system visualizing recirculating airflow. Each CRAH emits a
 * stream that loops cold-aisle → rack → hot-aisle return. The advance speed is
 * `particleSpeed(flow)` (so a higher recommended airflow moves particles
 * visibly faster) and each particle's color follows `tempColor` along its path
 * progress — cold/blue at supply, hot/red after passing through the rack.
 */
export default function Airflow({ crahs, rackRows, size, flow, sat, inletMax }: Props) {
  const pointsRef = useRef<Points>(null);
  const speed = particleSpeed(flow);

  // Pair each CRAH with the nearest rack row as its airflow target.
  const paths = useMemo<Path[]>(() => {
    if (rackRows.length === 0) return [];
    return crahs.map((c) => {
      const [cx, , cz] = toScene(c.pos, size);
      let best = rackRows[0];
      let bestD = Infinity;
      for (const r of rackRows) {
        const [rx, , rz] = toScene(r.pos, size);
        const d = Math.hypot(rx - cx, rz - cz);
        if (d < bestD) { bestD = d; best = r; }
      }
      return buildPath(c, best.pos, size);
    });
  }, [crahs, rackRows, size]);

  const count = paths.length * PARTICLES_PER_CRAH;

  // Per-particle (pathIndex, phase). Phase staggers particles along the loop.
  const meta = useMemo(() => {
    const m: { path: number; phase: number }[] = [];
    for (let p = 0; p < paths.length; p++) {
      for (let i = 0; i < PARTICLES_PER_CRAH; i++) {
        m.push({ path: p, phase: i / PARTICLES_PER_CRAH + (p % 5) * 0.013 });
      }
    }
    return m;
  }, [paths]);

  const positions = useMemo(() => new Float32Array(Math.max(count, 1) * 3), [count]);
  const colors = useMemo(() => new Float32Array(Math.max(count, 1) * 3), [count]);

  useFrame(({ clock }) => {
    const pts = pointsRef.current;
    if (!pts || paths.length === 0) return;
    const t = clock.elapsedTime * speed * 0.18;
    for (let i = 0; i < count; i++) {
      const { path, phase } = meta[i];
      const u = (t + phase) % 1;
      const [x, y, z] = sample(paths[path], u);
      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;

      // Color ramps with path progress: cold at supply, hot after the rack.
      // Map u∈[0,1] to a temperature between SAT and inletMax (peak mid-loop).
      const heat = u < 0.6 ? (u / 0.6) * 0.85 : 1 - ((u - 0.6) / 0.4) * 0.6;
      const temp = sat + (inletMax - sat) * heat;
      const { r, g, b } = tempColorRGB(temp, sat, inletMax);
      colors[i * 3] = r;
      colors[i * 3 + 1] = g;
      colors[i * 3 + 2] = b;
    }
    const posAttr = pts.geometry.getAttribute('position') as BufferAttribute;
    const colAttr = pts.geometry.getAttribute('color') as BufferAttribute;
    posAttr.needsUpdate = true;
    colAttr.needsUpdate = true;
  });

  if (count === 0) return null;

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.22}
        vertexColors
        transparent
        opacity={0.9}
        sizeAttenuation
        depthWrite={false}
        blending={AdditiveBlending}
      />
    </points>
  );
}
