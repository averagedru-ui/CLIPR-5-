#version 330

// Solid rounded-rectangle plate drawn behind a HUD region so it reads against a
// busy background. Straight-alpha RGBA.

uniform vec4  u_rect;      // x0,y0,x1,y1 canvas [0,1]
uniform float u_radius;    // canvas-frac of short side
uniform float u_softness;  // edge softness, canvas frac
uniform vec4  u_color;

in  vec2 v_uv;
out vec4 f_color;

float sd_rounded(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

void main() {
    vec2 lo = min(u_rect.xy, u_rect.zw);
    vec2 hi = max(u_rect.xy, u_rect.zw);
    vec2 span = max(hi - lo, vec2(1e-6));
    vec2 d = (v_uv - lo) / span;
    if (any(lessThan(d, vec2(-0.5))) || any(greaterThan(d, vec2(1.5)))) discard;

    float aspect = span.x / span.y;
    vec2 p = d - 0.5;
    vec2 h = vec2(0.5);
    if (aspect >= 1.0) { p.x *= aspect; h.x *= aspect; }
    else               { p.y /= aspect; h.y /= aspect; }

    float r = clamp(u_radius, 0.0, min(h.x, h.y));
    float sdf = sd_rounded(p, h, r);
    float soft = max(u_softness, 1e-4);
    float cov = 1.0 - smoothstep(-soft, soft, sdf);
    if (cov <= 0.0) discard;
    f_color = vec4(u_color.rgb, u_color.a * cov);
}
