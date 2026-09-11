import "./style.css";
import { Compositor } from "./render/compositor";
import { NodeGraph } from "./ui/nodegraph";
import { newProject, addRegion, saveProjectLocal, loadProjectLocal } from "./core/project";
import { importVctpl } from "./core/vctpl";
import { recordComposite, extForMime } from "./export";
import type { Project } from "./core/types";

const app = document.getElementById("app")!;
app.innerHTML = `
  <div class="topbar">
    <h1>CLIPR</h1>
    <button class="btn icon" id="btnLoad" title="Load video">📂 Video</button>
    <button class="btn icon" id="btnTpl" title="Import template">🧩 Template</button>
    <span class="spacer"></span>
    <button class="btn icon" id="btnNodes" title="Toggle node view">🧠</button>
    <button class="btn primary" id="btnExport" disabled>Export</button>
  </div>
  <div class="preview-wrap">
    <canvas id="previewCanvas"></canvas>
    <div class="empty-state hidden" id="emptyState">Load a video to start reframing.</div>
  </div>
  <div class="transport">
    <button class="btn icon" id="btnPlay" disabled>▶</button>
    <input type="range" id="scrub" min="0" max="1000" value="0" disabled />
    <span class="time-label" id="timeLabel">0:00 / 0:00</span>
  </div>
  <div class="nodepanel" id="nodePanel">
    <div class="nodecanvas" id="nodeCanvas">
      <div class="node-canvas-hint">drag to pan · pinch/wheel to zoom · drag cards to move</div>
    </div>
    <div style="display:flex; gap:8px; padding:8px; border-top:1px solid var(--line);">
      <button class="btn" id="btnAddRegion">+ Region</button>
      <span class="spacer"></span>
      <button class="btn" id="btnSaveProj">Save</button>
    </div>
  </div>
  <input type="file" id="fileVideo" accept="video/*" class="hidden" />
  <input type="file" id="fileTpl" accept=".vctpl,application/json" class="hidden" />
`;

const canvas = document.getElementById("previewCanvas") as HTMLCanvasElement;
const emptyState = document.getElementById("emptyState") as HTMLDivElement;
const btnPlay = document.getElementById("btnPlay") as HTMLButtonElement;
const scrub = document.getElementById("scrub") as HTMLInputElement;
const timeLabel = document.getElementById("timeLabel") as HTMLSpanElement;
const btnExport = document.getElementById("btnExport") as HTMLButtonElement;
const btnNodes = document.getElementById("btnNodes") as HTMLButtonElement;
const nodePanel = document.getElementById("nodePanel") as HTMLDivElement;
const nodeCanvasEl = document.getElementById("nodeCanvas") as HTMLDivElement;
const fileVideo = document.getElementById("fileVideo") as HTMLInputElement;
const fileTpl = document.getElementById("fileTpl") as HTMLInputElement;

let project: Project = newProject();
const compositor = new Compositor(canvas);
const video = document.createElement("video");
video.playsInline = true;
video.muted = false;
video.preload = "auto";

let rafId = 0;
let hasVideo = false;

const graph = new NodeGraph(nodeCanvasEl, project, {
  onChange: () => { drawOnce(); },
  onSelect: () => {},
  onDelete: (id) => {
    project.nodes = project.nodes.filter((n) => n.id !== id);
    graph.setProject(project);
    drawOnce();
  },
});

function drawOnce() {
  if (!hasVideo) return;
  compositor.uploadFrame(video, video.videoWidth, video.videoHeight);
  compositor.draw(project);
}

function loop() {
  if (hasVideo && !video.paused && !video.ended) {
    compositor.uploadFrame(video, video.videoWidth, video.videoHeight);
    compositor.draw(project);
    updateTransport();
  }
  rafId = requestAnimationFrame(loop);
}
rafId = requestAnimationFrame(loop);

function fmtTime(s: number): string {
  if (!isFinite(s)) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function updateTransport() {
  if (!video.duration) return;
  scrub.value = String(Math.round((video.currentTime / video.duration) * 1000));
  timeLabel.textContent = `${fmtTime(video.currentTime)} / ${fmtTime(video.duration)}`;
}

document.getElementById("btnLoad")!.addEventListener("click", () => fileVideo.click());
fileVideo.addEventListener("change", async () => {
  const f = fileVideo.files?.[0];
  if (!f) return;
  const url = URL.createObjectURL(f);
  video.src = url;
  await new Promise<void>((resolve) => {
    video.onloadedmetadata = () => resolve();
  });
  hasVideo = true;
  emptyState.classList.add("hidden");
  btnPlay.disabled = false;
  scrub.disabled = false;
  btnExport.disabled = false;
  video.currentTime = 0.01;
  drawOnce();
  updateTransport();
});

document.getElementById("btnTpl")!.addEventListener("click", () => fileTpl.click());
fileTpl.addEventListener("change", async () => {
  const f = fileTpl.files?.[0];
  if (!f) return;
  const text = await f.text();
  try {
    const json = JSON.parse(text);
    project = importVctpl(json, project.canvas_w, project.canvas_h);
    graph.setProject(project);
    drawOnce();
  } catch (err) {
    alert(`Couldn't read template: ${(err as Error).message}`);
  }
  fileTpl.value = "";
});

btnPlay.addEventListener("click", () => {
  if (video.paused) { video.play(); btnPlay.textContent = "⏸"; }
  else { video.pause(); btnPlay.textContent = "▶"; }
});
video.addEventListener("pause", () => { btnPlay.textContent = "▶"; drawOnce(); });
video.addEventListener("play", () => { btnPlay.textContent = "⏸"; });

let scrubbing = false;
scrub.addEventListener("input", () => {
  scrubbing = true;
  if (video.duration) {
    video.currentTime = (parseInt(scrub.value, 10) / 1000) * video.duration;
    drawOnce();
  }
});
scrub.addEventListener("change", () => { scrubbing = false; });
video.addEventListener("seeked", () => { if (!scrubbing) drawOnce(); });

btnNodes.addEventListener("click", () => {
  nodePanel.classList.toggle("open");
});

document.getElementById("btnAddRegion")!.addEventListener("click", () => {
  addRegion(project);
  graph.setProject(project);
  drawOnce();
});

document.getElementById("btnSaveProj")!.addEventListener("click", async () => {
  await saveProjectLocal("last", project);
  const btn = document.getElementById("btnSaveProj")!;
  const old = btn.textContent;
  btn.textContent = "Saved";
  setTimeout(() => { btn.textContent = old; }, 900);
});

btnExport.addEventListener("click", async () => {
  if (!hasVideo) return;
  btnExport.disabled = true;
  const originalText = btnExport.textContent;
  video.currentTime = 0;
  video.muted = false;
  await new Promise((r) => (video.onseeked = r));
  await video.play();
  const durationSec = video.duration;
  try {
    const blob = await recordComposite(canvas, video, {
      fps: 30,
      durationSec,
      onProgress: (frac) => { btnExport.textContent = `Exporting ${Math.round(frac * 100)}%`; },
    });
    video.pause();
    const ext = extForMime(blob.type);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${project.name || "clip"}.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  } finally {
    btnExport.textContent = originalText;
    btnExport.disabled = false;
  }
});

(async () => {
  const saved = await loadProjectLocal("last");
  if (saved) {
    project = saved;
    graph.setProject(project);
  }
})();

if ("serviceWorker" in navigator) {
  // registered by vite-plugin-pwa's virtual module in production builds
}
