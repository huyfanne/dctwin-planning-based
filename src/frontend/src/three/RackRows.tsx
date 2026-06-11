import { Fragment } from 'react';
import type { TopoRackRow, Vec3 } from '../api';
import { tempColor } from './airflow';
import { THEME, toScene } from './scene';

interface Props {
  rows: TopoRackRow[];
  size: Vec3;
  /** Plan supply-air temperature (°C) — anchors the cold (blue) end. */
  sat: number;
  /** Plan peak inlet temperature (°C) — anchors the hot (red) end. */
  inletMax: number;
  /** Optional live telemetry color per row (zone green/amber/red), index-aligned
   *  with `rows`; a null entry or absent prop → plan-gradient coloring. */
  liveColors?: (string | null)[];
}

const RACK_W = 0.6;   // along the row (x)
const RACK_D = 1.0;   // depth (z)
const RACK_H = 2.0;   // height (y)
const GAP = 0.06;

/**
 * Server-rack rows. Each rack is colored along the cold-aisle → hot-aisle
 * gradient: a "cold" aisle row sits near the supply-air temperature (blue), a
 * "hot" aisle row trends toward the peak inlet temperature (red). Within a row
 * the temperature ramps slightly from front to back so the gradient reads in 3D.
 */
export default function RackRows({ rows, size, sat, inletMax, liveColors }: Props) {
  const span = Math.max(inletMax - sat, 0.001);

  return (
    <group>
      {rows.map((row, ri) => {
        const [cx, , cz] = toScene(row.pos, size);
        const n = Math.max(1, row.nracks);
        const pitch = RACK_W + GAP;
        const rowLen = n * pitch;
        const startX = cx - rowLen / 2 + pitch / 2;

        // Base temperature for the aisle type.
        const aisleBase =
          row.aisle === 'cold' ? sat + span * 0.1 : sat + span * 0.75;
        // Live telemetry zone color overrides the whole row when available.
        const live = liveColors?.[ri] ?? null;

        return (
          <Fragment key={row.id ?? ri}>
            {Array.from({ length: n }).map((_, i) => {
              // Mild front→back ramp so racks aren't flat-colored.
              const ramp = (i / Math.max(n - 1, 1)) * span * 0.18;
              const t = aisleBase + ramp;
              const color = live ?? tempColor(t, sat, inletMax);
              return (
                <mesh
                  key={i}
                  position={[startX + i * pitch, RACK_H / 2, cz]}
                  castShadow
                >
                  <boxGeometry args={[RACK_W, RACK_H, RACK_D]} />
                  <meshStandardMaterial
                    color={color}
                    emissive={color}
                    emissiveIntensity={0.22}
                    metalness={0.35}
                    roughness={0.55}
                  />
                </mesh>
              );
            })}
            {/* Aisle tag strip on the floor under the row */}
            <mesh
              position={[cx, 0.02, cz]}
              rotation={[-Math.PI / 2, 0, 0]}
            >
              <planeGeometry args={[rowLen, RACK_D * 1.05]} />
              <meshBasicMaterial
                color={row.aisle === 'cold' ? THEME.cyan : THEME.red}
                transparent
                opacity={0.07}
              />
            </mesh>
          </Fragment>
        );
      })}
    </group>
  );
}
