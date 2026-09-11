import type { GraphNode, Project, RegionNode } from "../core/types";

export interface NodeGraphCallbacks {
  onChange: () => void;
  onSelect: (id: string | null) => void;
  onDelete: (id: string) => void;
}

const SHAPES = ["rect", "rounded_rect", "ellipse"] as const;
const ANCHORS = [
  "top-left", "top-center", "top-right",
  "center-left", "center", "center-right",
  "bottom-left", "bottom-center", "bottom-right",
] as const;

export class NodeGraph {
  private layer: HTMLDivElement;
  private panX = 20;
  private panY = 20;
  private zoom = 0.85;
  private dragCard: { id: string; startX: number; startY: number; nodeX: number; nodeY: number } | null = null;
  private panDrag: { startX: number; startY: number; panX: number; panY: number } | null = null;
  selectedId: string | null = null;

  constructor(private root: HTMLElement, private project: Project, private cb: NodeGraphCallbacks) {
    this.layer = document.createElement("div");
    this.layer.className = "nodelayer";
    this.root.appendChild(this.layer);
    this.root.addEventListener("pointerdown", (e) => this.onRootPointerDown(e));
    this.root.addEventListener("pointermove", (e) => this.onPointerMove(e));
    this.root.addEventListener("pointerup", () => this.onPointerUp());
    this.root.addEventListener("pointercancel", () => this.onPointerUp());
    this.root.addEventListener("wheel", (e) => this.onWheel(e), { passive: false });
    this.render();
  }

  setProject(p: Project) {
    this.project = p;
    this.render();
  }

