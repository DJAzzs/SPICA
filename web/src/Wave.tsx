import { useEffect, useRef } from "react";
import { readWaveform } from "./audio";

/** 声纹可视化：真实波形驱动的镜像包络（本地 Analyser，rAF 帧率）。
 * 说话时上下起伏明显，安静时近乎平直。主界面与向导共用。 */
export default function Wave({ height = 56 }: { height?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current!;
    const x = c.getContext("2d")!;
    let raf = 0;
    const cols = 96;
    const env = new Float32Array(cols);
    let mist = "#a8c3c0";
    const refresh = () => {
      mist = getComputedStyle(document.documentElement)
        .getPropertyValue("--mist").trim() || mist;
    };
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const w = c.width, h = c.height, mid = h / 2;
      x.clearRect(0, 0, w, h);
      const wave = readWaveform();
      if (wave) {
        for (let i = 0; i < cols; i++) {
          let m = 0;
          const s = Math.floor((i * wave.length) / cols);
          const e = Math.floor(((i + 1) * wave.length) / cols);
          for (let j = s; j < e; j++) m = Math.max(m, Math.abs(wave[j] - 128));
          const v = Math.min(1, (m / 128) * 1.6);
          env[i] += (v - env[i]) * 0.35;
        }
      } else {
        for (let i = 0; i < cols; i++) env[i] *= 0.9;
      }
      x.beginPath();
      for (let i = 0; i < cols; i++) {
        const px = (i / (cols - 1)) * w;
        const y = mid - env[i] * (h * 0.42);
        i === 0 ? x.moveTo(px, y) : x.lineTo(px, y);
      }
      for (let i = cols - 1; i >= 0; i--) {
        const px = (i / (cols - 1)) * w;
        x.lineTo(px, mid + env[i] * (h * 0.42));
      }
      x.closePath();
      x.globalAlpha = 0.16; x.fillStyle = mist; x.fill();
      x.globalAlpha = 0.9; x.strokeStyle = mist; x.lineWidth = 1.5; x.stroke();
      x.globalAlpha = 1;
    };
    refresh();
    const themeTimer = setInterval(refresh, 2000);
    draw();
    return () => { cancelAnimationFrame(raf); clearInterval(themeTimer); };
  }, []);
  return <canvas ref={ref} width={720} height={height}
    style={{ display: "block", width: "100%", height }} />;
}
