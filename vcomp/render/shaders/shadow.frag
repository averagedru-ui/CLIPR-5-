#version 330

// Recolour a region's alpha as a drop shadow, sampled with a canvas-space
// offset. Blur is applied as a separate pass before/after.

uniform sampler2D u_tex;      // straight-alpha region (or its blurred alpha)
uniform vec2  u_offset;       // canvas-frac shift
uniform vec4  u_color;        // shadow rgb + max alpha
uniform float u_opacity;

in  vec2 v_uv;
out vec4 f_color;

void main() {
    vec2 uv = v_uv - u_offset;
    float a = 0.0;
    if (all(greaterThanEqual(uv, vec2(0.0))) && all(lessThanEqual(uv, vec2(1.0))))
        a = texture(u_tex, uv).a;
    f_color = vec4(u_color.rgb, a * u_color.a * u_opacity);
}
