import { useEffect, useRef } from "react";
import * as THREE from "three";

/** Three.js 环境层 v3：染色光晕。
 *  纹理统一为白→透明径向渐变，颜色与强度由 material.color/opacity 染色，
 *  主题切换时目标值连续 lerp——平滑过渡，无跳变、无重建。 */
function whiteGlowTexture(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.55, "rgba(255,255,255,0.35)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
}

interface Conf { color: number; opacity: number; scale: number;
  pos: [number, number, number]; speed: number; }

const CONF: Record<"light" | "dark", Conf[]> = {
  // 浅色：无光斑（装饰交给瑞士网格描线）
  light: [
    { color: 0xb98e77, opacity: 0, scale: 15, pos: [6.5, 2.2, -4], speed: 0.05 },
    { color: 0x6f9793, opacity: 0, scale: 12, pos: [4.6, -3.2, -5], speed: 0.04 },
    { color: 0xa89a55, opacity: 0, scale: 9, pos: [8.2, -0.6, -6], speed: 0.06 },
  ],
  // 深色：5 光斑全屏铺开
  dark: [
    { color: 0x5a7fa8, opacity: 0.17, scale: 16, pos: [6.8, 2.4, -4], speed: 0.05 },
    { color: 0x8d7fa3, opacity: 0.13, scale: 13, pos: [-6.2, 3.4, -5], speed: 0.04 },
    { color: 0xa8c3c0, opacity: 0.10, scale: 11, pos: [-3.0, -4.4, -6], speed: 0.06 },
    { color: 0x5a7fa8, opacity: 0.09, scale: 9, pos: [8.4, -3.4, -7], speed: 0.045 },
    { color: 0x8d7fa3, opacity: 0.08, scale: 14, pos: [0.4, 0.6, -8], speed: 0.035 },
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

    const tex = whiteGlowTexture();
    const sprites: {
      s: THREE.Sprite; speed: number; phase: number;
      targetColor: THREE.Color; targetOpacity: number;
    }[] = [];

    CONF.dark.forEach((c, i) => {
      const mat = new THREE.SpriteMaterial({
        map: tex, transparent: true, depthWrite: false,
        color: c.color, opacity: c.opacity,
      });
      const s = new THREE.Sprite(mat);
      s.scale.set(c.scale, c.scale, 1);
      s.position.set(...c.pos);
      scene.add(s);
      sprites.push({ s, speed: c.speed, phase: i * 2.4,
        targetColor: new THREE.Color(c.color), targetOpacity: c.opacity });
    });

    const retarget = () => {
      const conf = document.documentElement.dataset.theme === "dark"
        ? CONF.dark : CONF.light;
      sprites.forEach((sp, i) => {
        sp.targetColor.set(conf[i].color);
        sp.targetOpacity = conf[i].opacity;
      });
    };
    addEventListener("spica-theme", retarget);

    const resize = () => {
      renderer.setSize(innerWidth, innerHeight, false);
      camera.aspect = innerWidth / innerHeight;
      camera.updateProjectionMatrix();
    };
    resize();
    addEventListener("resize", resize);

    let raf = 0;
    const t0 = performance.now();
    sprites.forEach(({ s }) => { s.userData.baseY = s.position.y; });
    const loop = () => {
      raf = requestAnimationFrame(loop);
      const t = (performance.now() - t0) / 1000;
      sprites.forEach(({ s, speed, phase, targetColor, targetOpacity }) => {
        // 主题色连续过渡（每帧 lerp，无跳变）
        const mat = s.material as THREE.SpriteMaterial;
        mat.color.lerp(targetColor, 0.035);
        mat.opacity += (targetOpacity - mat.opacity) * 0.035;
        s.position.y = s.userData.baseY + Math.sin(t * speed + phase) * 0.35;
      });
      renderer.render(scene, camera);
    };
    loop();

    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("resize", resize);
      removeEventListener("spica-theme", retarget);
      renderer.dispose();
    };
  }, []);

  const isDark = document.documentElement.dataset.theme === "dark";
  if (!isDark) return null;
  return <canvas ref={ref} className="backdrop-canvas" />;
}
