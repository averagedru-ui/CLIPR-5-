#version 330

// Attribute-less fullscreen triangle. v_uv has a TOP-LEFT origin that matches
// both image convention AND FBO memory order (row 0 = v_uv.y 0 = image top), so
// FBO->FBO sampling in compose/blur needs no flip and readback needs no flip.

out vec2 v_uv;

void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = p;                                   // 0..1 across the visible quad
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
