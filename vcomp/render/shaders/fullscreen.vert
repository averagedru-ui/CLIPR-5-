#version 330

// Attribute-less fullscreen triangle. v_uv uses a TOP-LEFT origin so every
// coordinate space in the compositor (canvas, source rects) matches image
// convention; the FBO is flipped once on readback.

out vec2 v_uv;

void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = vec2(p.x, 1.0 - p.y);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
