#version 330

// Separable Gaussian, one axis per pass. u_dir is the per-tap texel offset
// (texelSize * axis). Radius in taps (<= 12). Straight-alpha RGBA in/out.

uniform sampler2D u_tex;
uniform vec2  u_dir;
uniform int   u_radius;

in  vec2 v_uv;
out vec4 f_color;

void main() {
    int r = clamp(u_radius, 0, 12);
    if (r == 0) { f_color = texture(u_tex, v_uv); return; }

    float sigma = float(r) * 0.5 + 0.5;
    float wsum = 0.0;
    vec4 acc = vec4(0.0);
    for (int i = -12; i <= 12; ++i) {
        if (i < -r || i > r) continue;
        float w = exp(-float(i * i) / (2.0 * sigma * sigma));
        acc += texture(u_tex, v_uv + u_dir * float(i)) * w;
        wsum += w;
    }
    f_color = acc / max(wsum, 1e-6);
}
