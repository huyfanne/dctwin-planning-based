import { useState } from 'react';
import { Edges, Html } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';
import type { BuildingHall } from '../api';
import { THEME } from './scene';

interface Props {
  hall: BuildingHall;
  /** total building height (m), so the stack can be centred on the origin */
  buildingHeight: number;
  showLabel?: boolean;
  selected?: boolean;
  onSelect?: (code: string) => void;
}

/**
 * One data hall / room as a translucent glass box at its real z-level in the
 * stack. Click the box (or its label) to select it. The selected hall is
 * highlighted amber; the operator-controlled hall is cyan; context halls are
 * dim. A DOM label (no GL font dependency) tags each with code, level and ITE.
 */
export default function HallBox({
  hall, buildingHeight, showLabel = true, selected = false, onSelect,
}: Props) {
  const [w, d, h] = hall.size;          // w=x, d=depth(y), h=height(z)
  const cy = hall.z0 + h / 2 - buildingHeight / 2;   // centre, building centred on origin
  const ctrl = hall.controlled;
  const [hovered, setHovered] = useState(false);

  // colour priority: selected (amber) > controlled (cyan) > hovered > context
  const accent = selected ? THEME.amber : ctrl ? THEME.cyan : THEME.border;
  const opacity = selected ? 0.16 : hovered ? 0.1 : ctrl ? 0.07 : 0.025;
  const fill = selected ? THEME.amber : ctrl ? THEME.cyan : '#16314a';

  const pick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    onSelect?.(hall.code);
  };
  const over = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    setHovered(true);
    document.body.style.cursor = 'pointer';
  };
  const out = () => {
    setHovered(false);
    document.body.style.cursor = 'auto';
  };

  return (
    <group position={[0, cy, 0]}>
      <mesh onClick={pick} onPointerOver={over} onPointerOut={out}>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial
          color={fill}
          transparent
          opacity={opacity}
          metalness={0.1}
          roughness={0.9}
          side={2}
        />
        <Edges threshold={15} color={accent} />
      </mesh>

      {showLabel && (
        <Html
          position={[w / 2, 0, -d / 2]}
          style={{ pointerEvents: 'none', transform: 'translate(10px, -50%)', whiteSpace: 'nowrap' }}
          zIndexRange={[10, 0]}
        >
          <div
            onClick={() => onSelect?.(hall.code)}
            style={{
              pointerEvents: 'auto',
              cursor: 'pointer',
              fontFamily: 'var(--font-data, ui-monospace, monospace)',
              fontSize: 11,
              lineHeight: 1.3,
              padding: '3px 7px',
              borderRadius: 3,
              border: `1px solid ${accent}`,
              background: selected ? 'rgba(20,14,4,0.85)' : 'rgba(8,12,20,0.72)',
              color: selected ? THEME.amber : ctrl ? THEME.cyan : THEME.textLabel,
              boxShadow: selected
                ? `0 0 12px ${THEME.amber}88`
                : ctrl ? `0 0 10px ${THEME.cyan}55` : 'none',
            }}
          >
            <span style={{ fontWeight: 600 }}>{hall.code}</span>
            {ctrl && <span style={{ color: THEME.green }}> ◆ CONTROLLED</span>}
            <span style={{ opacity: 0.7 }}>
              {'  ·  '}{hall.level}{hall.ite > 1 ? `  ·  ${hall.ite} ITE` : ''}
            </span>
          </div>
        </Html>
      )}
    </group>
  );
}
