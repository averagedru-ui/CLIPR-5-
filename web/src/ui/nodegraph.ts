import type { GraphNode, Project, RegionNode } from "../core/types";

export interface NodeGraphCallbacks {
  onChange: () => void;
  onSelect: (id: string | null) => void;
  onDelete: (id: string) => void;
  // Called once right before a discrete edit begins (slider drag start,
  // step-button click) so the caller can snapshot undo state - NOT called
  // on every 'input' tick during a drag, only once per gesture.
  onBeforeChange: () => void;
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
  private pointers = new Map<number, { x: number; y: number }>();
  private pinch: { startDist: number; startZoom: number; startPanX: number; startPanY: number } | null = null;
  selectedId: string | null = null;

  constructor(private root: HTMLElement, private project: Project, private cb: NodeGraphCallbacks) {
    this.layer = document.createElement("div");
    this.layer.className = "nodelayer";
    this.root.appendChild(this.layer);
    this.root.addEventListener("pointerdown", (e) => this.onRootPointerDown(e));
    this.root.addEventListener("pointermove", (e) => this.onPointerMove(e));
    this.root.addEventListener("pointerup", (e) => this.onPointerUp(e));
    this.root.addEventListener("pointercancel", (e) => this.onPointerUp(e));
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
    this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this.pointers.size >= 2) {
      // Second finger landed - abandon any single-finger card drag/pan and
      // start a pinch instead.
      this.dragCard = null;
      this.panDrag = null;
      this.startPinch();
      return;
    }

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

  private twoPointers(): [{ x: number; y: number }, { x: number; y: number }] | null {
    if (this.pointers.size < 2) return null;
    const pts = [...this.pointers.values()];
    return [pts[0], pts[1]];
  }

  private startPinch() {
    const pts = this.twoPointers();
    if (!pts) return;
    const [a, b] = pts;
    this.pinch = {
      startDist: Math.hypot(b.x - a.x, b.y - a.y) || 1,
      startZoom: this.zoom,
      startPanX: this.panX,
      startPanY: this.panY,
    };
  }

  private onPointerMove(e: PointerEvent) {
    if (this.pointers.has(e.pointerId)) {
      this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    }
    if (this.pinch) {
      const pts = this.twoPointers();
      if (!pts) return;
      const [a, b] = pts;
      const dist = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      const rect = this.root.getBoundingClientRect();
      const midX = (a.x + b.x) / 2 - rect.left;
      const midY = (a.y + b.y) / 2 - rect.top;
      const scale = dist / this.pinch.startDist;
      const newZoom = Math.min(1.6, Math.max(0.4, this.pinch.startZoom * scale));
      // keep the point under the fingers fixed on screen while zooming
      const contentX = (midX - this.pinch.startPanX) / this.pinch.startZoom;
      const contentY = (midY - this.pinch.startPanY) / this.pinch.startZoom;
      this.zoom = newZoom;
      this.panX = midX - contentX * newZoom;
      this.panY = midY - contentY * newZoom;
      this.applyTransform();
      return;
    }
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

  private onPointerUp(e: PointerEvent) {
    this.pointers.delete(e.pointerId);
    if (this.pointers.size < 2) this.pinch = null;
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

  // Two-line layout (label+value header, then step buttons flanking the
  // slider) instead of cramming label+slider+value into one row - on a
  // 240px card that squeezed the value text down to nothing and clipped it.
  // Step buttons exist because a touch slider alone is too imprecise to
  // land on values like an exact 0 rotation or a specific crop edge.
  private slider(label: string, value: number, min: number, max: number, step: number, apply: (v: number) => void): HTMLElement {
    const r = document.createElement("div");
    r.className = "row";

    const head = document.createElement("div");
    head.className = "row-head";
    const l = document.createElement("label");
    l.textContent = label;
    const val = document.createElement("span");
    val.className = "val";
    val.textContent = fmt(value);
    head.appendChild(l);
    head.appendChild(val);
    r.appendChild(head);

    const track = document.createElement("div");
    track.className = "row-track";
    const input = document.createElement("input");
    input.type = "range";
    input.min = String(min); input.max = String(max); input.step = String(step);
    input.value = String(value);

    const clamp = (v: number) => Math.min(max, Math.max(min, v));
    const commit = (v: number) => {
      v = clamp(Math.round(v / step) * step);
      input.value = String(v);
      apply(v);
      val.textContent = fmt(v);
      this.cb.onChange();
    };

    const minus = document.createElement("button");
    minus.type = "button";
    minus.className = "step-btn";
    minus.textContent = "−";
    minus.addEventListener("click", () => { this.cb.onBeforeChange(); commit(parseFloat(input.value) - step); });

    const plus = document.createElement("button");
    plus.type = "button";
    plus.className = "step-btn";
    plus.textContent = "+";
    plus.addEventListener("click", () => { this.cb.onBeforeChange(); commit(parseFloat(input.value) + step); });

    // Snapshot once per drag gesture (pointerdown), not on every 'input'
    // tick while dragging - otherwise one slider drag would flood undo
    // with dozens of near-identical steps.
    input.addEventListener("pointerdown", () => this.cb.onBeforeChange());
    input.oninput = () => commit(parseFloat(input.value));

    track.appendChild(minus);
    track.appendChild(input);
    track.appendChild(plus);
    r.appendChild(track);
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
