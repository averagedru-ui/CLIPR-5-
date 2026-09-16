# CLIPR iOS (native Xcode/Swift) — handoff doc

Give this whole file to Claude Code in Terminal on the Mac as the first
message in a fresh session, in this cloned repo. It's the domain knowledge
needed to rebuild the mobile client natively without re-deriving or
re-breaking things that already got fixed the hard way once.

**This doc is a summary, not the source of truth for exact look/behavior.**
The actual working PWA is committed in this same repo at `web/` (all
TypeScript) - when a description below isn't precise enough (exact colors,
spacing, interaction details, the precise shader math, etc.), **read the
real source there instead of guessing from this doc's prose.** Particularly:
`web/src/style.css` (the current neutral-dark/blue-accent palette, sizing),
`web/src/render/compositor.ts` + `shaders.ts` (the exact region placement
+ shape-mask rendering, WebGL2 but the math translates directly),
`web/src/main.ts` (overall app flow/state), `web/src/ui/nodegraph.ts` (the
node-canvas pan/zoom/pinch + slider-with-step-buttons UI), `web/src/drive.ts`
+ `web/src/ui/drive-browser.ts` (the Drive integration this doc describes
at a high level). If the user says something doesn't "look/run like what we
built," this is why - go read the actual code, don't re-derive intent from
memory of this summary.

## What this project is

CLIPR is a personal (not App Store, not multi-user) tool that reframes 16:9
gameplay recordings into 9:16 vertical clips while **preserving HUD
elements** by letting the user mask/reposition them onto the vertical
canvas, instead of just center-cropping and losing them. There's a desktop
Windows app (Python/PySide6/moderngl, full node graph editor — **not part of
this port, stays as-is, maintained in a separate Claude Code session on
Windows**) and there *was* a mobile PWA (`web/`, TypeScript/Vite/WebGL2) that
this native rebuild is replacing. The PWA's code won't port directly, but
the geometry math, the template file format, and several hard-won iOS
lessons below absolutely should.

**Decision already made, don't re-litigate:** native Swift instead of
continuing the PWA. Reasoning: the PWA hit real, unfixable-from-JS iOS
limits — no background downloads (a page-driven fetch dies the instant
Safari is backgrounded, confirmed via an actual tab crash on a large file),
PWA service-worker cache/update fights that cost multiple debugging rounds,
OAuth requiring an ugly redirect-flow + server-side token-exchange dance.
Native fixes all of that (`URLSession` background tasks, `ASWebAuthenticationSession`
+ Keychain, no service worker at all). **One thing native does NOT fix:**
AVFoundation uses the same hardware video decoders as Safari/WebKit
(VideoToolbox) — a clip encoded in a codec the device's hardware decoder
doesn't support (AV1 is the confirmed real-world case here, see below) will
still fail to decode natively. That's a hardware limitation, not a
browser one.

## The .vctpl template format

Desktop templates are JSON files, `%APPDATA%\CLIPR\templates\*.vctpl` on
Windows (bundled built-ins ship in `vcomp/templates/builtin/`). Top-level
shape:

```json
{
  "format": "vctpl",
  "version": 1,
  "meta": { "name": "...", "game": "...", "author": "local", "created": "ISO8601", "tags": [...], "notes": "...", "thumbnail": "" },
  "reference_resolution": { "width": 1920, "height": 1080 },
  "canvas": { "width": 1080, "height": 1920, "fps": 30 },
  "graph": {
    "nodes": [ { "id": "...", "type": "...", "title": "...", "enabled": true, "params": { "<name>": { "value": ..., "keyframes": [] } } } ],
    "connections": [ { "from_node": "...", "from_port": "image", "to_node": "...", "to_port": "image" } ]
  }
}
```

