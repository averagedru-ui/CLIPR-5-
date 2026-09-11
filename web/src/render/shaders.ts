export const QUAD_VS = `#version 300 es
precision highp float;
layout(location=0) in vec2 aPos; // 0..1 quad
uniform vec2 uDestOrigin;   // canvas uv, top-left of unrotated quad
uniform vec2 uDestSize;     // canvas uv size
uniform vec2 uPivot;        // canvas uv, rotation pivot (anchor point)
uniform float uRotation;    // radians
out vec2 vUV;
void main() {
  vec2 local = aPos * uDestSize + uDestOrigin - uPivot;
  float c = cos(uRotation), s = sin(uRotation);
  vec2 rotated = vec2(local.x * c - local.y * s, local.x * s + local.y * c) + uPivot;
  // canvas uv -> clip space (y flip)
  vec2 clip = rotated * 2.0 - 1.0;
  clip.y = -clip.y;
  gl_Position = vec4(clip, 0.0, 1.0);
  vUV = aPos;
}`;

// Background: cover-fit the source frame into the canvas, no masking.
export const BG_FS = `#version 300 es
precision highp float;
in vec2 vUV;
uniform sampler2D uTex;
out vec4 outColor;
void main() {
  outColor = vec4(texture(uTex, vUV).rgb, 1.0);
}`;

export const REGION_FS = `#version 300 es
precision highp float;
in vec2 vUV; // 0..1 across the dest quad
uniform sampler2D uTex;
uniform vec4 uSrcRect;    // x0,y0,x1,y1 in source uv
uniform int uShape;       // 0 rect, 1 rounded_rect, 2 ellipse
uniform vec4 uRadii;      // per-corner radius, canvas-quad-relative 0..0.5
uniform float uFeatherPx; // feather in quad-local px
uniform vec2 uQuadPx;     // dest quad size in px (for feather scale)
uniform float uOpacity;
uniform bool uFlipH;
uniform bool uFlipV;
out vec4 outColor;

float sdRoundRect(vec2 p, vec2 halfSize, vec4 radii) {
  // radii: tl, tr, br, bl
  float r = (p.x > 0.0)
    ? ((p.y > 0.0) ? radii.z : radii.y)
    : ((p.y > 0.0) ? radii.w : radii.x);
  vec2 q = abs(p) - halfSize + r;
  return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

void main() {
  vec2 uv = vUV;
  if (uFlipH) uv.x = 1.0 - uv.x;
  if (uFlipV) uv.y = 1.0 - uv.y;
  vec2 srcUV = mix(uSrcRect.xy, uSrcRect.zw, uv);
  vec3 col = texture(uTex, srcUV).rgb;

  float mask = 1.0;
  vec2 halfPx = uQuadPx * 0.5;
  vec2 pPx = (vUV - 0.5) * uQuadPx;
  float featherPx = max(uFeatherPx, 0.001);

  if (uShape == 2) {
    // ellipse
    vec2 n = pPx / max(halfPx, vec2(0.001));
    float d = (length(n) - 1.0) * max(halfPx.x, halfPx.y);
    mask = 1.0 - smoothstep(-featherPx, featherPx, d);
  } else if (uShape == 1) {
    float maxR = min(halfPx.x, halfPx.y);
    vec4 radiiPx = clamp(uRadii, 0.0, 1.0) * maxR;
    float d = sdRoundRect(pPx, halfPx, radiiPx);
    mask = 1.0 - smoothstep(-featherPx, featherPx, d);
  } else {
    vec2 d2 = abs(pPx) - halfPx;
    float d = max(d2.x, d2.y);
    mask = 1.0 - smoothstep(-featherPx, featherPx, d);
  }

  if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) mask = 0.0;
  outColor = vec4(col, mask * uOpacity);
}`;
