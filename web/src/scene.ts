/** Three.js 等距场景：任务=悬浮几何体，子步骤=上方小块，完成=上升转雾青。
 * 遵循效果层规范 §4/§11：哑光 Lambert、一方向光+弱环境光、PCFSoft 极淡阴影、
 * 极淡雾、无后处理；60fps；降级只减光晕/阴影/雾。
 */
import * as THREE from "three";
import { getMicLevel } from "./audio";

export type SceneState = "idle" | "listen" | "exec" | "paused" | "confirm" | "done";

const PALETTE = {
  sand: 0xd9b8a6, mist: 0xa8c3c0, mustard: 0xd6c98a, lilac: 0xb7aec4,
  accent: 0xc86a54, dim: 0x6a6e78,
};
const LAYER_COLORS = [PALETTE.sand, PALETTE.mustard, PALETTE.lilac];

export class SpicaScene {
  private renderer: THREE.WebGLRenderer;
  private scene: THREE.Scene;
  private camera: THREE.OrthographicCamera;
  private taskMesh: THREE.Mesh;
  private taskBase: number;               // 任务体基准高度
  private stepMeshes: THREE.Mesh[] = [];
  private frame = 0;
  private state: SceneState = "idle";
  private rms = 0;
  private orbit = false;
  private baseColor = new THREE.Color(PALETTE.sand);
  private doneAt = 0;
  private degraded = { glow: true, shadow: true, fog: true };