  private applyTransform() {
    this.layer.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.zoom})`;
  }

  private onWheel(e: WheelEvent) {
    e.preventDefault();
    const delta = -e.deltaY * 0.0015;
    this.zoom = Math.min(1.6, Math.max(0.4, this.zoom + delta));
    this.applyTransform();
  }

  private onRootPointerDown(e: PointerEvent) {
    const target = e.target as HTMLElement;
    const card = target.closest(".node-card") as HTMLElement | null;
    if (card) {
      const id = card.dataset.id!;
      if (target.closest(".del")) {
        this.cb.onDelete(id);
        return;
      }
      if (target.closest("input") || target.closest("select")) {
        this.select(id);
        return;
      }
      const node = this.project.nodes.find((n) => n.id === id);
      if (!node) return;
      this.select(id);
      this.dragCard = { id, startX: e.clientX, startY: e.clientY, nodeX: node.x, nodeY: node.y };
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
      return;
    }
    this.select(null);
    this.panDrag = { startX: e.clientX, startY: e.clientY, panX: this.panX, panY: this.panY };
  }

  private onPointerMove(e: PointerEvent) {
    if (this.dragCard) {
      const dx = (e.clientX - this.dragCard.startX) / this.zoom;
      const dy = (e.clientY - this.dragCard.startY) / this.zoom;
      const node = this.project.nodes.find((n) => n.id === this.dragCard!.id);
      if (node) {
        node.x = this.dragCard.nodeX + dx;
        node.y = this.dragCard.nodeY + dy;
        const el = this.layer.querySelector(`[data-id="${node.id}"]`) as HTMLElement | null;
        if (el) { el.style.left = `${node.x}px`; el.style.top = `${node.y}px`; }
      }
    } else if (this.panDrag) {
      this.panX = this.panDrag.panX + (e.clientX - this.panDrag.startX);
      this.panY = this.panDrag.panY + (e.clientY - this.panDrag.startY);
      this.applyTransform();
    }
  }

  private onPointerUp() {
    this.dragCard = null;
    this.panDrag = null;
  }

  private select(id: string | null) {
    this.selectedId = id;
    this.layer.querySelectorAll(".node-card").forEach((el) => el.classList.remove("selected"));
    if (id) this.layer.querySelector(`[data-id="${id}"]`)?.classList.add("selected");
    this.cb.onSelect(id);
  }

  render() {
    this.layer.innerHTML = "";
    this.applyTransform();
    for (const node of this.project.nodes) {
      this.layer.appendChild(this.buildCard(node));
    }
  }

  private buildCard(node: GraphNode): HTMLElement {
    const el = document.createElement("div");
    el.className = "node-card";
    el.dataset.id = node.id;
    el.style.left = `${node.x}px`;
    el.style.top = `${node.y}px`;
    if (node.id === this.selectedId) el.classList.add("selected");

    const head = document.createElement("div");
    head.className = "node-head";
    const dot = document.createElement("span");
    dot.className = "dot";
    head.appendChild(dot);
    const title = document.createElement("span");
    title.textContent = node.kind === "region" ? (node as RegionNode).label || "Region"
      : node.kind === "source" ? "Source" : "Output";
    head.appendChild(title);
    if (node.kind === "region") {
      const del = document.createElement("span");
      del.className = "del";
      del.textContent = "✕";
      head.appendChild(del);
    }
    el.appendChild(head);

    if (node.kind === "region") {
      el.appendChild(this.buildRegionBody(node as RegionNode));
    } else {
      const body = document.createElement("div");
      body.className = "node-body";
      const hint = document.createElement("div");
      hint.style.fontSize = "11px";
      hint.style.color = "var(--text-dim)";
      hint.textContent = node.kind === "source" ? "Full frame, cover-fit" : "Final 9:16 canvas";
      body.appendChild(hint);
      el.appendChild(body);
    }
    return el;
  }

  private buildRegionBody(r: RegionNode): HTMLElement {
    const body = document.createElement("div");
    body.className = "node-body";

    const shapeRow = row("Shape");
    const shapeSel = document.createElement("select");
    for (const s of SHAPES) {
      const o = document.createElement("option");
      o.value = s; o.textContent = s.replace("_", " ");
      if (s === r.shape) o.selected = true;
      shapeSel.appendChild(o);
    }
    shapeSel.onchange = () => { r.shape = shapeSel.value as any; this.cb.onChange(); };
    shapeRow.appendChild(shapeSel);
    body.appendChild(shapeRow);

    body.appendChild(this.slider("Src X", r.source_rect.x, 0, 1, 0.005, (v) => { r.source_rect.x = v; }));
    body.appendChild(this.slider("Src Y", r.source_rect.y, 0, 1, 0.005, (v) => { r.source_rect.y = v; }));
    body.appendChild(this.slider("Src W", r.source_rect.w, 0.01, 1, 0.005, (v) => { r.source_rect.w = v; }));
    body.appendChild(this.slider("Src H", r.source_rect.h, 0.01, 1, 0.005, (v) => { r.source_rect.h = v; }));

    body.appendChild(this.slider("Pos X", r.dest_x, -0.5, 1.5, 0.005, (v) => { r.dest_x = v; }));
    body.appendChild(this.slider("Pos Y", r.dest_y, -0.5, 1.5, 0.005, (v) => { r.dest_y = v; }));
    body.appendChild(this.slider("Scale", r.dest_scale, 0.05, 4, 0.01, (v) => { r.dest_scale = v; }));
    body.appendChild(this.slider("Rotate", r.rotation, -180, 180, 1, (v) => { r.rotation = v; }));
    body.appendChild(this.slider("Feather", r.feather, 0, 128, 1, (v) => { r.feather = v; }));
    body.appendChild(this.slider("Opacity", r.opacity, 0, 1, 0.01, (v) => { r.opacity = v; }));

    if (r.shape === "rounded_rect") {
      body.appendChild(this.slider("Radius", r.corner_radii.x, 0, 1, 0.01, (v) => {
        r.corner_radii = { x: v, y: v, z: v, w: v };
      }));
    }

    const anchorRow = row("Anchor");
    const anchorSel = document.createElement("select");
    for (const a of ANCHORS) {
      const o = document.createElement("option");
      o.value = a; o.textContent = a;
      if (a === r.dest_anchor) o.selected = true;
      anchorSel.appendChild(o);
    }
    anchorSel.onchange = () => { r.dest_anchor = anchorSel.value as any; this.cb.onChange(); };
    anchorRow.appendChild(anchorSel);
    body.appendChild(anchorRow);

    return body;
  }

  private slider(label: string, value: number, min: number, max: number, step: number, apply: (v: number) => void): HTMLElement {
    const r = row(label);
    const input = document.createElement("input");
    input.type = "range";
    input.min = String(min); input.max = String(max); input.step = String(step);
    input.value = String(value);
    const val = document.createElement("span");
    val.className = "val";
    val.textContent = fmt(value);
    input.oninput = () => {
      const v = parseFloat(input.value);
      apply(v);
      val.textContent = fmt(v);
      this.cb.onChange();
    };
    r.appendChild(input);
    r.appendChild(val);
    return r;
  }
}

function row(label: string): HTMLElement {
  const r = document.createElement("div");
  r.className = "row";
  const l = document.createElement("label");
  l.textContent = label;
  r.appendChild(l);
  return r;
}

function fmt(v: number): string {
  return Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(2);
}
