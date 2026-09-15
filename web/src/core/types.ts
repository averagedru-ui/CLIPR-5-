// Geometry/param schema mirrors vcomp/nodes/region.py + layout.py so .vctpl
// templates authored on desktop CLIPR load here unmodified (subset of fields).

export type Shape = "rect" | "rounded_rect" | "ellipse" | "polygon";
export type Anchor =
  | "top-left" | "top-center" | "top-right"
  | "center-left" | "center" | "center-right"
  | "bottom-left" | "bottom-center" | "bottom-right";

export interface Rect { x: number; y: number; w: number; h: number; }
export interface Radii { x: number; y: number; z: number; w: number; } // per-corner, matches RECT param order

export interface RegionNode {
  id: string;
  kind: "region";
  label: string;
  shape: Shape;
  source_rect: Rect;
  corner_radii: Radii;
  polygon_points: string; // "x,y;x,y;..." in 0..1 quad space
  anchor: Anchor;
  reference_height: number;
  dest_x: number;
  dest_y: number;
  dest_scale: number;
  dest_scale_x: number;
  dest_scale_y: number;
  link_scale: boolean;
  rotation: number; // degrees
  dest_anchor: Anchor;
  flip_h: boolean;
  flip_v: boolean;
  feather: number; // canvas px
  mask_expand: number;
  crop_left: number;
  crop_right: number;
  crop_top: number;
  crop_bottom: number;
  opacity: number;
  outline_width: number;
  outline_color: [number, number, number, number];
  shadow_enabled: boolean;
  shadow_blur: number;
  shadow_offset_y: number;
  shadow_opacity: number;
  solo: boolean;
  x: number; // node-graph canvas position
  y: number;
}

export interface OutputNode {
  id: string;
  kind: "output";
  x: number;
  y: number;
}

export interface SourceNode {
  id: string;
  kind: "source";
  x: number;
  y: number;
}

export type GraphNode = RegionNode | OutputNode | SourceNode;

export interface Wire {
  from: string; // node id
  to: string;   // node id
}

export interface Project {
  name: string;
  canvas_w: number;
  canvas_h: number;
  nodes: GraphNode[];
  wires: Wire[];
}

export const ANCHOR_UV: Record<Anchor, [number, number]> = {
  "top-left": [0, 0], "top-center": [0.5, 0], "top-right": [1, 0],
  "center-left": [0, 0.5], "center": [0.5, 0.5], "center-right": [1, 0.5],
  "bottom-left": [0, 1], "bottom-center": [0.5, 1], "bottom-right": [1, 1],
};

// Grid layout for region cards on the node canvas. A single-column stack
// with a small fixed offset per card looked fine with 1-2 regions but badly
// overlapped with a real template's 8-12 regions, since each card is
// 300-450px tall depending on shape/content - far more than any small
// fixed offset accounted for.
const REGION_GRID_COLS = 3;
const REGION_GRID_COL_W = 260;
const REGION_GRID_ROW_H = 460;
const REGION_GRID_START_X = 280;
const REGION_GRID_START_Y = 40;

export function regionGridPos(index: number): { x: number; y: number } {
  const col = index % REGION_GRID_COLS;
  const row = Math.floor(index / REGION_GRID_COLS);
  return {
    x: REGION_GRID_START_X + col * REGION_GRID_COL_W,
    y: REGION_GRID_START_Y + row * REGION_GRID_ROW_H,
  };
}

export function outputNodePos(): { x: number; y: number } {
  return { x: REGION_GRID_START_X + REGION_GRID_COLS * REGION_GRID_COL_W + 40, y: REGION_GRID_START_Y };
}

export function defaultRegion(id: string, x: number, y: number): RegionNode {
  return {
    id, kind: "region", label: "Region",
    shape: "rect",
    source_rect: { x: 0.0, y: 0.0, w: 0.2, h: 0.2 },
    corner_radii: { x: 0, y: 0, z: 0, w: 0 },
    polygon_points: "",
    anchor: "top-left",
    reference_height: 1080,
    dest_x: 0.5, dest_y: 0.15,
    dest_scale: 1.0, dest_scale_x: 1.0, dest_scale_y: 1.0, link_scale: true,
    rotation: 0,
    dest_anchor: "center",
    flip_h: false, flip_v: false,
    feather: 0, mask_expand: 0,
    crop_left: 0, crop_right: 0, crop_top: 0, crop_bottom: 0,
    opacity: 1,
    outline_width: 0, outline_color: [1, 1, 1, 1],
    shadow_enabled: false, shadow_blur: 6, shadow_offset_y: 8, shadow_opacity: 0.5,
    solo: false,
    x, y,
  };
}
