#version 330

// Composite u_top over u_bg. Both are straight-alpha RGBA. The colour blend mode
// is applied per spec 5.3, then combined with the standard "over" operator.

#include "lib_blend.glsl"

uniform sampler2D u_bg;
uniform sampler2D u_top;
uniform float u_opacity;
uniform int   u_blend;

in  vec2 v_uv;
out vec4 f_color;

void main() {
    vec4 b = texture(u_bg, v_uv);
    vec4 t = texture(u_top, v_uv);
    float ta = t.a * u_opacity;

    vec3 blended = vcomp_blend(u_blend, b.rgb, t.rgb);
    // where the background is opaque, use the blended colour; where it is not,
    // fall back to the top colour so nothing darkens against emptiness.
    vec3 src = mix(t.rgb, blended, b.a);

    float oa = ta + b.a * (1.0 - ta);
    vec3 oc = (src * ta + b.rgb * b.a * (1.0 - ta)) / max(oa, 1e-6);
    f_color = vec4(oc, oa);
}