Desktop node `type`s you'll see: `Clip Source`, `Main Framing`, `Blur
Background`, `Stack`, `Output`, `HUD Region` (the one the user creates
dozens of — HUD element masks), `Facecam` (webcam overlay, similar params
to HUD Region plus a `shape` default of `rounded_rect`).

**The PWA only ever imported `HUD Region` and `Facecam` nodes**, flattened
into a simple list, rendered as: full source frame cover-fit as background,
then every region drawn on top. It deliberately did NOT model `Main
Framing`/`Blur Background`/`Stack` (desktop's more complex compositing
nodes) — this was a known, accepted gap (see "Blur Background + Centered
Gameplay" complaint below). **Worth actually building properly natively**
since AVFoundation/Core Image make a letterbox+blur-backdrop pass
straightforward (far easier than it would have been in raw WebGL2) — ask
the user whether they want full node-graph parity or the same flattened
region-only approach the PWA used, now that the constraint that drove that
simplification (hand-rolling everything in WebGL2) doesn't really apply to
native.

Relevant `HUD Region`/`Facecam` params (there are more on desktop; these
are the ones the PWA read and that actually matter for placement):

| param | type | meaning |
|---|---|---|
| `shape` | enum | `rect` \| `rounded_rect` \| `ellipse` \| `polygon` |
| `source_rect` | [x,y,w,h] 0..1 | sub-rect of the source frame to sample |
| `corner_radii` | [tl,tr,br,bl] 0..1 | only for rounded_rect |
| `anchor` | enum | source-side anchor (rarely matters for placement math) |
| `reference_height` | int, default 1080 | **stable authoring constant, see below** |
| `dest_x`, `dest_y` | float, canvas 0..1 | placement anchor point on the vertical canvas |
| `dest_scale`, `dest_scale_x`, `dest_scale_y`, `link_scale` | float/bool | scale multiplier |
| `rotation` | degrees | |
| `dest_anchor` | enum, 9 values | which point of the region rect sits at (dest_x,dest_y) |
| `flip_h`, `flip_v` | bool | |
| `feather` | float, canvas px | edge softness |
| `opacity` | 0..1 | |

## THE PLACEMENT FORMULA — get this exactly right

This is the thing that broke repeatedly across this whole project (both
desktop and the PWA independently drifted from it at different points) and
is the most important thing in this handoff. **A region's on-canvas size
depends ONLY on `reference_height` and the source clip's ASPECT RATIO —
never on the clip's actual pixel dimensions.** This is deliberate: it's what
makes a saved placement reproduce identically for any clip of the same
aspect ratio (e.g. any 1920x1080 clip, regardless of whether a specific
file happens to be 1920x1080 or 2560x1440 — as long as the aspect matches,
same math, same answer). Getting this wrong (e.g. accidentally keying off
live pixel dimensions somewhere) is exactly what caused "template doesn't
match where I saved it" bugs, more than once, in both the desktop and PWA
codebases.

Desktop authoritative implementation — `vcomp/nodes/region.py`,
`HUDRegion.dest_rect_for()`:

```python
def dest_rect_for(self, canvas_w, canvas_h, src_w, src_h, dx=None, dy=None, scale=None):
    _, _, sw, sh = self.params["source_rect"].value
    src_w = src_w or canvas_w
    src_h = src_h or canvas_h
    ref_h = float(self.params["reference_height"].value)
    src_aspect = float(src_w) / max(1.0, float(src_h))
    reg_px_w = max(1.0, sw * ref_h * src_aspect)
    reg_px_h = max(1.0, sh * ref_h)

    scale = float(self.params["dest_scale"].value if scale is None else scale)
    linked = self.params["link_scale"].value
    scx = scale * (1.0 if linked else self.params["dest_scale_x"].value)
    scy = scale * (1.0 if linked else self.params["dest_scale_y"].value)
    dw = reg_px_w / canvas_w * scx
    dh = reg_px_h / canvas_h * scy

    dx = float(self.params["dest_x"].value if dx is None else dx)
    dy = float(self.params["dest_y"].value if dy is None else dy)
    ax, ay = anchor_uv(self.params["dest_anchor"].value)   # see table below
    x0, y0 = dx - ax * dw, dy - ay * dh
    return (x0, y0, x0 + dw, y0 + dh)   # canvas-space [0,1] rect
