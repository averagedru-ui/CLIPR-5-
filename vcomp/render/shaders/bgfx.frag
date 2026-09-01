#version 330
#include "lib_color.glsl"

// Blur Background post-processing: brightness / saturation / contrast, tint,
// dark scrim overlay, vignette. Opaque RGB out.

uniform sampler2D u_tex;
uniform float u_brightness;
uniform float u_saturation;
uniform float u_contrast;
uniform vec3  u_tint;
uniform float u_tint_amount;
uniform vec4  u_overlay;       // rgb + opacity
uniform float u_vignette;      // 0..1 amount
uniform float u_vignette_soft;

in  vec2 v_uv;
out vec4 f_color;

void main() {
    vec3 c = texture(u_tex, v_uv).rgb;
    c *= u_brightness;
    float l = luma(c);
    c = mix(vec3(l), c, u_saturation);
    c = (c - 0.5) * u_contrast + 0.5;
    c = mix(c, u_tint, u_tint_amount);
    c = mix(c, u_overlay.rgb, u_overlay.a);

    vec2 d = v_uv - 0.5;
    float r = length(d) * 1.41421;
    float v = 1.0 - smoothstep(1.0 - u_vignette - u_vignette_soft,
                               1.0 - u_vignette + 1e-4, r) * u_vignette;
    c *= mix(1.0, v, step(0.001, u_vignette));

    f_color = vec4(clamp(c, 0.0, 1.0), 1.0);
}
