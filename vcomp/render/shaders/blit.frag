#version 330

// Place a source texture into a canvas-space quad. Output is straight-alpha
// RGBA, fully transparent outside the quad. Rounded-corner + feathered edge via
// a rounded-box SDF evaluated in canvas-normalized units. Used by Main Framing
// (M3) and, with an added shape switch, HUD Region (M4).

uniform sampler2D u_src;
uniform vec4  u_dest;       // x0,y0,x1,y1 canvas [0,1] top-left
uniform vec4  u_srcrect;    // u0,v0,u1,v1
uniform float u_opacity;
uniform float u_feather;    // canvas-space fraction
uniform float u_radius;     // corner radius, canvas-space fraction of min(w,h)
uniform int   u_flip_h;
uniform int   u_flip_v;

in  vec2 v_uv;
out vec4 f_color;

float rounded_box_sdf(vec2 p, vec2 half_size, float r) {
    vec2 q = abs(p) - half_size + r;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

void main() {
    vec2 lo = min(u_dest.xy, u_dest.zw);
    vec2 hi = max(u_dest.xy, u_dest.zw);
    vec2 span = max(hi - lo, vec2(1e-6));
    vec2 d = (v_uv - lo) / span;                 // 0..1 within quad

    if (any(lessThan(d, vec2(-0.5))) || any(greaterThan(d, vec2(1.5)))) {
        discard;
    }

    // SDF in units of the quad's shorter side
    float aspect = span.x / span.y;
    vec2 p = (d - 0.5);
    vec2 half_size = vec2(0.5);
    if (aspect >= 1.0) { p.x *= aspect; half_size.x *= aspect; }
    else               { p.y /= aspect; half_size.y /= aspect; }

    float r = clamp(u_radius, 0.0, min(half_size.x, half_size.y));
    float sdf = rounded_box_sdf(p, half_size, r);

    float fw = max(u_feather / min(span.x, span.y), 1e-5);
    float cov = 1.0 - smoothstep(-fw, 0.0, sdf);
    if (cov <= 0.0) discard;

    vec2 sd = clamp(d, 0.0, 1.0);
    if (u_flip_h == 1) sd.x = 1.0 - sd.x;
    if (u_flip_v == 1) sd.y = 1.0 - sd.y;
    vec2 uv = mix(u_srcrect.xy, u_srcrect.zw, sd);
    vec4 s = texture(u_src, uv);

    f_color = vec4(s.rgb, s.a * u_opacity * cov);
}
