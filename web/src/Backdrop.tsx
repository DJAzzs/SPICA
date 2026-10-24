import { useEffect, useRef } from "react";
import * as THREE from "three";

/** Three.js 环境效果层（非交互，慢速）：
 *  浅色（米白新拟物）：哑光柔和几何体，双向柔光（亮左上/暗右下）
 *  深色（钛黑液态玻璃）：低透明玻璃质球体，冷色微光
 *  极慢漂浮（60-120s 周期），主题切换实时换材质。 */
export default function Backdrop() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current!;
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 100);
    camera.position.set(0, 0, 14);

    // 柔光系统：亮暖左上 + 暗冷右下（新拟物的光感来源）
    const keyLight = new THREE.DirectionalLight(0xfff6ea, 1.15);
    keyLight.position.set(-4, 5, 6);
    const fillLight = new THREE.DirectionalLight(0x9aa4b5, 0.5);
    fillLight.position.set(5, -4, 3);
    const amb = new THREE.AmbientLight(0xffffff, 0.55);
    scene.add(keyLight, fillLight, amb);

    // 形状：右侧竖排（避开居中的对话面板）
    const group = new THREE.Group();
    const shapes: { mesh: THREE.Mesh; phase: number; speed: number }[] = [];
    const geos = [
      new THREE.SphereGeometry(1.6, 48, 48),
      new THREE.CapsuleGeometry(0.9, 1.6, 16, 32),
      new THREE.SphereGeometry(1.0, 48, 48),
      new THREE.TorusGeometry(1.2, 0.45, 24, 64),
    ];
    const positions: [number, number, number][] = [
      [5.6, 1.6, -1], [7.6, -1.4, -2.5], [4.4, -2.8, -3.5], [6.8, 3.4, -4.5],
    ];
    geos.forEach((g, i) => {
      const mesh = new THREE.Mesh(g);
      mesh.position.set(...positions[i]);
      group.add(mesh);
      shapes.push({ mesh, phase: i * 1.9, speed: 0.14 + i * 0.05 });
    });
    // 左下远处一枚呼应
    const far = new THREE.Mesh(new THREE.SphereGeometry(2.4, 48, 48));
    far.position.set(-7.5, -4.2, -8);
    group.add(far);
    shapes.push({ mesh: far, phase: 5.2, speed: 0.08 });
    scene.add(group);

    let matLight: THREE.Material[] = [];
    let matDark: THREE.Material[] = [];
    const applyTheme = () => {
      const dark = document.documentElement.dataset.theme === "dark";
      matLight = shapes.map((_, i) => new THREE.MeshLambertMaterial({
        color: [0xdfd8cb, 0xd4dcd9, 0xd8d2c4, 0xd6d0da, 0xe2ddd3][i],
      }));
      matDark = shapes.map(() => new THREE.MeshPhongMaterial({
        color: 0x9fb4c8, transparent: true, opacity: 0.10,
        shininess: 90, specular: 0x88aacc,
      }));
      shapes.forEach((s, i) => {
        s.mesh.material = dark ? matDark[i] : matLight[i];
      });
      keyLight.intensity = dark ? 0.9 : 1.15;
      fillLight.intensity = dark ? 0.65 : 0.5;
    };
    applyTheme();
    addEventListener("spica-theme", applyTheme);

    const resize = () => {
      renderer.setSize(innerWidth, innerHeight, false);
      camera.aspect = innerWidth / innerHeight;
      camera.updateProjectionMatrix();
    };
    resize();
    addEventListener("resize", resize);

    let raf = 0;
    const t0 = performance.now();
    shapes.forEach((s) => { s.mesh.userData.baseY = s.mesh.position.y; });
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const t = (performance.now() - t0) / 1000;
      shapes.forEach((s) => {
        s.mesh.position.y = s.mesh.userData.baseY
          + Math.sin(t * s.speed + s.phase) * 0.28;
        s.mesh.rotation.x = t * 0.05 + s.phase;
        s.mesh.rotation.y = t * 0.03;
      });
      renderer.render(scene, camera);
    };
    loop();

    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("resize", resize);
      removeEventListener("spica-theme", applyTheme);
      renderer.dispose();
    };
  }, []);

  return <canvas ref={ref} className="backdrop-canvas" />;
}
