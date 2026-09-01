#version 330

// Generic transform sampler: place a source texture on the canvas with a fit
// mode + translate / scale / rotation about an anchor. Straight-alpha RGBA out,
// transparent outside the mapped quad. Used by Transform, Image Background,
// Blur Background's cover fit.

uniform sampler2D u_src;
uniform vec2  u_translate;
uniform vec2  u_scale;
uniform float u_rotation;      // radians
uniform vec2  u_anchor;        // 0..1 within the canvas
uniform int   u_fit;           // 0 none, 1 cover, 2 contain, 3 stretch, 4 tile, 5 mirror
uniform float u_src_aspect;    // w/h of the source
uniform float u_canvas_aspect; // w/h of the canvas
uniform vec2  u_skew;          // shear
uniform float u_opacity;

in  vec2 v_uv;
out vec4 f_color;

void main() {
    vec2 p = v_uv - u_anchor - u_translate;

    float sa = u_src_aspect, ca = u_canvas_aspect;
    vec2 fit = vec2(1.0);
    if (u_fit == 1)      fit = (sa > ca) ? vec2(ca / sa, 1.0) : vec2(1.0, sa / ca);   // cover
    else if (u_fit == 2) fit = (sa > ca) ? vec2(1.0, sa / ca) : vec2(ca / sa, 1.0);   // contain
    // stretch / none -> fit stays (1,1)

    float cs = cos(u_rotation), sn = sin(u_rotation);
    p = mat2(cs, -sn, sn, cs) * p;
    p.x += p.y * u_skew.x;
    p.y += p.x * u_skew.y;
    p /= max(u_scale, vec2(1e-4));
    p /= max(fit, vec2(1e-4));
    vec2 uv = p + u_anchor;

    vec4 col;
    if (u_fit == 4) {
        col = texture(u_src, fract(uv));
    } else if (u_fit == 5) {
        vec2 m = abs(fract(uv * 0.5) * 2.0 - 1.0);
        col = texture(u_src, m);
    } else {
        if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) {
            f_color = vec4(0.0);
            return;
        }
        col = texture(u_src, uv);
    }
    f_color = vec4(col.rgb, col.a * u_opacity);
}
