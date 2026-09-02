#version 330

// HUD Region: lift a sub-rect of the source into a canvas-space quad, masked by
// an analytic shape SDF (rect / rounded-rect / ellipse) or a pre-baked polygon
// mask, with feather, dilate/erode, and an optional outline. Output is
// straight-alpha RGBA; opacity / blend mode are applied by the Stack later.

uniform sampler2D u_src;
uniform sampler2D u_polymask;
uniform int   u_has_polymask;

uniform vec4  u_dest;        // x0,y0,x1,y1 canvas [0,1] top-left
uniform vec4  u_srcrect;     // u0,v0,u1,v1
uniform int   u_shape;       // 0 rect, 1 rounded_rect, 2 ellipse, 3 polygon
uniform vec4  u_radii;       // per-corner radius (rounded_rect), canvas-frac of short side
uniform float u_feather;     // canvas px, converted below
uniform float u_expand;      // canvas px; + dilate, - erode
uniform float u_rotation;    // radians, about the quad centre
uniform int   u_flip_h;
uniform int   u_flip_v;

uniform float u_outline_w;   // canvas px
uniform vec4  u_outline_color;
uniform float u_opacity;
uniform vec4  u_crop;        // inset each edge: left, top, right, bottom (0..0.49 of quad)

in  vec2 v_uv;
out vec4 f_color;

float sd_box(vec2 p, vec2 b) {
    vec2 d = abs(p) - b;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}

float sd_rounded(vec2 p, vec2 b, vec4 r) {
    r.xy = (p.x > 0.0) ? r.xy : r.zw;
    r.x  = (p.y > 0.0) ? r.x  : r.y;
    vec2 q = abs(p) - b + r.x;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r.x;
}

float sd_ellipse_approx(vec2 p, vec2 b) {
    // cheap normalised-distance ellipse SDF (good enough for masking)
    vec2 q = p / b;
    float d = length(q) - 1.0;
    return d * min(b.x, b.y);
}

void main() {
    vec2 lo = min(u_dest.xy, u_dest.zw);
    vec2 hi = max(u_dest.xy, u_dest.zw);
    vec2 span = max(hi - lo, vec2(1e-6));
    vec2 d = (v_uv - lo) / span;                    // 0..1 in quad

    // rotate about centre
    vec2 c = d - 0.5;
    float s = sin(u_rotation), co = cos(u_rotation);
    c = mat2(co, -s, s, co) * c;
    d = c + 0.5;

    if (any(lessThan(d, vec2(-0.25))) || any(greaterThan(d, vec2(1.25))))
        discard;

    float shortest = min(span.x, span.y);
    float aspect = span.x / span.y;
    vec2 p = (d - 0.5);
    vec2 half_size = vec2(0.5);
    if (aspect >= 1.0) { p.x *= aspect; half_size.x *= aspect; }
    else               { p.y /= aspect; half_size.y /= aspect; }

    float feather = max(u_feather / shortest, 1e-5);
    float expand  = u_expand / shortest;

    float cov;
    if (u_shape == 3 && u_has_polymask == 1) {
        vec2 m = clamp(d, 0.0, 1.0);
        cov = texture(u_polymask, m).r;
        cov = smoothstep(0.5 - feather - expand, 0.5 + feather - expand, cov);
    } else {
        float sdf;
        if (u_shape == 1)      sdf = sd_rounded(p, half_size, u_radii);
        else if (u_shape == 2) sdf = sd_ellipse_approx(p, half_size);
        else                   sdf = sd_box(p, half_size);
        sdf -= expand;
        cov = 1.0 - smoothstep(-feather, feather, sdf);
    }
    // independent edge crop (trim the mask to the real HUD element's borders)
    vec2 clo = u_crop.xy;
    vec2 chi = vec2(1.0) - u_crop.zw;
    vec2 cc = smoothstep(clo - feather, clo + feather, d)
            * (vec2(1.0) - smoothstep(chi - feather, chi + feather, d));
    cov *= cc.x * cc.y;

    if (cov <= 0.0) discard;

    // sample source
    vec2 sd2 = clamp(d, 0.0, 1.0);
    if (u_flip_h == 1) sd2.x = 1.0 - sd2.x;
    if (u_flip_v == 1) sd2.y = 1.0 - sd2.y;
    vec2 uv = mix(u_srcrect.xy, u_srcrect.zw, sd2);
    vec4 col = texture(u_src, uv);

    // outline band just inside the edge
    if (u_outline_w > 0.0 && u_shape != 3) {
        float ow = u_outline_w / shortest;
        float sdf;
        if (u_shape == 1)      sdf = sd_rounded(p, half_size, u_radii);
        else if (u_shape == 2) sdf = sd_ellipse_approx(p, half_size);
        else                   sdf = sd_box(p, half_size);
        sdf -= expand;
        float band = smoothstep(-ow - feather, -ow, sdf) * (1.0 - smoothstep(0.0, feather, sdf));
        col.rgb = mix(col.rgb, u_outline_color.rgb, band * u_outline_color.a);
    }

    f_color = vec4(col.rgb, col.a * cov * u_opacity);
}
