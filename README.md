# CLIPR

Node-based compositor that turns 16:9 gameplay recordings into 9:16 vertical
clips **without cropping away the HUD**. Windows desktop app, fully offline.

Instead of cropping 1920×1080 down to a 9:16 slice (throwing away the minimap,
health bar, killfeed, …), you mask HUD regions out of the source frame and
reposition them onto the 1080×1920 canvas — usually into the letterbox bands
above and below the gameplay. A background (solid / gradient / image / blurred
gameplay) fills the rest. Every mask, transform and control is a node in a node
graph. Save a graph as a reusable **template** and apply it to any clip.

## Status

All milestones M0–M8 implemented. `pytest` green (68 tests, incl. the
golden-frame WYSIWYG check). PyInstaller `--onedir` build verified launching.

| Area | State |
|---|---|
| Media | PyAV decoder, frame-accurate PTS seek, LRU cache, VFR |
| Renderer | one moderngl offscreen compositor for preview **and** export |
| Nodes | 21 types: Clip/Image/Value/Color/Time/Expression, Main Framing, HUD Region, Facecam, Bar Layout, Solid/Gradient/Image/Blur backgrounds, Transform, Color Adjust, Blur, Key, Opacity, Text, Stack, Guides, Output |
| Editing | draw-to-create masks, handle editing + snapping in both viewports, undo/redo |
| Export | bundled ffmpeg, encoder detection, progress/cancel, audio mux, batch queue |
| Templates | `.vctpl` with resolution remap, browser, 11 built-ins |
| Projects | `.vcproj` with media relink, 60 s autosave + crash recovery |

## Dev setup

```
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

### Vendored ffmpeg (required)

The app never uses ffmpeg from `PATH`. Place static builds here:

```
vendor/ffmpeg/ffmpeg.exe
vendor/ffmpeg/ffprobe.exe   (optional; metadata falls back to PyAV)
```

Git-ignored. Static builds: https://www.gyan.dev/ffmpeg/builds/ or
https://github.com/BtbN/FFmpeg-Builds

## Tests

```
.venv\Scripts\pytest -q            # skips @slow export runs? no - runs all
.venv\Scripts\pytest -q -m "not slow"
```

## Headless render

```
.venv\Scripts\python main.py --render project.vcproj out.mp4
.venv\Scripts\python main.py --version
```

## Packaging

```
.venv\Scripts\pyinstaller --noconfirm build/clipr.spec
```

Produces `dist/CLIPR/CLIPR.exe` (onedir — fast startup, AV-friendly). Optional
installer: compile `build/installer.iss` with Inno Setup 6.

## Layout

`vcomp/core` (graph, params, coords, project, autosave — Qt-free) ·
`vcomp/media` (decode/probe) · `vcomp/render` (GL context, compositor, shaders,
frame pipeline) · `vcomp/nodes` (Qt-free node classes) · `vcomp/export`
(ffmpeg) · `vcomp/templates` · `vcomp/ui` (PySide6).

## Known limitations

- `.cube` LUT loading, dual-Kawase blur, "Detect Facecam", and the step-by-step
  template capture wizard are not implemented.
- Batch export uses a fixed 1080×1920@30 whole-clip range.
- Hardware encoders (NVENC/AMF/QSV) are detected but only libx264 is verified.
