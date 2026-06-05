import { useMemo } from 'react';
import { Line } from '@react-three/drei';
import { Html } from '@react-three/drei';
import type { TopoPlant, TopoCRAH, TopoLink, Vec3 } from '../api';
import { THEME, toScene } from './scene';

interface Props {
  plant: TopoPlant;
  crahs: TopoCRAH[];
  links: TopoLink[];
  size: Vec3;
}

interface Block {
  label: string;
  count: number;
  color: string;
  size: [number, number, number];
}

/**
 * The cooling plant (chiller / cooling-tower / pumps) drawn as a small block
 * group offset outside the hall, with chilled-water pipe lines fanning out to
 * each CRAH per the `links` list.
 */
export default function Plant({ plant, crahs, links, size }: Props) {
  const [px, , pz] = toScene(plant.pos ?? [-8, size[1] / 2, 0], size);

  const blocks: Block[] = [
    { label: `Chiller ×${plant.chiller}`, count: plant.chiller, color: THEME.cyan, size: [2.2, 2.6, 2.0] },
    { label: `Cooling Tower ×${plant.coolingTower}`, count: plant.coolingTower, color: THEME.violet, size: [2.0, 3.2, 2.0] },
    { label: `Pumps ×${plant.pumps}`, count: plant.pumps, color: THEME.green, size: [1.4, 1.2, 1.4] },
  ];

  const crahById = useMemo(
    () => new Map(crahs.map((c) => [c.id, c])),
    [crahs],
  );

  // Plant pipe origin (top of the chiller block).
  const origin: [number, number, number] = [px, 2.4, pz];

  const pipes = useMemo(() => {
    const out: [number, number, number][][] = [];
    for (const link of links) {
      if (link.from !== 'plant') continue;
      const c = crahById.get(link.to);
      if (!c) continue;
      const [cx, , cz] = toScene(c.pos, size);
      // Manhattan-style routed pipe: up, across in z to wall, then to CRAH.
      out.push([
        origin,
        [px, 0.4, pz],
        [px, 0.4, cz],
        [cx, 0.4, cz],
        [cx, 1.0, cz],
      ]);
    }
    return out;
  }, [links, crahById, size, px, pz, origin]);

  return (
    <group>
      {/* Plant blocks, stacked along z */}
      {blocks.map((b, i) => (
        <group key={b.label} position={[px, b.size[1] / 2, pz + (i - 1) * 3.0]}>
          <mesh castShadow>
            <boxGeometry args={b.size} />
            <meshStandardMaterial
              color="#0c1a24"
              emissive={b.color}
              emissiveIntensity={0.3}
              metalness={0.55}
              roughness={0.4}
            />
          </mesh>
          <Html position={[0, b.size[1] / 2 + 0.4, 0]} center distanceFactor={20} zIndexRange={[5, 0]}>
            <div
              style={{
                fontFamily: "'Rajdhani', sans-serif",
                fontSize: 11,
                fontWeight: 700,
                color: b.color,
                background: 'rgba(8,12,20,0.8)',
                border: `1px solid ${THEME.border}`,
                borderRadius: 3,
                padding: '1px 6px',
                whiteSpace: 'nowrap',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                pointerEvents: 'none',
              }}
            >
              {b.label}
            </div>
          </Html>
        </group>
      ))}

      {/* Chilled-water pipe lines to CRAHs */}
      {pipes.map((pts, i) => (
        <Line
          key={i}
          points={pts}
          color={THEME.cyan}
          lineWidth={1}
          transparent
          opacity={0.18}
        />
      ))}
    </group>
  );
}
