/**
 * GLSL ES 3.00 sources. ADJUST is the pointwise part of the pipeline (stages A to G of
 * backend/src/siqe/imaging/ops.py) and is shared verbatim by the renderer and the shader
 * parity test (e2e/shader-parity.spec.ts). Keep it in step with reference.ts.
 */

export const VERTEX = /* glsl */ `#version 300 es
// One triangle that covers the viewport. v_pos runs 0..1 with y pointing down the image.
out vec2 v_pos;
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  v_pos = vec2(p.x, 1.0 - p.y);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
`;

export const ADJUST = /* glsl */ `
uniform int u_stages;
uniform vec3 u_gain;
uniform vec2 u_levels;
uniform vec2 u_tone;
uniform float u_contrast;
uniform float u_vibrance;
uniform float u_saturation;

const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

float toLinear(float x) {
  x = max(x, 0.0);
  return x <= 0.04045 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4);
}

float toSrgb(float x) {
  x = max(x, 0.0);
  return x <= 0.0031308 ? 12.92 * x : 1.055 * pow(x, 1.0 / 2.4) - 0.055;
}

bool stage(int bit) {
  return (u_stages & bit) != 0;
}

vec3 adjust(vec3 c) {
  if (stage(1)) {
    c = vec3(toSrgb(toLinear(c.r) * u_gain.r), toSrgb(toLinear(c.g) * u_gain.g), toSrgb(toLinear(c.b) * u_gain.b));
  }
  if (stage(2)) {
    c = (c - u_levels.x) / (u_levels.y - u_levels.x);
  }
  if (stage(4)) {
    vec3 cc = clamp(c, 0.0, 1.0);
    vec3 inv = 1.0 - cc;
    c = c + cc * inv * inv * u_tone.x + cc * cc * inv * u_tone.y;
  }
  if (stage(8)) {
    c = (c - 0.5) * u_contrast + 0.5;
  }
  if (stage(16)) {
    float lum = dot(c, LUMA);
    float sat = clamp(max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b)), 0.0, 1.0);
    float f = 1.0 + u_vibrance * (1.0 - sat);
    c = lum + (c - lum) * f;
  }
  if (stage(32)) {
    float lum = dot(c, LUMA);
    c = lum + (c - lum) * u_saturation;
  }
  if (stage(64)) {
    c = vec3(dot(c, LUMA));
  }
  return c;
}
`;

/** Separable Gaussian blur of the source luma; run once horizontally and once vertically. */
export const BLUR = /* glsl */ `#version 300 es
precision highp float;
uniform sampler2D u_src;
uniform vec2 u_dir;      // (1, 0) or (0, 1)
uniform float u_sigma;   // in texels of u_src
uniform int u_half;      // kernel half-width
uniform bool u_lumaIn;   // first pass reads RGB and converts to luma
out vec4 outColor;
const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

float sampleAt(vec2 texel) {
  vec2 size = vec2(textureSize(u_src, 0));
  vec4 v = texture(u_src, (texel + 0.5) / size);
  return u_lumaIn ? dot(v.rgb, LUMA) : v.r;
}

void main() {
  vec2 texel = floor(gl_FragCoord.xy);
  float total = 0.0;
  float weight = 0.0;
  for (int i = -64; i <= 64; i++) {
    if (i < -u_half || i > u_half) continue;
    float w = exp(-float(i * i) / (2.0 * u_sigma * u_sigma));
    total += sampleAt(texel + u_dir * float(i)) * w;
    weight += w;
  }
  outColor = vec4(total / weight, 0.0, 0.0, 1.0);
}
`;

/**
 * The full preview: geometry (crop, flip, rotate) as a coordinate transform, the pointwise
 * stages, sharpen from the pre-blurred luma, vignette in output space, then the compare mode.
 */
export const FINAL = /* glsl */ `#version 300 es
precision highp float;
precision highp int;
in vec2 v_pos;
out vec4 outColor;

uniform sampler2D u_image;
uniform sampler2D u_blur;
uniform vec4 u_crop;       // x, y, w, h in the rotated and flipped image
uniform int u_rotate;      // 0, 90, 180, 270 (clockwise)
uniform bvec2 u_flip;      // horizontal, vertical
uniform vec2 u_outSize;    // output size in pixels, for the vignette's aspect
uniform vec2 u_sharpen;    // detail gain, unused sigma here
uniform vec2 u_vignette;   // strength, midpoint
uniform int u_mode;        // 0 after, 1 split, 2 side by side, 3 difference, 4 before
uniform float u_split;     // split position, 0..1

${ADJUST}

vec2 sourceUv(vec2 p) {
  vec2 q = u_crop.xy + p * u_crop.zw;
  if (u_flip.x) q.x = 1.0 - q.x;
  if (u_flip.y) q.y = 1.0 - q.y;
  if (u_rotate == 90) return vec2(q.y, 1.0 - q.x);
  if (u_rotate == 180) return vec2(1.0 - q.x, 1.0 - q.y);
  if (u_rotate == 270) return vec2(1.0 - q.y, q.x);
  return q;
}

float smoothstep01(float e0, float e1, float x) {
  float t = clamp((x - e0) / (e1 - e0), 0.0, 1.0);
  return t * t * (3.0 - 2.0 * t);
}

vec4 after(vec2 p, vec4 src, vec2 uv) {
  vec3 c = adjust(src.rgb);
  if (stage(128)) {
    float detail = dot(src.rgb, LUMA) - texture(u_blur, uv).r;
    c += detail * u_sharpen.x;
  }
  if (stage(256)) {
    float aspect = u_outSize.x / u_outSize.y;
    vec2 d = vec2((p.x - 0.5) * aspect, p.y - 0.5);
    float dist = length(d) / length(vec2(0.5 * aspect, 0.5));
    c *= 1.0 + u_vignette.x * smoothstep01(u_vignette.y, 1.0, dist);
  }
  return vec4(clamp(c, 0.0, 1.0), src.a);
}

void main() {
  vec2 p = v_pos;
  int mode = u_mode;
  bool showBefore = mode == 4;
  if (mode == 2) {
    showBefore = p.x < 0.5;
    p.x = showBefore ? p.x * 2.0 : (p.x - 0.5) * 2.0;
  } else if (mode == 1) {
    showBefore = p.x < u_split;
  }
  vec2 uv = sourceUv(p);
  vec4 src = texture(u_image, uv);
  if (showBefore) {
    outColor = vec4(clamp(src.rgb, 0.0, 1.0), src.a);
    return;
  }
  vec4 edited = after(p, src, uv);
  if (mode == 3) {
    vec3 diff = clamp(abs(edited.rgb - src.rgb) * 4.0, 0.0, 1.0);
    outColor = vec4(diff, 1.0);
    return;
  }
  outColor = edited;
}
`;
