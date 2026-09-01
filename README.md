# VCOMP

Node-based compositor that turns 16:9 gameplay recordings into 9:16 vertical
clips **without cropping away the HUD**. Windows desktop app.

Status: **M7 — templates**. `.vctpl` save/load with versioned migration;
apply remaps every HUD Region source rect from the template's reference
resolution to the current clip (anchor + relative/fixed + ultrawide policy),
preserving the loaded clip. Template browser, Save-as-Template with thumbnail,
11 built-in starter templates, `.vcproj` projects with media relink, batch
export.

## Dev setup

```
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

### Vendored ffmpeg

The app never uses ffmpeg from `PATH`. Place static builds here:

```
vendor/ffmpeg/ffmpeg.exe
vendor/ffmpeg/ffprobe.exe
```

These are git-ignored. Get a static build from https://www.gyan.dev/ffmpeg/builds/
or https://github.com/BtbN/FFmpeg-Builds. `ffprobe.exe` is still required
(only `ffmpeg.exe` is present after the M0 stopgap copy).

## Tests

```
.venv\Scripts\pytest -q
```

## Layout

See the module tree under `vcomp/`. GPU code stays in `vcomp/render/`; `vcomp/core/`
and `vcomp/nodes/` stay Qt-free so the graph can be evaluated headlessly.

## Milestones

M0 scaffold · M1 media+preview · M2 render core · M3 node system · M4 masks ·
M5 backgrounds+modifiers · M6 export · M7 templates · M8 polish+package