  constructor(canvas: HTMLCanvasElement, theme: "light" | "dark" = "dark") {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.scene = new THREE.Scene();
    this.applyTheme(theme);

    const aspect = innerWidth / innerHeight;
    const h = 5.2;
    this.camera = new THREE.OrthographicCamera(-h * aspect, h * aspect, h, -h, 0.1, 100);
    this.setIso();

    const dir = new THREE.DirectionalLight(0xffffff, 1.0);
    dir.position.set(3, 5, 2);
    dir.castShadow = true;
    dir.shadow.mapSize.set(1024, 1024);
    this.scene.add(dir);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.35));

    // 地面（接影）
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(40, 40),
      new THREE.MeshLambertMaterial({ color: 0x000000, transparent: true, opacity: 0.0 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -1.6;
    ground.receiveShadow = true;
    this.scene.add(ground);

    // 任务几何体（右侧留白区，不压左列文本）
    this.taskBase = 0;
    this.taskMesh = new THREE.Mesh(
      new THREE.BoxGeometry(1.4, 1.4, 1.4),
      new THREE.MeshLambertMaterial({ color: this.baseColor }),
    );
    this.taskMesh.position.set(3.2, this.taskBase, 0);
    this.taskMesh.castShadow = true;
    this.scene.add(this.taskMesh);

    addEventListener("resize", () => this.onResize());
    this.onResize();
    this.loop();
  }

  private setIso() {
    // 等距：绕 Y 45°，俯 35.264°
    const r = 14;
    this.camera.position.set(r * Math.cos(Math.PI / 6), r * Math.sin(Math.PI / 6), r * Math.cos(Math.PI / 6));
    this.camera.lookAt(2.6, 0, 0);
  }

  private onResize() {
    this.renderer.setSize(innerWidth, innerHeight, false);
    const aspect = innerWidth / innerHeight;
    const h = 5.2;
    this.camera.left = -h * aspect; this.camera.right = h * aspect;
    this.camera.top = h; this.camera.bottom = -h;
    this.camera.updateProjectionMatrix();
  }

  applyTheme(theme: "light" | "dark") {
    const bg = new THREE.Color(theme === "dark" ? 0x1c1f24 : 0xf7f6f3);
    this.scene.background = bg;
    this.scene.fog = this.degraded.fog ? new THREE.FogExp2(bg.getHex(), 0.02) : null;
  }

  setState(s: SceneState, steps = 0) {
    if (s === "done" && this.state !== "done") this.doneAt = performance.now();
    this.state = s;
    this.syncSteps(steps);
  }

  setRms(rms: number) { this.rms = rms; }
  setOrbit(on: boolean) { this.orbit = on; }
  degrade(level: 0 | 1 | 2) {
    this.degraded = { glow: level < 1, shadow: level < 2, fog: level < 1 };
    this.renderer.shadowMap.enabled = this.degraded.shadow;
  }

  /** 子步骤块：任务体上方排布，完成转雾青。 */
  private syncSteps(n: number) {
    while (this.stepMeshes.length < Math.min(n, 7)) {
      const i = this.stepMeshes.length;
      const m = new THREE.Mesh(
        new THREE.BoxGeometry(0.4, 0.4, 0.4),
        new THREE.MeshLambertMaterial({ color: LAYER_COLORS[i % 3] }),
      );
      const col = i % 3, row = Math.floor(i / 3);
      m.position.set(3.2 + (col - 1) * 0.7, this.taskBase + 1.2 + row * 0.7, (row % 2 ? 0.2 : -0.2));
      m.castShadow = true;
      this.scene.add(m);
      this.stepMeshes.push(m);
    }
    const done = this.state === "done";
    this.stepMeshes.forEach((m, i) => {
      const mat = m.material as THREE.MeshLambertMaterial;
      const target = done ? new THREE.Color(PALETTE.mist) : new THREE.Color(LAYER_COLORS[i % 3]);
      mat.color.lerp(target, 0.05);
      const targetY = (done ? 0.3 : 0) + this.taskBase + 1.2 + Math.floor(i / 3) * 0.7;
      m.position.y += (targetY - m.position.y) * 0.04;
    });
  }

  private loop = () => {
    requestAnimationFrame(this.loop);
    this.frame++;
    const t = this.frame / 60;

    // 静息呼吸：任务体 ±0.05 正弦（8s）
    const breath = Math.sin(t * (2 * Math.PI / 8)) * 0.05;
    let y = this.taskBase + breath;
    if (this.state === "done") y += 0.5 * Math.min(1, (performance.now() - this.doneAt) / 1200);
    this.taskMesh.position.y += (y - this.taskMesh.position.y) * 0.06;

    // 完成色过渡
    const mat = this.taskMesh.material as THREE.MeshLambertMaterial;
    const targetColor = this.state === "done"
      ? new THREE.Color(PALETTE.mist)
      : this.state === "confirm" ? new THREE.Color(PALETTE.mustard) : this.baseColor;
    mat.color.lerp(targetColor, 0.04);

    // 播报光晕：随 RMS 的极淡自发光
    if (this.degraded.glow) {
      mat.emissive.setHex(this.state === "exec" ? PALETTE.sand : 0x000000);
      mat.emissiveIntensity = this.state === "exec"
        ? 0.05 + Math.min(0.12, this.rms * 2.4) : 0.0;
    } else mat.emissiveIntensity = 0;

    // 唯一强调：当前任务体线框（exec 时）
    if (this.state === "exec") {
      const outline = new THREE.LineSegments(
        new THREE.EdgesGeometry(this.taskMesh.geometry),
        new THREE.LineBasicMaterial({ color: PALETTE.accent, transparent: true, opacity: 0.6 }),
      );
      // 每帧替换代价低（单几何体）；位置同步
      outline.position.copy(this.taskMesh.position);
      this.taskMesh.children.forEach((c) => this.taskMesh.remove(c));
      this.taskMesh.add(outline);
    } else if (this.taskMesh.children.length) {
      this.taskMesh.children.forEach((c) => this.taskMesh.remove(c));
    }

    // 聆听：任务体随用户真实音量轻微律动（本地麦克风，rAF 帧率）
    if (this.state === "listen") {
      const target = 1 + Math.min(0.06, getMicLevel() * 0.5);
      const cur = this.taskMesh.scale.x;
      this.taskMesh.scale.setScalar(cur + (target - cur) * 0.18);
    } else this.taskMesh.scale.setScalar(1);

    // 极缓轨道（演示模式）
    if (this.orbit) {
      const a = t * (2 * Math.PI / 90);
      const r = 14;
      this.camera.position.set(2.6 + r * Math.cos(a), 7, r * Math.sin(a));
      this.camera.lookAt(2.6, 0, 0);
    }

    this.renderer.render(this.scene, this.camera);
  };
}