```

`src_w`/`src_h` here are the **current clip's actual decoded frame
dimensions** (not the canvas, not the template's `reference_resolution`) —
only their ratio (`src_aspect`) feeds the math, never their absolute
values. `canvas_w`/`canvas_h` are the output canvas pixel size (e.g.
1080x1920). All of `dest_x`, `dest_y`, `x0`, `y0`, `x1`, `y1` are in
canvas-normalized `[0,1]` space, `(0,0)` = top-left.

`anchor_uv` (`vcomp/core/coords.py`) — 9-point anchor names to `(x,y)` unit
fractions, standard 3x3 grid:

```
top-left(0,0) top-center(0.5,0) top-right(1,0)
center-left(0,0.5) center(0.5,0.5) center-right(1,0.5)
bottom-left(0,1) bottom-center(0.5,1) bottom-right(1,1)
```

The PWA's port of this (`web/src/render/compositor.ts`,
`destRectFor()`) is a faithful line-for-line translation of the above and
can be used as a second reference if the Python reads ambiguously in any
spot — TypeScript is arguably clearer for a Swift port anyway:

```typescript
destRectFor(region, canvasW, canvasH) {
  const { w: sw, h: sh } = region.source_rect;
  const srcW = this.texW || canvasW;   // current clip's decoded frame size
  const srcH = this.texH || canvasH;
  const refH = region.reference_height || 1080;
  const srcAspect = srcW / Math.max(1, srcH);
  const regPxW = Math.max(1, sw * refH * srcAspect);
  const regPxH = Math.max(1, sh * refH);
  const scale = region.dest_scale;
  const scx = scale * (region.link_scale ? 1 : region.dest_scale_x);
  const scy = scale * (region.link_scale ? 1 : region.dest_scale_y);
  const dw = (regPxW / canvasW) * scx;
  const dh = (regPxH / canvasH) * scy;
  const [ax, ay] = ANCHOR_UV[region.dest_anchor];
  const x0 = region.dest_x - ax * dw;
  const y0 = region.dest_y - ay * dh;
  return { x0, y0, x1: x0 + dw, y1: y0 + dh };
}
```

**Rotation** happens around the rect's own center, applied after computing
`(x0,y0,x1,y1)` — rotate the quad's corners around `((x0+x1)/2, (y0+y1)/2)`
before rasterizing.

**If a user reports placement drift again:** verify this formula is
implemented exactly as above FIRST, byte-for-byte, before looking anywhere
else — it has been the actual bug more than once, in more than one
codebase, and it's easy to accidentally reintroduce (e.g. by keying region
size off canvas dimensions instead of reference_height+aspect, or off the
template's `reference_resolution` instead of the live clip's actual decoded
size).

## Auth for Google Drive — do this differently than the PWA did

The PWA had to jump through real hoops because a browser SPA has no secure
place to hold a client secret: Authorization Code + PKCE, but Google still
requires the secret for the "Web application" OAuth client type even with
PKCE, so it needed a Vercel serverless function just to hide the secret,
plus a full-page-redirect dance because Google's popup-based sign-in breaks
in Safari/PWA contexts. **None of this applies natively.**

- Register a **new** OAuth client in the same Google Cloud project, type
  **iOS** (not Web application) — no client secret is issued for this type
  at all, nothing to hide, nothing server-side needed.
- Use `ASWebAuthenticationSession` for the sign-in UI (system-provided,
  handles the browser sheet + redirect-back-to-app automatically via a
  custom URL scheme or universal link).
- Store the refresh token in the **Keychain**, not `UserDefaults`/plist —
  this is the one place iOS actually gives you secure persistent storage,
  no reason to reinvent what the PWA had to (`localStorage`, the least-bad
  option available to a browser).
- Scope: `drive.readonly` if hand-rolling folder browsing UI (what the PWA
  did, and why — see below), or Google's Picker SDK if it has better native
  behavior than its web widget did (see next section).

## Google Picker (web widget) vs. hand-rolled Drive browsing

The PWA tried Google's Picker JS widget first and it was **broken in ways
that took 3 debugging rounds to conclude were unfixable from configuration**:
folders wouldn't open on tap (only worked via Picker's own internal search
box), the default view flattened into a cross-Drive "Recent" list instead
of real My Drive hierarchy, video files were inconsistently missing from
folders that clearly contained them. Ended up hand-rolling a folder browser
against the plain Drive REST API (`files.list` with a `'<id>' in parents`
query, `files.get?alt=media` for download) instead — full control, no more
guessing at undocumented widget internals.

**If a native Google Picker SDK exists for iOS, it may or may not have the
same problems** (the web widget's bugs might be web-specific) — worth a
quick eval, but don't be surprised if it needs the same hand-rolled
fallback. The Drive REST API approach is simple enough to just use directly
regardless: `GET https://www.googleapis.com/drive/v3/files?q='<parentId>'
in parents and trashed = false&fields=files(id,name,mimeType)` with a
`Bearer <token>` header, `application/vnd.google-apps.folder` is the folder
mimeType, filter files to `video/*` plus folders.

## Large file downloads — don't repeat the PWA's memory crash

The PWA's first attempt fetched a Drive file's bytes in-page and assembled
them into a Blob for immediate use — **this crashed the Safari tab outright**
on a real multi-hundred-MB gameplay clip (WKWebView's page memory ceiling).
Ended up with a size-based hybrid: small files (<300MB) fetch inline for a
smooth one-tap import, large files hand off to Safari's own downloader
(survives backgrounding, but costs a manual re-import step). **Native
doesn't need this compromise at all** — use `URLSession` background
download tasks (`URLSessionDownloadTask` via a background
`URLSessionConfiguration`), which are designed for exactly this: large
files, survives the app being backgrounded/suspended/killed, OS manages it.
Should be strictly better than anything the PWA could do — no size
threshold needed, no two-step UX compromise.

## Known real limitation — not fixable at any layer

**AV1-encoded clips don't play.** Confirmed root cause (not a guess): a
debug readout showed `readyState` reaching `HAVE_ENOUGH_DATA` (4) but
`videoWidth`/`videoHeight` staying `0x0` — WebKit recognized and decoded
the audio track fine, silently dropped the unsupported video track, and
still reported "loaded" because the audio stream buffered fine. Isolated
via the user's own Camera Roll video (plays fine, standard H.264/HEVC) vs.
their gameplay clips (AV1, don't). Root cause: their capture software
(OBS with NVENC) defaults to AV1 on newer GPUs; most iPhones lack a
hardware AV1 decoder. Fix given to the user: switch OBS's recording
encoder to **NVENC H.264** (Settings → Output → Recording tab → Encoder)
going forward. For existing AV1 clips, a standalone desktop re-encode tool
was built (`convert_for_mobile.py` / `build/convert_for_mobile.spec` →
`.exe`, lives in the main repo, not part of this iOS port) - re-encodes to
H.264 via the fastest available hardware encoder before the clip ever
reaches the phone. **AVFoundation uses the same hardware decoders as
WebKit** — this limitation carries over 1:1 to native. Don't attempt a
software AV1 decode fallback; not worth the complexity for a personal tool
when "fix the recording settings" is a one-time zero-cost fix.

## UI/UX lessons worth carrying over

- **Undo matters and is easy to get subtly wrong.** The PWA's history is
  snapshot-based (whole-project JSON, not command objects) — simpler and
  correct for a small plain-data model like this. One critical detail: a
  slider drag must push exactly ONE undo snapshot per drag *gesture*
  (captured at drag-start, before any value changes), not one per
  continuous input tick — otherwise one drag floods undo with dozens of
  near-identical steps. In UIKit/SwiftUI terms: snapshot on
  `UISlider`/`Slider` gesture-began, not on every `.onChanged`/valueChanged
  callback during a drag.
- **Sliders need visible numeric feedback AND coarse step buttons.** Pure
  touch sliders are too imprecise for exact values (landing on exactly `0`
  rotation, an exact crop edge). The PWA added +/- step buttons flanking
  each slider stepping by the slider's own step size. Worth the same
  treatment natively (a stepper alongside the slider, or long-press for
  fine adjustment — whatever's idiomatic for SwiftUI).
- **A flat node-graph-lite canvas (draggable cards, pinch-zoom, pan) is
  what the user actually wanted** on a phone screen over a literal
  wires-and-ports graph editor (explicitly said node-based "might be
  easier to fit everything since the node tree can move around" over a
  fixed panel — but also explicitly said node view shouldn't feel
  cramped). No wires were ever drawn in the PWA (flat pipeline: source →
  every region → output, implied not literal) — worth deciding fresh
  whether native should draw connections at all, now that a real canvas
  framework (SwiftUI + gestures, or a proper 2D scene graph) makes it less
  of an engineering lift than it was in hand-rolled DOM+CSS.
- Region cards auto-layout in a grid (3 columns, sized to the tallest
  card variant) — an earlier flat/linear offset badly overlapped with a
  real template's 8-12 regions. Worth the same grid-not-list approach
  natively if using auto-placed cards at all.

## Templates: how sync between desktop and native works — DECIDED

**Keep using the existing pipeline as-is, don't rebuild it.** The desktop
app already auto-mirrors every saved template into `web/public/templates/`
(`vcomp/templates/io.py`, `_mirror_to_mobile()`) whenever `save_template()`
runs; a `git push` deploys that to Vercel, which serves it as plain public
JSON at `https://clipr-studio.vercel.app/templates/index.json` (manifest:
`[{file, name, game, tags, notes}, ...]`) and
`https://clipr-studio.vercel.app/templates/<file>` per template (URL-encode
the filename - they contain spaces). **No auth needed to fetch these** -
confirmed via plain unauthenticated `curl` during the PWA's development,
they're public static files.

The native app should just do a normal `URLSession` GET to those same
URLs to list/fetch templates - full sync chain end to end:
**desktop save → git push → live on Vercel → native app fetches over
HTTPS.** This needn't involve Google Drive, app bundling, or a rebuild for
new templates at all. It's already live and already works; the only
native-side work is parsing the JSON (same shape documented above) and
downloading a `.vctpl` file when the user picks a template.

Don't reach for iCloud/Drive/bundling for this - they'd all be reinventing
something that's already running.
in the first Xcode-side conversation.

## Getting set up on the Mac — practical steps

1. **Xcode** from the Mac App Store (free). A free personal Apple ID is
   enough to build and run on the user's own iPhone via Xcode directly (no
   $99/year Apple Developer Program needed) — **but a free-account sideload
   expires after 7 days** and needs re-installing from Xcode to keep
   working. Worth flagging to the user early: fine during active
   development (rebuilding often anyway), but means the app will
   periodically "stop working" and need a fresh `Xcode → Run` if they go
   a week without touching it. The $99/year program removes that limit if
   it becomes annoying.
2. `git clone https://github.com/averagedru-ui/CLIPR-5-.git` (or the
   `Clipr-Studio` mirror, same content) on the Mac — gets this handoff
   doc, all the `.vctpl` templates (`vcomp/templates/builtin/` and
   whatever's mirrored in `web/public/templates/`), and the existing PWA
   source as a reference if useful.
3. Open Claude Code in Terminal, in that cloned repo directory, paste this
   file as the first message (or just tell it to read `IOS_HANDOFF.md`).
4. New Xcode project: SwiftUI App template, iOS target matching the user's
   device/iOS version. Suggest a subdirectory like `ios/` in this same repo
   (keeps it alongside the desktop app and old PWA rather than a wholly
   separate repo) unless the user prefers it split out — ask, don't assume.
5. New Google Cloud OAuth client, type iOS, in the same `clipr-studio`
   Cloud Console project already set up (Testing mode, user's own account
   as test user — already configured, just needs the additional client).

## What NOT to do

- Don't reintroduce the OAuth Web-application-client + server-secret
  dance — the whole reason it existed was "no secure secret storage in a
  browser," which isn't a constraint natively.
- Don't hold large downloaded video files fully in memory - use
  background download tasks writing to disk.
- Don't key region on-canvas size off the clip's live pixel
  dimensions, the template's `reference_resolution`, or the canvas size -
  ONLY `reference_height` + the current clip's aspect ratio, per the
  formula above.
- Don't assume Google's native Picker SDK works well without checking -
  the web one didn't, verify before building UI around it.
