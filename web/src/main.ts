import "./style.css";
import { Compositor } from "./render/compositor";
import { NodeGraph } from "./ui/nodegraph";
import {
  newProject, addRegion, saveProjectLocal, loadProjectLocal,
  saveTemplateLocal, loadTemplateLocal, listLocalTemplateNames, deleteTemplateLocal,
} from "./core/project";
import { importVctpl } from "./core/vctpl";
import { recordComposite, extForMime } from "./export";
import { driveConfigured, getAccessToken, handleAuthRedirectReturn } from "./drive";
import { DriveBrowser } from "./ui/drive-browser";
import type { Project } from "./core/types";

const app = document.getElementById("app")!;
app.innerHTML = `
  <div class="topbar">
    <h1>CLIPR</h1>
    <button class="btn icon" id="btnLoad" title="Load video">📂 Video</button>
    <button class="btn icon" id="btnDrive" title="Load from Google Drive">🔵 Drive</button>
    <button class="btn icon" id="btnTpl" title="Import template">🧩 Template</button>
    <span class="spacer"></span>
    <button class="btn icon" id="btnNodes" title="Toggle node view">🧠</button>
    <button class="btn primary" id="btnExport" disabled>Export</button>
  </div>
  <div class="preview-wrap">
    <canvas id="previewCanvas"></canvas>
    <div class="empty-state hidden" id="emptyState">Load a video to start reframing.</div>
    <div class="loading-overlay hidden" id="loadingOverlay">
      <div class="spinner"></div>
      <div class="loading-label" id="loadingLabel">Loading video…</div>
    </div>
  </div>
  <div class="transport">
    <button class="btn icon" id="btnPlay" disabled>▶</button>
    <div class="scrub-wrap">
      <div class="trim-overlay" id="trimOverlay"></div>
      <input type="range" id="scrub" min="0" max="1000" value="0" disabled />
    </div>
    <span class="time-label" id="timeLabel">0:00 / 0:00</span>
  </div>
  <div class="trimbar">
    <button class="btn icon" id="btnMarkIn" disabled title="Set in point to playhead">[ In</button>
    <span class="time-label" id="trimLabel">0:00 – 0:00</span>
    <button class="btn icon" id="btnMarkOut" disabled title="Set out point to playhead">Out ]</button>
    <span class="spacer"></span>
    <button class="btn icon" id="btnTrimReset" disabled title="Reset trim to full clip">↺</button>
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
  <input type="file" id="fileVideo" class="hidden" />
  <input type="file" id="fileTpl" accept=".vctpl,application/json" class="hidden" />
  <div class="modal-backdrop hidden" id="tplModal">
    <div class="modal">
      <div class="modal-head">
        <span>Templates</span>
        <span class="del" id="tplClose">✕</span>
      </div>
      <div class="modal-body" id="tplList"></div>
      <div class="modal-foot">
        <button class="btn" id="btnSaveAsTpl">Save current as template</button>
        <button class="btn" id="btnImportFile">Import .vctpl file</button>
      </div>
    </div>
  </div>
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
const btnMarkIn = document.getElementById("btnMarkIn") as HTMLButtonElement;
const btnMarkOut = document.getElementById("btnMarkOut") as HTMLButtonElement;
const btnTrimReset = document.getElementById("btnTrimReset") as HTMLButtonElement;
const trimLabel = document.getElementById("trimLabel") as HTMLSpanElement;
const trimOverlay = document.getElementById("trimOverlay") as HTMLDivElement;

let trimIn = 0;
let trimOut = 0;

function updateTrimUi() {
  trimLabel.textContent = `${fmtTime(trimIn)} – ${fmtTime(trimOut)}`;
  if (video.duration) {
    const l = (trimIn / video.duration) * 100;
    const r = (1 - trimOut / video.duration) * 100;
    trimOverlay.style.left = `${l}%`;
    trimOverlay.style.right = `${r}%`;
  }
}

let project: Project = newProject();
const compositor = new Compositor(canvas);
const video = document.createElement("video");
video.playsInline = true;
video.muted = false;
video.preload = "auto";
// iOS WebKit (Safari/Edge/Chrome all run WebKit there) is unreliable about
// firing loadedmetadata/decoding frames for a <video> that's never attached
// to the DOM - keep it real but invisible rather than detached. It also
// needs a real (non-near-zero) rendered size: some hardware-decode paths
// silently stop producing actual frame data (audio keeps playing, video
// stays black) when the element's box is ~0x0, so this is off-screen via
// position, not shrunk to nothing.
video.style.position = "fixed";
video.style.left = "-9999px";
video.style.top = "0";
video.style.width = "480px";
video.style.height = "270px";
video.style.opacity = "0";
video.style.pointerEvents = "none";
document.body.appendChild(video);

let rafId = 0;
let hasVideo = false;
const vfcSupported = typeof (video as any).requestVideoFrameCallback === "function";

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

// requestVideoFrameCallback (Safari 15.4+, Chrome 83+) guarantees a real
// decoded frame is behind video.videoWidth/videoHeight at the moment it
// fires - plain requestAnimationFrame + reading those properties does NOT
// give that guarantee on WebKit, which is a documented cause of canvas/
// WebGL capture from <video> staying black (audio plays fine since decode
// itself isn't the problem, just the frame-readiness signal we were using).
function vfcLoop() {
  if (!hasVideo) return;
  compositor.uploadFrame(video, video.videoWidth, video.videoHeight);
  compositor.draw(project);
  updateTransport();
  (video as any).requestVideoFrameCallback(vfcLoop);
}

function loop() {
  if (hasVideo && !video.paused && !video.ended) {
    compositor.uploadFrame(video, video.videoWidth, video.videoHeight);
    compositor.draw(project);
    updateTransport();
  }
  rafId = requestAnimationFrame(loop);
}

if (vfcSupported) {
  (video as any).requestVideoFrameCallback(vfcLoop);
} else {
  rafId = requestAnimationFrame(loop);
}

function mediaErrorText(err: MediaError | null): string {
  if (!err) return "unknown decode error";
  switch (err.code) {
    case MediaError.MEDIA_ERR_ABORTED: return "load was aborted";
    case MediaError.MEDIA_ERR_NETWORK: return "network error while reading the file";
    case MediaError.MEDIA_ERR_DECODE: return "the file is corrupt or uses an unsupported codec";
    case MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED: return "this browser can't play that format/codec (common with HEVC .mov or unusual containers - try re-exporting as H.264 mp4)";
    default: return err.message || "unknown decode error";
  }
}

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

const loadingOverlay = document.getElementById("loadingOverlay") as HTMLDivElement;
const loadingLabel = document.getElementById("loadingLabel") as HTMLDivElement;
const loadingReasons = new Set<string>();

function showLoading(reason: string, label: string) {
  loadingReasons.add(reason);
  loadingLabel.textContent = label;
  loadingOverlay.classList.remove("hidden");
}
function hideLoading(reason: string) {
  loadingReasons.delete(reason);
  if (loadingReasons.size === 0) loadingOverlay.classList.add("hidden");
}

async function loadVideoBlob(blob: Blob, name: string) {
  showLoading("load", `Loading ${name}…`);
  try {
    const url = URL.createObjectURL(blob);
    video.src = url;
    video.load();
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error("timed out - the file may still be downloading from Drive/iCloud, or the format isn't supported on this browser")),
        20_000
      );
      video.onloadedmetadata = () => { clearTimeout(timeout); resolve(); };
      video.onerror = () => { clearTimeout(timeout); reject(new Error(mediaErrorText(video.error))); };
    });
    hasVideo = true;
    emptyState.classList.add("hidden");
    btnPlay.disabled = false;
    scrub.disabled = false;
    btnExport.disabled = false;
    btnMarkIn.disabled = false;
    btnMarkOut.disabled = false;
    btnTrimReset.disabled = false;
    trimIn = 0;
    trimOut = video.duration;
    updateTrimUi();
    video.currentTime = 0.01;
    await new Promise<void>((resolve) => { video.onseeked = () => resolve(); });
    drawOnce();
    updateTransport();
  } catch (err) {
    const mb = (blob.size / (1024 * 1024)).toFixed(1);
    alert(
      `Couldn't load that video: ${(err as Error).message ?? err}\n\n` +
      `File: ${name}\nReported type: ${blob.type || "(none)"}\nSize: ${mb} MB`
    );
  } finally {
    hideLoading("load");
  }
}

