#version 330
#include "lib_color.glsl"

// Luma / chroma key. mode: 0 none, 1 luma, 2 chroma.

uniform sampler2D u_tex;
uniform int   u_mode;
uniform vec3  u_key;
uniform float u_tolerance;
uniform float u_softness;
uniform float u_spill;         // spill suppression 0..1
uniform float u_despill;       // 0..1
uniform int   u_invert;

in  vec2 v_uv;
out vec4 f_color;

void main() {
    vec4 s = texture(u_tex, v_uv);
    vec3 c = s.rgb;
    float a = s.a;

    if (u_mode == 1) {
        float d = abs(luma(c) - luma(u_key));
        a *= smoothstep(u_tolerance, u_tolerance + u_softness + 1e-4, d);
    } else if (u_mode == 2) {
        float d = distance(c, u_key);
        float m = smoothstep(u_tolerance, u_tolerance + u_softness + 1e-4, d);
        a *= m;
        if (u_spill > 0.0) {
            float sp = clamp(1.0 - m, 0.0, 1.0) * u_spill;
            float g = max(c.g - max(c.r, c.b), 0.0);
            c.g -= g * sp;
        }
        if (u_despill > 0.0) {
            float avg = (c.r + c.b) * 0.5;
            c.g = mix(c.g, min(c.g, avg), u_despill);
        }
    }

    if (u_invert == 1) a = s.a - a + (1.0 - s.a) * 0.0;
    f_color = vec4(c, clamp(a, 0.0, 1.0));
}
