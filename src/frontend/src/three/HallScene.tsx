import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid } from '@react-three/drei';
import type { Topology } from '../api';
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
}

export default function HallScene({
  topo, sat, flow, inletMax, showLabels = false, showContext = true,
}: Props) {
  const building = topo.building;
  const [W, D] = building.footprint;
  const H = building.height;
  const radius = Math.max(W, H, D);

  // Controlled hall: where the detailed equipment lives, lifted to its z-level.
  const ctrl = building.halls.find((h) => h.controlled);
  const ctrlSize = topo.hall.size;                 // [w, d, h] of the controlled hall
  const z0 = ctrl ? ctrl.z0 : 0;
  const detailY = z0 - H / 2;                       // floor of the controlled hall

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

      {/* All halls / levels as stacked glass boxes */}
      {visibleHalls.map((h) => (
        <HallBox key={h.code} hall={h} buildingHeight={H} showLabel={showContext || h.controlled} />
      ))}

      {/* Controlled-hall detail, lifted into the stack at its real level */}
      <group position={[0, detailY, 0]}>
        {topo.crahs.map((c) => (
          <CRAH key={c.id} crah={c} size={ctrlSize} showLabel={showLabels} />
        ))}
        <RackRows rows={topo.rack_rows} size={ctrlSize} sat={sat} inletMax={inletMax} />
        <Plant plant={topo.plant} crahs={topo.crahs} links={topo.links} size={ctrlSize} />
        <Airflow
          crahs={topo.crahs}
          rackRows={topo.rack_rows}
          size={ctrlSize}
          flow={flow}
          sat={sat}
          inletMax={inletMax}
        />
      </group>

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
