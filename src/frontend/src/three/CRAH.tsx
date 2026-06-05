import { useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import type { Mesh } from 'three';
import type { TopoCRAH, Vec3 } from '../api';
import { THEME, toScene } from './scene';

interface Props {
  crah: TopoCRAH;
  size: Vec3;
  showLabel?: boolean;
}

/** A single CRAH unit: a tall unit box at the hall wall with a hover/Html label. */
export default function CRAH({ crah, size, showLabel = false }: Props) {
  const [x, , z] = toScene(crah.pos, size);
  const meshRef = useRef<Mesh>(null);
  const [hovered, setHovered] = useState(false);

  // Subtle "running fan" intake glow that breathes.
  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const m = meshRef.current.material as { emissiveIntensity?: number };
    if (m && 'emissiveIntensity' in m) {
      m.emissiveIntensity = 0.35 + 0.15 * Math.sin(clock.elapsedTime * 2 + x);
    }
  });

  const h = 2.4; // unit height (m)

  return (
    <group position={[x, h / 2, z]}>
      <mesh
        ref={meshRef}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
        onPointerOut={() => setHovered(false)}
        castShadow
      >
        <boxGeometry args={[1.4, h, 1.0]} />
        <meshStandardMaterial
          color={hovered ? '#16344a' : '#10222f'}
          emissive={THEME.cyan}
          emissiveIntensity={0.35}
          metalness={0.6}
          roughness={0.35}
        />
      </mesh>
      {/* Intake grille face glow */}
      <mesh position={[0, 0, 0.51]}>
        <planeGeometry args={[1.1, h * 0.8]} />
        <meshBasicMaterial color={THEME.cyan} transparent opacity={hovered ? 0.5 : 0.28} />
      </mesh>

      {(showLabel || hovered) && (
        <Html position={[0, h / 2 + 0.4, 0]} center distanceFactor={18} zIndexRange={[10, 0]}>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              color: THEME.cyan,
              background: 'rgba(8,12,20,0.82)',
              border: `1px solid ${THEME.border}`,
              borderRadius: 3,
              padding: '2px 6px',
              whiteSpace: 'nowrap',
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              pointerEvents: 'none',
            }}
          >
            {crah.id}
          </div>
        </Html>
      )}
    </group>
  );
}
