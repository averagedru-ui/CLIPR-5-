export interface RecordOptions {
  fps: number;
  durationSec: number;
  onProgress?: (frac: number) => void;
}

function pickMime(): string {
  const candidates = [
    "video/mp4;codecs=avc1.640028",
    "video/mp4",
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ];
  for (const c of candidates) {
    if ((window as any).MediaRecorder?.isTypeSupported?.(c)) return c;
  }
  return "video/webm";
}

// Records the live composited canvas (already being driven by the caller's
// render loop) plus the source video's own audio track, via MediaRecorder.
export async function recordComposite(
  canvas: HTMLCanvasElement,
  audioSource: HTMLVideoElement,
  opts: RecordOptions
): Promise<Blob> {
  const mimeType = pickMime();
  const canvasStream = (canvas as any).captureStream(opts.fps) as MediaStream;
  const tracks: MediaStreamTrack[] = [...canvasStream.getVideoTracks()];

  let audioStream: MediaStream | null = null;
  try {
    audioStream = (audioSource as any).captureStream?.() ?? null;
    if (audioStream) {
      const at = audioStream.getAudioTracks();
      if (at.length) tracks.push(at[0]);
    }
  } catch {
    // no audio track available (e.g. muted decode path) - export video-only
  }

  const mixed = new MediaStream(tracks);
  const recorder = new MediaRecorder(mixed, { mimeType, videoBitsPerSecond: 12_000_000 });
  const chunks: Blob[] = [];
  recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };

  const done = new Promise<Blob>((resolve) => {
    recorder.onstop = () => resolve(new Blob(chunks, { type: mimeType }));
  });

  recorder.start(250);
  const start = performance.now();
  const total = opts.durationSec * 1000;
  await new Promise<void>((resolve) => {
    const tick = () => {
      const elapsed = performance.now() - start;
      opts.onProgress?.(Math.min(1, elapsed / total));
      if (elapsed >= total) { resolve(); return; }
      requestAnimationFrame(tick);
    };
    tick();
  });
  recorder.stop();
  return done;
}

export function extForMime(mime: string): string {
  return mime.includes("mp4") ? "mp4" : "webm";
}
