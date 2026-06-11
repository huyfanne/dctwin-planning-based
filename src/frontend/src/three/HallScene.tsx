import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid } from '@react-three/drei';
import type { BuildingHall, Topology } from '../api';
import { THEME } from './scene';
import CRAH from './CRAH';
import RackRows from './RackRows';
import Plant from './Plant';
import Airflow from './Airflow';
import HallBox from './HallBox';

interface Props {
  topo: Topology;
  /** CRAH supply-air temperature setpoint (°C). */
  sat: number;
  /** CRAH supply-air mass-flow setpoint (kg/s). */
  flow: number;
  /** Plan peak inlet temperature (°C). */
  inletMax: number;
  showLabels?: boolean;
  /** show every hall/level (true) or just the controlled hall (false). */
  showContext?: boolean;
  /** code of the currently selected hall (highlighted + its equipment shown). */
  selectedCode?: string;
  /** called when a hall box/label is clicked. */
  onSelectHall?: (code: string) => void;
  /** live telemetry colors for the CONTROLLED hall's rack rows, index-aligned
   *  with its rackRows; null entries / absent prop → plan-gradient coloring. */
  liveRowColors?: (string | null)[];
}

/** A hall's equipment (ACUs + rack rows, optionally animated airflow), lifted to
 *  its real z-level in the building stack. */
function HallEquipment({
  hall, buildingHeight, sat, flow, inletMax, showLabels, withAirflow, liveRowColors,
}: {
  hall: BuildingHall; buildingHeight: number;
  sat: number; flow: number; inletMax: number;
  showLabels: boolean; withAirflow: boolean;
  liveRowColors?: (string | null)[];
}) {
  return (
    <group position={[0, hall.z0 - buildingHeight / 2, 0]}>
      {hall.crahs.map((c) => (
        <CRAH key={c.id} crah={c} size={hall.size} showLabel={showLabels} />
      ))}
      <RackRows rows={hall.rackRows} size={hall.size} sat={sat} inletMax={inletMax} liveColors={liveRowColors} />
      {withAirflow && (
        <Airflow
          crahs={hall.crahs}
          rackRows={hall.rackRows}
          size={hall.size}
          flow={flow}
          sat={sat}
          inletMax={inletMax}
        />
      )}
    </group>
  );
}

export default function HallScene({
  topo, sat, flow, inletMax, showLabels = false, showContext = true,
  selectedCode, onSelectHall, liveRowColors,
}: Props) {
  const building = topo.building;
  const [W, D] = building.footprint;
  const H = building.height;
  const radius = Math.max(W, H, D);

  const ctrl = building.halls.find((h) => h.controlled);
  const selected = building.halls.find((h) => h.code === selectedCode);
  // Render the controlled hall's equipment always (it's the live hall) plus the
  // selected hall's equipment when a different hall is being inspected.
  const showSelectedEquip = !!selected && !selected.controlled && showContext;

  const visibleHalls = showContext
    ? building.halls
    : building.halls.filter((h) => h.controlled);

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [radius * 0.95, radius * 0.75, radius * 1.15], fov: 42 }}
      style={{ width: '100%', height: '100%', background: 'transparent' }}
    >
      {/* Lighting */}
      <ambientLight intensity={0.4} color="#88b8d8" />
      <directionalLight
        position={[W, H * 2, D]}
        intensity={1.1}
        color="#cfe8ff"
        castShadow
        shadow-mapSize={[1024, 1024]}
      />
      <pointLight position={[-W, H, -D]} intensity={0.4} color={THEME.cyan} />
      <hemisphereLight intensity={0.5} color="#bfe0ff" groundColor="#0a1622" />

      {/* Floor grid at the base of the stack */}
      <Grid
        position={[0, -H / 2, 0]}
        args={[W * 1.2, D * 1.2]}
        cellSize={2}
        cellThickness={0.5}
        cellColor={THEME.border}
        sectionSize={10}
        sectionThickness={1}
        sectionColor={THEME.cyan}
        fadeDistance={radius * 3}
        fadeStrength={1.1}
        infiniteGrid={false}
        side={2}
      />

      {/* All halls / levels as stacked glass boxes (clickable) */}
      {visibleHalls.map((h) => (
        <HallBox
          key={h.code}
          hall={h}
          buildingHeight={H}
          showLabel={showContext || h.controlled}
          selected={h.code === selectedCode}
          onSelect={onSelectHall}
        />
      ))}

      {/* Controlled hall: full detail + animated airflow + plant */}
      {ctrl && (
        <>
          <HallEquipment
            hall={ctrl}
            buildingHeight={H}
            sat={sat}
            flow={flow}
            inletMax={inletMax}
            showLabels={showLabels}
            withAirflow
            liveRowColors={liveRowColors}
          />
          <group position={[0, ctrl.z0 - H / 2, 0]}>
            <Plant plant={topo.plant} crahs={ctrl.crahs} links={topo.links} size={ctrl.size} />
          </group>
        </>
      )}

      {/* Selected context hall: its own ACUs + racks (no airflow — scheduled) */}
      {showSelectedEquip && selected && (
        <HallEquipment
          hall={selected}
          buildingHeight={H}
          sat={sat}
          flow={flow}
          inletMax={inletMax}
          showLabels={showLabels}
          withAirflow={false}
        />
      )}

      <OrbitControls
        enablePan
        enableDamping
        dampingFactor={0.08}
        minDistance={radius * 0.35}
        maxDistance={radius * 3.5}
        maxPolarAngle={Math.PI / 1.95}
        target={[0, 0, 0]}
      />
    </Canvas>
  );
}
