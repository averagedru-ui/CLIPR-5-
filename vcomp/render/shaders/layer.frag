#version 330

// One layer over an accumulated background. The layer is a quad in canvas space
// (u_dest, top-left origin, [0,1]) that samples a sub-rect of a source texture
// (u_srcrect). Alpha outside the quad is zero. Feather softens the quad edge
// (canvas-space fraction). This is the M2 building block; the M4 HUD Region
// shader replaces the rectangular test with an SDF.

#include "lib_blend.glsl"

uniform sampler2D u_bg;
uniform sampler2D u_src;
uniform vec4  u_dest;      // x0, y0, x1, y1  (canvas [0,1], top-left origin)
uniform vec4  u_srcrect;   // u0, v0, u1, v1  (source texture [0,1], top-left)
uniform float u_opacity;
uniform float u_feather;   // canvas-space fraction, 0 = hard edge
uniform int   u_blend;
uniform int   u_has_src;
uniform int   u_flip_h;
uniform int   u_flip_v;

in  vec2 v_uv;
out vec4 f_color;

void main() {
    vec3 base = texture(u_bg, v_uv).rgb;
    vec3 outc = base;

    if (u_has_src == 1) {
        vec2 span = max(u_dest.zw - u_dest.xy, vec2(1e-6));
        vec2 d = (v_uv - u_dest.xy) / span;

        // rectangular coverage with optional feather
        vec2 fw = max(vec2(u_feather) / span, vec2(1e-6));
        vec2 cov2 = smoothstep(vec2(0.0), fw, d)
                  * smoothstep(vec2(0.0), fw, vec2(1.0) - d);
        float cov = cov2.x * cov2.y;

        if (cov > 0.0) {
            vec2 sd = d;
            if (u_flip_h == 1) sd.x = 1.0 - sd.x;
            if (u_flip_v == 1) sd.y = 1.0 - sd.y;
            vec2 uv = mix(u_srcrect.xy, u_srcrect.zw, sd);
            vec4 s = texture(u_src, uv);
            vec3 blended = vcomp_blend(u_blend, base, s.rgb);
            float a = s.a * u_opacity * cov;
            outc = mix(base, blended, a);
        }
    }

    f_color = vec4(outc, 1.0);
}
