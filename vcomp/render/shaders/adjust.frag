#version 330
#include "lib_color.glsl"

// Colour Adjust. Straight-alpha RGBA in/out; alpha untouched.

uniform sampler2D u_tex;
uniform float u_exposure;      // stops
uniform float u_contrast;      // 1 = neutral
uniform float u_saturation;    // 1 = neutral
uniform float u_temperature;   // -1..1
uniform float u_tint;          // -1..1
uniform vec3  u_lift;
uniform vec3  u_gamma;
uniform vec3  u_gain;
uniform float u_hue_shift;     // radians

in  vec2 v_uv;
out vec4 f_color;

void main() {
    vec4 s = texture(u_tex, v_uv);
    vec3 c = s.rgb;

    c *= pow(2.0, u_exposure);
    c += vec3(u_temperature * 0.10, u_tint * 0.10, -u_temperature * 0.10);
    c = (c - 0.5) * u_contrast + 0.5;

    float l = luma(c);
    c = mix(vec3(l), c, u_saturation);

    c = u_gain * (c + u_lift * (1.0 - c));
    c = pow(max(c, 0.0), 1.0 / max(u_gamma, vec3(1e-3)));

    if (abs(u_hue_shift) > 1e-4) c = hue_rotate(c, u_hue_shift);

    f_color = vec4(clamp(c, 0.0, 1.0), s.a);
}