document.getElementById("btnLoad")!.addEventListener("click", () => fileVideo.click());
fileVideo.addEventListener("change", async () => {
  const f = fileVideo.files?.[0];
  if (!f) return;
  await loadVideoBlob(f, f.name);
  fileVideo.value = "";
});

const btnDrive = document.getElementById("btnDrive") as HTMLButtonElement;
if (!driveConfigured()) {
  btnDrive.title = "Drive isn't set up yet";
  btnDrive.style.opacity = "0.5";
}

async function openDriveBrowser() {
  if (!driveConfigured()) {
    alert("Drive isn't set up yet (missing Google Client ID)");
    return;
  }
  const token = await getAccessToken();
  if (!token) return; // getAccessToken() already started a redirect to sign in
  const browser = new DriveBrowser(token);
  await browser.open();
  // Drive hands the actual file off to Safari's own download/media handling
  // (see drive-browser.ts) rather than fetching it in-page, since iOS kills
  // a page-driven fetch the moment it's backgrounded. Re-import the result
  // via the normal "Video" button once it's saved.
}

btnDrive.addEventListener("click", () => { openDriveBrowser(); });

// Coming back from Google's sign-in redirect: exchange the code left in the
// URL for tokens, and if the Drive browser was open when we left, reopen it
// automatically instead of leaving the user to tap the button again.
(async () => {
  const { pendingPick } = await handleAuthRedirectReturn();
  if (pendingPick) openDriveBrowser();
})();

