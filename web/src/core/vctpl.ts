import { nextId } from "./project";
import type { Anchor, Project, RegionNode, Shape } from "./types";
import { defaultRegion } from "./types";

// Reads a desktop CLIPR .vctpl (JSON). Pulls only "HUD Region" nodes (the
// per-element overlays) into the mobile project's flat region list; desktop-only
// structural nodes (Main Framing, Blur Background, Stack, Clip Source) are not
// represented here since the mobile pipeline always does cover-fit background
// + region overlays.
export function importVctpl(json: any, canvasW: number, canvasH: number): Project {
  const nodes: RegionNode[] = [];
  const graphNodes: any[] = json?.graph?.nodes ?? [];
  let i = 0;
  for (const gn of graphNodes) {
    if (gn.type !== "HUD Region" && gn.type !== "Facecam") continue;
    const v = (name: string, fallback: any) => gn.params?.[name]?.value ?? fallback;
    const base = defaultRegion(nextId("region"), 280, 40 + i * 210);
    i += 1;
    const sr = v("source_rect", [0, 0, 0.2, 0.2]);
    const cr = v("corner_radii", [0, 0, 0, 0]);
    const region: RegionNode = {
      ...base,
      label: gn.title ?? gn.type ?? base.label,
      shape: (v("shape", "rect") as Shape) ?? (gn.type === "Facecam" ? "rounded_rect" : "rect"),
      source_rect: { x: sr[0], y: sr[1], w: sr[2], h: sr[3] },
      corner_radii: { x: cr[0], y: cr[1], z: cr[2], w: cr[3] },
      polygon_points: v("polygon_points", ""),
      anchor: v("anchor", "top-left") as Anchor,
      reference_height: v("reference_height", 1080),
      dest_x: v("dest_x", 0.5),
      dest_y: v("dest_y", 0.15),
      dest_scale: v("dest_scale", 1),
      dest_scale_x: v("dest_scale_x", 1),
      dest_scale_y: v("dest_scale_y", 1),
      link_scale: v("link_scale", true),
      rotation: v("rotation", 0),
      dest_anchor: v("dest_anchor", "center") as Anchor,
      flip_h: v("flip_h", false),
      flip_v: v("flip_v", false),
      feather: v("feather", 0),
      mask_expand: v("mask_expand", 0),
      crop_left: v("crop_left", 0),
      crop_right: v("crop_right", 0),
      crop_top: v("crop_top", 0),
      crop_bottom: v("crop_bottom", 0),
      opacity: v("opacity", 1),
      outline_width: v("outline_width", 0),
      outline_color: v("outline_color", [1, 1, 1, 1]),
      shadow_enabled: v("shadow_enabled", false),
      shadow_blur: v("shadow_blur", 6),
      shadow_offset_y: v("shadow_offset_y", 8),
      shadow_opacity: v("shadow_opacity", 0.5),
      solo: false,
    };
    nodes.push(region);
  }

  return {
    name: json?.meta?.name ?? "Imported",
    canvas_w: json?.canvas?.width ?? canvasW,
    canvas_h: json?.canvas?.height ?? canvasH,
    nodes: [
      { id: "source", kind: "source", x: 40, y: 40 },
      { id: "output", kind: "output", x: 280 + i * 0 + 260, y: 40 },
      ...nodes,
    ],
    wires: [],
  };
}
