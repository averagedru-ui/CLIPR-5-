// Blend modes selected by an integer uniform (spec 5.3). One function, no
// per-mode shader permutations. Operates on non-premultiplied RGB in [0,1].

vec3 vcomp_blend(int mode, vec3 b, vec3 s) {
    if (mode == 0) return s;                                   // normal
    if (mode == 1) return min(b + s, vec3(1.0));               // add
    if (mode == 2) return b + s - b * s;                       // screen
    if (mode == 3) return b * s;                               // multiply
    if (mode == 4) {                                           // overlay
        return mix(2.0 * b * s,
                   1.0 - 2.0 * (1.0 - b) * (1.0 - s),
                   step(0.5, b));
    }
    if (mode == 5) {                                           // soft-light
        vec3 d = mix(((16.0 * b - 12.0) * b + 4.0) * b, sqrt(b), step(0.25, b));
        return mix(b - (1.0 - 2.0 * s) * b * (1.0 - b),
                   b + (2.0 * s - 1.0) * (d - b),
                   step(0.5, s));
    }
    if (mode == 6) return min(b, s);                           // darken
    if (mode == 7) return max(b, s);                           // lighten
    return s;
}