// Buffering during playback/seek (relevant for large or cloud-sourced clips)
// reuses the same overlay so a stall never looks like a frozen app.
video.addEventListener("waiting", () => showLoading("buffer", "Buffering…"));
video.addEventListener("playing", () => hideLoading("buffer"));
video.addEventListener("canplay", () => hideLoading("buffer"));

interface BundledTplEntry { file: string; name: string; game: string; tags: string[]; notes: string; }
let bundledTpls: BundledTplEntry[] | null = null;

const tplModal = document.getElementById("tplModal") as HTMLDivElement;
const tplList = document.getElementById("tplList") as HTMLDivElement;

async function openTemplateModal() {
  tplModal.classList.remove("hidden");
  tplList.innerHTML = `<div class="tpl-empty">Loading…</div>`;
  if (!bundledTpls) {
    try {
      const res = await fetch("templates/index.json");
      bundledTpls = await res.json();
    } catch {
      bundledTpls = [];
    }
  }
  const mine = await listLocalTemplateNames();
  tplList.innerHTML = "";

  const mineTitle = document.createElement("div");
  mineTitle.className = "tpl-group-title";
  mineTitle.textContent = "My templates";
  tplList.appendChild(mineTitle);
  if (!mine.length) {
    const empty = document.createElement("div");
    empty.className = "tpl-empty";
    empty.textContent = "None saved yet on this device.";
    tplList.appendChild(empty);
  }
  for (const name of mine) {
    const item = document.createElement("div");
    item.className = "tpl-item";
    item.innerHTML = `<div><div class="name">${escapeHtml(name)}</div><div class="meta">saved on this device</div></div><span class="tpl-del">✕</span>`;
    item.addEventListener("click", async (e) => {
      if ((e.target as HTMLElement).classList.contains("tpl-del")) {
        await deleteTemplateLocal(name);
        openTemplateModal();
        return;
      }
      const p = await loadTemplateLocal(name);
      if (p) applyProject(p);
      tplModal.classList.add("hidden");
    });
    tplList.appendChild(item);
  }

  const builtinTitle = document.createElement("div");
  builtinTitle.className = "tpl-group-title";
  builtinTitle.textContent = "Built-in (from desktop CLIPR)";
  tplList.appendChild(builtinTitle);
  for (const t of bundledTpls ?? []) {
    const item = document.createElement("div");
    item.className = "tpl-item";
    item.innerHTML = `<div><div class="name">${escapeHtml(t.name)}</div><div class="meta">${escapeHtml(t.game || t.notes || "")}</div></div>`;
    item.addEventListener("click", async () => {
      const res = await fetch(`templates/${encodeURIComponent(t.file)}`);
      const json = await res.json();
      applyProject(importVctpl(json, project.canvas_w, project.canvas_h));
      tplModal.classList.add("hidden");
    });
    tplList.appendChild(item);
  }
}

function applyProject(p: Project) {
  project = p;
  graph.setProject(project);
  drawOnce();
}

function escapeHtml(s: string): string {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

document.getElementById("btnTpl")!.addEventListener("click", openTemplateModal);
document.getElementById("tplClose")!.addEventListener("click", () => tplModal.classList.add("hidden"));
tplModal.addEventListener("click", (e) => { if (e.target === tplModal) tplModal.classList.add("hidden"); });

document.getElementById("btnImportFile")!.addEventListener("click", () => fileTpl.click());
fileTpl.addEventListener("change", async () => {
  const f = fileTpl.files?.[0];
  if (!f) return;
  const text = await f.text();
  try {
    const json = JSON.parse(text);
    applyProject(importVctpl(json, project.canvas_w, project.canvas_h));
    tplModal.classList.add("hidden");
  } catch (err) {
    alert(`Couldn't read template: ${(err as Error).message}`);
  }
  fileTpl.value = "";
});

document.getElementById("btnSaveAsTpl")!.addEventListener("click", async () => {
  const name = prompt("Save current layout as:", project.name || "My template");
  if (!name) return;
  await saveTemplateLocal(name, project);
  openTemplateModal();
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

btnMarkIn.addEventListener("click", () => {
  trimIn = Math.min(video.currentTime, trimOut - 0.05);
  trimIn = Math.max(0, trimIn);
  updateTrimUi();
});
btnMarkOut.addEventListener("click", () => {
  trimOut = Math.max(video.currentTime, trimIn + 0.05);
  trimOut = Math.min(video.duration, trimOut);
  updateTrimUi();
});
btnTrimReset.addEventListener("click", () => {
  trimIn = 0;
  trimOut = video.duration;
  updateTrimUi();
});

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
  video.currentTime = trimIn;
  video.muted = false;
  await new Promise((r) => (video.onseeked = r));
  await video.play();
  const durationSec = trimOut - trimIn;
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
