import { Edges, Html } from '@react-three/drei';
import type { BuildingHall } from '../api';
import { THEME } from './scene';

interface Props {
  hall: BuildingHall;
  /** total building height (m), so the stack can be centred on the origin */
  buildingHeight: number;
  showLabel?: boolean;
}

/**
 * One data hall / room as a translucent glass box at its real z-level in the
 * stack. The operator-controlled hall is highlighted in cyan; context halls are
 * dim. A DOM label (no GL font dependency) tags each with its code, level and
 * ITE count.
 */
export default function HallBox({ hall, buildingHeight, showLabel = true }: Props) {
  const [w, d, h] = hall.size;          // w=x, d=depth(y), h=height(z)
  const cy = hall.z0 + h / 2 - buildingHeight / 2;   // centre, building centred on origin
  const ctrl = hall.controlled;
  const edge = ctrl ? THEME.cyan : THEME.border;

  return (
    <group position={[0, cy, 0]}>
      <mesh>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial
          color={ctrl ? THEME.cyan : '#16314a'}
          transparent
          opacity={ctrl ? 0.07 : 0.025}
          metalness={0.1}
          roughness={0.9}
          side={2}
        />
        <Edges threshold={15} color={edge} />
      </mesh>

      {showLabel && (
        <Html
          position={[w / 2, 0, -d / 2]}
          style={{ pointerEvents: 'none', transform: 'translate(10px, -50%)', whiteSpace: 'nowrap' }}
          zIndexRange={[10, 0]}
        >
          <div
            style={{
              fontFamily: 'var(--font-data, ui-monospace, monospace)',
              fontSize: 11,
              lineHeight: 1.3,
              padding: '3px 7px',
              borderRadius: 3,
              border: `1px solid ${ctrl ? THEME.cyan : THEME.border}`,
              background: 'rgba(8,12,20,0.72)',
              color: ctrl ? THEME.cyan : THEME.textLabel,
              boxShadow: ctrl ? `0 0 10px ${THEME.cyan}55` : 'none',
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
