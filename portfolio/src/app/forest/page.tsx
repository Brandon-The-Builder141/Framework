"use client";

import { Canvas } from "@react-three/fiber";
import { OrbitControls, Sky, Stars } from "@react-three/drei";
import { useRef, useMemo } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";

function seededRandom(seed) {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

function getHeight(x, z) {
  return (
    Math.sin(x * 0.04) * 2.5 +
    Math.cos(z * 0.06) * 2.0 +
    Math.sin(x * 0.015 + z * 0.02) * 4.0 +
    Math.sin(x * 0.08) * Math.cos(z * 0.08) * 1.2
  );
}

function Terrain({ res }) {
  const geometry = useMemo(() => {
    const geo = new THREE.PlaneGeometry(250, 250, res, res);
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getY(i);
      pos.setZ(i, getHeight(x, z));
    }
    geo.computeVertexNormals();
    return geo;
  }, [res]);

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
      <primitive object={geometry} attach="geometry" />
      <meshStandardMaterial color="#2a4a1a" roughness={0.92} flatShading />
    </mesh>
  );
}

function Tree({ x, z, seed }) {
  const terrainY = getHeight(x, z);
  const trunkH = 2.5 + seededRandom(seed) * 3;
  const canopyR = 1.8 + seededRandom(seed + 1) * 1.5;
  return (
    <group position={[x, terrainY, z]}>
      <mesh position={[0, trunkH / 2, 0]} castShadow>
        <cylinderGeometry args={[0.15, 0.28, trunkH, 6]} />
        <meshStandardMaterial color="#3a2a1a" roughness={0.95} />
      </mesh>
      <mesh position={[0, trunkH + canopyR * 0.35, 0]} castShadow>
        <coneGeometry args={[canopyR, canopyR * 1.1, 7]} />
        <meshStandardMaterial color="#1a5a1a" roughness={0.85} />
      </mesh>
      <mesh position={[0, trunkH + canopyR * 0.85, 0]} castShadow>
        <coneGeometry args={[canopyR * 0.65, canopyR * 0.9, 7]} />
        <meshStandardMaterial color="#2a6a2a" roughness={0.85} />
      </mesh>
    </group>
  );
}

function Forest({ count }) {
  const trees = useMemo(() => {
    const t = [];
    for (let i = 0; i < count; i++) {
      const s = (i + 1) * 2654435761;
      const x = (seededRandom(s) - 0.5) * 180;
      const z = (seededRandom(s + 1) - 0.5) * 180;
      if (Math.abs(x) < 8 && Math.abs(z) < 8) continue;
      t.push({ x, z, seed: s });
    }
    return t;
  }, [count]);
  return <>{trees.map((t, i) => <Tree key={i} x={t.x} z={t.z} seed={t.seed} />)}</>;
}

function GrassField({ count }) {
  const group = useRef(null);
  const blades = useMemo(() => {
    const b = [];
    for (let i = 0; i < count; i++) {
      const s = (i + 2000) * 123456789;
      const x = (seededRandom(s) - 0.5) * 160;
      const z = (seededRandom(s + 1) - 0.5) * 160;
      const h = 0.4 + seededRandom(s + 2) * 0.6;
      const hue = 95 + seededRandom(s + 3) * 45;
      const phase = seededRandom(s + 6) * Math.PI * 2;
      b.push({ x, z, h, hue, phase });
    }
    return b;
  }, [count]);

  useFrame(({ clock }) => {
    if (!group.current) return;
    const t = clock.getElapsedTime();
    group.current.children.forEach((child, i) => {
      const blade = blades[i];
      if (blade) {
        child.rotation.z = Math.sin(t * 2 + blade.phase) * 0.2;
        child.rotation.x = Math.cos(t * 1.5 + blade.phase * 0.7) * 0.15;
      }
    });
  });

  return (
    <group ref={group}>
      {blades.map((b, i) => {
        const y = getHeight(b.x, b.z);
        return (
          <mesh key={i} position={[b.x, y + b.h * 0.3, b.z]}>
            <coneGeometry args={[0.05, b.h, 3]} />
            <meshStandardMaterial color={`hsl(${b.hue}, 50%, 22%)`} roughness={0.85} side={THREE.DoubleSide} />
          </mesh>
        );
      })}
    </group>
  );
}

export default function ForestPage() {
  return (
    <Canvas camera={{ position: [0, 20, 40], fov: 50 }}>
      <ambientLight intensity={0.5} />
      <directionalLight position={[10, 20, 10]} intensity={1} castShadow />
      <Sky />
      <Stars />
      <Terrain res={128} />
      <Forest count={200} />
      <GrassField count={500} />
      <OrbitControls />
    </Canvas>
  );
}
