#version 330
#include "lib_color.glsl"

// Multi-stop gradient. type: 0 linear, 1 radial, 2 conic. Up to 8 stops.
// interpolation: 0 sRGB, 1 oklab. Optional +-1/255 dither.

uniform int   u_type;
uniform float u_angle;        // radians
uniform vec2  u_center;
uniform float u_radius;
uniform int   u_count;
uniform float u_pos[8];
uniform vec4  u_col[8];
uniform int   u_interp;
uniform int   u_dither;

in  vec2 v_uv;
out vec4 f_color;

float gradient_t() {
    if (u_type == 1) {
        return clamp(length((v_uv - u_center) / max(u_radius, 1e-4)), 0.0, 1.0);
    }
    if (u_type == 2) {
        vec2 d = v_uv - u_center;
        float a = atan(d.y, d.x) - u_angle;
        return fract(a / 6.2831853 + 1.0);
    }
    vec2 dir = vec2(cos(u_angle), sin(u_angle));
    return clamp(dot(v_uv - 0.5, dir) + 0.5, 0.0, 1.0);
}

void main() {
    float t = gradient_t();
    vec4 c0 = u_col[0];
    vec4 c1 = u_col[max(u_count - 1, 0)];
    float p0 = u_pos[0];
    float p1 = u_pos[max(u_count - 1, 0)];
    for (int i = 0; i < 7; ++i) {
        if (i + 1 >= u_count) break;
        if (t >= u_pos[i] && t <= u_pos[i + 1]) {
            c0 = u_col[i]; c1 = u_col[i + 1];
            p0 = u_pos[i]; p1 = u_pos[i + 1];
            break;
        }
        if (t > u_pos[i + 1]) { c0 = c1 = u_col[i + 1]; p0 = p1 = u_pos[i + 1]; }
    }
    float f = (p1 > p0) ? clamp((t - p0) / (p1 - p0), 0.0, 1.0) : 0.0;

    vec3 col;
    if (u_interp == 1) {
        vec3 a = linear_srgb_to_oklab(srgb_to_linear(c0.rgb));
        vec3 b = linear_srgb_to_oklab(srgb_to_linear(c1.rgb));
        col = linear_to_srgb(oklab_to_linear_srgb(mix(a, b, f)));
    } else {
        col = mix(c0.rgb, c1.rgb, f);
    }
    if (u_dither == 1) col += (hash12(v_uv * 2048.0) - 0.5) / 255.0;

    f_color = vec4(clamp(col, 0.0, 1.0), mix(c0.a, c1.a, f));
}
