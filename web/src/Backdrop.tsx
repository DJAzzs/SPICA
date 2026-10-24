import { useEffect, useRef } from "react";
import * as THREE from "three";

/** Three.js 环境层 v2：径向渐变光晕（Canvas 纹理 Sprite）。
 *  无实体几何、无光照计算——浅色=暖白/雾青柔光，深色=冷蓝/灰紫微光。
 *  极慢漂移（90s+），主题切换实时换色。 */
function glowTexture(inner: string): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  grad.addColorStop(0, inner);
  grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
}

const THEMES = {
  light: [
    { color: "rgba(185,142,119,0.16)", scale: 15, pos: [6.5, 2.2, -4], speed: 0.05 },
    { color: "rgba(111,151,147,0.14)", scale: 12, pos: [4.6, -3.2, -5], speed: 0.04 },
    { color: "rgba(168,154,85,0.08)", scale: 9, pos: [8.2, -0.6, -6], speed: 0.06 },
  ],
  dark: [
    { color: "rgba(90,127,168,0.14)", scale: 15, pos: [6.5, 2.2, -4], speed: 0.05 },
    { color: "rgba(141,127,163,0.11)", scale: 12, pos: [4.6, -3.2, -5], speed: 0.04 },
    { color: "rgba(168,195,192,0.05)", scale: 9, pos: [8.2, -0.6, -6], speed: 0.06 },
  ],
};

export default function Backdrop() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current!;
    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 100);
    camera.position.set(0, 0, 14);

    const sprites: { s: THREE.Sprite; speed: number; phase: number }[] = [];
    const build = () => {
      sprites.forEach(({ s }) => { scene.remove(s); (s.material as any).dispose?.(); });
      sprites.length = 0;
      const conf = document.documentElement.dataset.theme === "dark"
        ? THEMES.dark : THEMES.light;
      conf.forEach((c, i) => {
        const tex = glowTexture(c.color);
        const s = new THREE.Sprite(new THREE.SpriteMaterial({
          map: tex, transparent: true, depthWrite: false,
        }));
        s.scale.set(c.scale, c.scale, 1);
        s.position.set(...(c.pos as [number, number, number]));
        scene.add(s);
        sprites.push({ s, speed: c.speed, phase: i * 2.4 });
      });
    };
    build();
    addEventListener("spica-theme", build);

    const resize = () => {
      renderer.setSize(innerWidth, innerHeight, false);
      camera.aspect = innerWidth / innerHeight;
      camera.updateProjectionMatrix();
    };
    resize();
    addEventListener("resize", resize);

    let raf = 0;
    const t0 = performance.now();
    sprites.forEach(({ s }, i) => { s.userData.baseY = s.position.y; });
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const t = (performance.now() - t0) / 1000;
      sprites.forEach(({ s, speed, phase }) => {
        s.position.y = s.userData.baseY + Math.sin(t * speed + phase) * 0.35;
      });
      renderer.render(scene, camera);
    };
    loop();

    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("resize", resize);
      removeEventListener("spica-theme", build);
      renderer.dispose();
    };
  }, []);

  return <canvas ref={ref} className="backdrop-canvas" />;
}
