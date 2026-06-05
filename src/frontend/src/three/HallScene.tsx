import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid, Environment, Edges } from '@react-three/drei';
import type { Topology } from '../api';
import { THEME } from './scene';
import CRAH from './CRAH';
import RackRows from './RackRows';
import Plant from './Plant';
import Airflow from './Airflow';

interface Props {
  topo: Topology;
  /** CRAH supply-air temperature setpoint (°C). */
  sat: number;
  /** CRAH supply-air mass-flow setpoint (kg/s). */
  flow: number;
  /** Plan peak inlet temperature (°C). */
  inletMax: number;
  showLabels?: boolean;
}

export default function HallScene({ topo, sat, flow, inletMax, showLabels = false }: Props) {
  const size = topo.hall.size as [number, number, number];
  const [w, h, d] = [size[0], size[2], size[1]];
  const radius = Math.max(w, d);

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [radius * 0.9, radius * 0.7, radius * 1.1], fov: 42 }}
      style={{ width: '100%', height: '100%', background: 'transparent' }}
    >
      {/* Lighting */}
      <ambientLight intensity={0.35} color="#88b8d8" />
      <directionalLight
        position={[w, h * 4, d]}
        intensity={1.1}
        color="#cfe8ff"
        castShadow
        shadow-mapSize={[1024, 1024]}
      />
      <pointLight position={[-w, h * 2, -d]} intensity={0.4} color={THEME.cyan} />
      <Environment preset="night" />

      {/* Floor grid */}
      <Grid
        position={[0, 0, 0]}
        args={[w, d]}
        cellSize={1}
        cellThickness={0.5}
        cellColor={THEME.border}
        sectionSize={5}
        sectionThickness={1}
        sectionColor={THEME.cyan}
        fadeDistance={radius * 2.6}
        fadeStrength={1.2}
        infiniteGrid={false}
        side={2}
      />

      {/* Hall glass shell with blueprint wireframe edges */}
      <mesh position={[0, h / 2, 0]}>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial
          color={THEME.cyan}
          transparent
          opacity={0.035}
          metalness={0.1}
          roughness={0.9}
          side={2}
        />
        <Edges threshold={15} color={THEME.border} />
      </mesh>

      {/* Equipment */}
      {topo.crahs.map((c) => (
        <CRAH key={c.id} crah={c} size={size} showLabel={showLabels} />
      ))}
      <RackRows rows={topo.rack_rows} size={size} sat={sat} inletMax={inletMax} />
      <Plant plant={topo.plant} crahs={topo.crahs} links={topo.links} size={size} />
      <Airflow
        crahs={topo.crahs}
        rackRows={topo.rack_rows}
        size={size}
        flow={flow}
        sat={sat}
        inletMax={inletMax}
      />

      <OrbitControls
        enablePan
        enableDamping
        dampingFactor={0.08}
        minDistance={radius * 0.4}
        maxDistance={radius * 3}
        maxPolarAngle={Math.PI / 2.05}
        target={[0, h / 2, 0]}
      />
    </Canvas>
  );
}
