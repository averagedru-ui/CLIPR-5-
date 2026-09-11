import { linkProgram, makeUnitQuad } from "./gl";
import { QUAD_VS, BG_FS, REGION_FS } from "./shaders";
import { ANCHOR_UV, type Project, type RegionNode } from "../core/types";

const SHAPE_ID: Record<string, number> = { rect: 0, rounded_rect: 1, ellipse: 2, polygon: 1 };

export class Compositor {
  gl: WebGL2RenderingContext;
  private bgProg: WebGLProgram;
  private regionProg: WebGLProgram;
  private quad: WebGLBuffer;
  private tex: WebGLTexture;
  private texW = 0;
  private texH = 0;

  constructor(private canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl2", { premultipliedAlpha: false, alpha: false });
    if (!gl) throw new Error("WebGL2 unavailable on this device/browser.");
    this.gl = gl;
    this.bgProg = linkProgram(gl, QUAD_VS, BG_FS);
    this.regionProg = linkProgram(gl, QUAD_VS, REGION_FS);
    this.quad = makeUnitQuad(gl);
    this.tex = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  uploadFrame(src: TexImageSource, w: number, h: number) {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    this.texW = w;
    this.texH = h;
  }

  destRectFor(region: RegionNode, canvasW: number, canvasH: number): { x0: number; y0: number; x1: number; y1: number } {
    const { w: sw, h: sh } = region.source_rect;
    const srcW = this.texW || canvasW;
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

  draw(project: Project, opts: { selectedId?: string | null } = {}) {
    const gl = this.gl;
    const cw = project.canvas_w, ch = project.canvas_h;
    if (this.canvas.width !== cw || this.canvas.height !== ch) {
      this.canvas.width = cw;
      this.canvas.height = ch;
    }
    gl.viewport(0, 0, cw, ch);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    if (this.texW === 0) return;

    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);

    // background: cover-fit full source frame
    gl.useProgram(this.bgProg);
    this.setBgDest(cw, ch);
    gl.uniform1i(gl.getUniformLocation(this.bgProg, "uTex"), 0);
    gl.drawArrays(gl.TRIANGLES, 0, 6);

    const regions = project.nodes.filter((n): n is RegionNode => n.kind === "region");
    for (const r of regions) {
      const { x0, y0, x1, y1 } = this.destRectFor(r, cw, ch);
      const dw = x1 - x0, dh = y1 - y0;
      gl.useProgram(this.regionProg);
      const U = (name: string) => gl.getUniformLocation(this.regionProg, name);
      gl.uniform2f(U("uDestOrigin"), x0, y0);
      gl.uniform2f(U("uDestSize"), dw, dh);
      gl.uniform2f(U("uPivot"), x0 + dw / 2, y0 + dh / 2);
      gl.uniform1f(U("uRotation"), (r.rotation * Math.PI) / 180);
      const { x: sx0, y: sy0, w: sw, h: sh } = r.source_rect;
      gl.uniform4f(U("uSrcRect"), sx0, sy0, sx0 + sw, sy0 + sh);
      gl.uniform1i(U("uShape"), SHAPE_ID[r.shape] ?? 0);
      gl.uniform4f(U("uRadii"), r.corner_radii.x, r.corner_radii.y, r.corner_radii.z, r.corner_radii.w);
      gl.uniform1f(U("uFeatherPx"), r.feather);
      gl.uniform2f(U("uQuadPx"), dw * cw, dh * ch);
      gl.uniform1f(U("uOpacity"), r.opacity);
      gl.uniform1i(U("uFlipH"), r.flip_h ? 1 : 0);
      gl.uniform1i(U("uFlipV"), r.flip_v ? 1 : 0);
      gl.uniform1i(U("uTex"), 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }
  }

  private setBgDest(cw: number, ch: number) {
    const gl = this.gl;
    const srcAspect = this.texW / Math.max(1, this.texH);
    const dstAspect = cw / ch;
    let dw = 1, dh = 1, x0 = 0, y0 = 0;
    if (srcAspect > dstAspect) {
      // source wider than dest -> fit height, crop width
      dh = 1;
      dw = srcAspect / dstAspect;
      x0 = (1 - dw) / 2;
    } else {
      dw = 1;
      dh = dstAspect / srcAspect;
      y0 = (1 - dh) / 2;
    }
    const U = (name: string) => gl.getUniformLocation(this.bgProg, name);
    gl.uniform2f(U("uDestOrigin"), x0, y0);
    gl.uniform2f(U("uDestSize"), dw, dh);
    gl.uniform2f(U("uPivot"), 0.5, 0.5);
    gl.uniform1f(U("uRotation"), 0);
  }
}
