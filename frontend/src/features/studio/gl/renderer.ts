/**
 * WebGL2 preview renderer. The 2048 px preview is uploaded once; every slider move is one
 * draw call, so editing stays real-time even on integrated graphics. Sharpen needs the
 * blurred source luma, which is computed in two passes and cached until the radius changes.
 */
import { type ActiveOps, type Geometry, outputSize } from "../doc";
import { BLUR, FINAL, VERTEX } from "./glsl";
import { blurHalfWidth, uniformsFor } from "./uniforms";

export type CompareMode = "after" | "split" | "side" | "diff" | "before";

const MODE_INDEX: Record<CompareMode, number> = { after: 0, split: 1, side: 2, diff: 3, before: 4 };

export interface RenderParams {
  geometry: Geometry;
  ops: ActiveOps;
  /** Preview pixels per original pixel, so sharpen radii match the full-size export. */
  previewScale: number;
  mode: CompareMode;
  split: number;
}

export interface Histogram {
  r: Uint32Array;
  g: Uint32Array;
  b: Uint32Array;
  l: Uint32Array;
  /** Fraction of pixels crushed to black (all channels) or blown out (any channel). */
  clipped: { shadows: number; highlights: number };
}

export class WebGLUnavailableError extends Error {
  constructor() {
    super("WebGL 2 isn't available in this browser.");
    this.name = "WebGLUnavailableError";
  }
}

type Program = { program: WebGLProgram; uniforms: Map<string, WebGLUniformLocation | null> };

interface Target {
  texture: WebGLTexture;
  framebuffer: WebGLFramebuffer;
  width: number;
  height: number;
}

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("Couldn't create a shader.");
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`Shader compile failed: ${log}`);
  }
  return shader;
}

export function link(gl: WebGL2RenderingContext, vertex: string, fragment: string): Program {
  const program = gl.createProgram();
  if (!program) throw new Error("Couldn't create a shader program.");
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, vertex));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, fragment));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(`Shader link failed: ${gl.getProgramInfoLog(program)}`);
  }
  return { program, uniforms: new Map() };
}

function loc(gl: WebGL2RenderingContext, p: Program, name: string): WebGLUniformLocation | null {
  if (!p.uniforms.has(name)) p.uniforms.set(name, gl.getUniformLocation(p.program, name));
  return p.uniforms.get(name) ?? null;
}

export class PreviewRenderer {
  readonly canvas: HTMLCanvasElement;
  private gl: WebGL2RenderingContext;
  private final!: Program;
  private blur!: Program;
  private vao!: WebGLVertexArrayObject;
  private image: WebGLTexture | null = null;
  private imageSize: [number, number] = [1, 1];
  private bitmap: ImageBitmap | null = null;
  private blurTargets: [Target, Target] | null = null;
  private blurSigma = -1;
  private histogramTarget: Target | null = null;
  private floatTargets = false;
  lost = false;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const gl = canvas.getContext("webgl2", {
      alpha: true,
      premultipliedAlpha: false,
      antialias: false,
      preserveDrawingBuffer: false,
    });
    if (!gl) throw new WebGLUnavailableError();
    this.gl = gl;
    this.setup();
  }

  private setup(): void {
    const gl = this.gl;
    this.floatTargets = gl.getExtension("EXT_color_buffer_float") !== null;
    this.final = link(gl, VERTEX, FINAL);
    this.blur = link(gl, VERTEX, BLUR);
    const vao = gl.createVertexArray();
    if (!vao) throw new Error("Couldn't create a vertex array.");
    this.vao = vao;
    this.blurTargets = null;
    this.blurSigma = -1;
    this.histogramTarget = null;
    if (this.bitmap) this.upload(this.bitmap);
  }

  /** Call after the browser restores a lost context. */
  restore(): void {
    this.lost = false;
    this.setup();
  }

  setImage(bitmap: ImageBitmap): void {
    if (this.bitmap && this.bitmap !== bitmap) this.bitmap.close();
    this.bitmap = bitmap;
    this.upload(bitmap);
  }

  get hasImage(): boolean {
    return this.image !== null;
  }

  private upload(bitmap: ImageBitmap): void {
    const gl = this.gl;
    if (this.image) gl.deleteTexture(this.image);
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
    this.setSampling(gl.LINEAR);
    this.image = texture;
    this.imageSize = [bitmap.width, bitmap.height];
    this.blurSigma = -1;
    for (const t of this.blurTargets ?? []) this.deleteTarget(t);
    this.blurTargets = null;
  }

  private setSampling(filter: number): void {
    const gl = this.gl;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  private createTarget(width: number, height: number, float: boolean): Target {
    const gl = this.gl;
    const texture = gl.createTexture();
    const framebuffer = gl.createFramebuffer();
    if (!texture || !framebuffer) throw new Error("Couldn't allocate a render target.");
    gl.bindTexture(gl.TEXTURE_2D, texture);
    if (float) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, width, height, 0, gl.RGBA, gl.HALF_FLOAT, null);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    this.setSampling(gl.LINEAR);
    gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return { texture, framebuffer, width, height };
  }

  private deleteTarget(t: Target): void {
    this.gl.deleteTexture(t.texture);
    this.gl.deleteFramebuffer(t.framebuffer);
  }

  /** Blur the source luma with sigma in preview pixels; cached by sigma. */
  private ensureBlur(sigma: number): void {
    const gl = this.gl;
    if (!this.image) return;
    const [w, h] = this.imageSize;
    if (!this.blurTargets) {
      this.blurTargets = [
        this.createTarget(w, h, this.floatTargets),
        this.createTarget(w, h, this.floatTargets),
      ];
      this.blurSigma = -1;
    }
    if (Math.abs(sigma - this.blurSigma) < 1e-4) return;
    const [first, second] = this.blurTargets;
    const p = this.blur;
    gl.useProgram(p.program);
    gl.bindVertexArray(this.vao);
    gl.viewport(0, 0, w, h);
    gl.uniform1f(loc(gl, p, "u_sigma"), sigma);
    gl.uniform1i(loc(gl, p, "u_half"), blurHalfWidth(sigma));
    gl.uniform1i(loc(gl, p, "u_src"), 0);
    gl.activeTexture(gl.TEXTURE0);

    gl.bindFramebuffer(gl.FRAMEBUFFER, first.framebuffer);
    gl.bindTexture(gl.TEXTURE_2D, this.image);
    gl.uniform2f(loc(gl, p, "u_dir"), 1, 0);
    gl.uniform1i(loc(gl, p, "u_lumaIn"), 1);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    gl.bindFramebuffer(gl.FRAMEBUFFER, second.framebuffer);
    gl.bindTexture(gl.TEXTURE_2D, first.texture);
    gl.uniform2f(loc(gl, p, "u_dir"), 0, 1);
    gl.uniform1i(loc(gl, p, "u_lumaIn"), 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.blurSigma = sigma;
  }

  /** Output size of the preview (in preview pixels) for the given geometry. */
  outputSize(geometry: Geometry): [number, number] {
    return outputSize(this.imageSize[0], this.imageSize[1], geometry);
  }

  private draw(params: RenderParams, target: Target | null, width: number, height: number): void {
    const gl = this.gl;
    if (!this.image) return;
    const u = uniformsFor(params.ops);
    if (u.stages & 128) this.ensureBlur(Math.max(0.2, u.sharpen[1] * params.previewScale));
    const p = this.final;
    const g = params.geometry;
    const crop = g.crop ?? { x: 0, y: 0, w: 1, h: 1 };
    const [outW, outH] = this.outputSize(g);

    gl.bindFramebuffer(gl.FRAMEBUFFER, target?.framebuffer ?? null);
    gl.viewport(0, 0, width, height);
    gl.useProgram(p.program);
    gl.bindVertexArray(this.vao);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.image);
    gl.uniform1i(loc(gl, p, "u_image"), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.blurTargets?.[1].texture ?? this.image);
    gl.uniform1i(loc(gl, p, "u_blur"), 1);

    gl.uniform4f(loc(gl, p, "u_crop"), crop.x, crop.y, crop.w, crop.h);
    gl.uniform1i(loc(gl, p, "u_rotate"), g.rotate);
    gl.uniform2i(loc(gl, p, "u_flip"), g.flip_h ? 1 : 0, g.flip_v ? 1 : 0);
    gl.uniform2f(loc(gl, p, "u_outSize"), outW, outH);
    gl.uniform1i(loc(gl, p, "u_stages"), u.stages);
    gl.uniform3f(loc(gl, p, "u_gain"), ...u.gain);
    gl.uniform2f(loc(gl, p, "u_levels"), ...u.levels);
    gl.uniform2f(loc(gl, p, "u_tone"), ...u.tone);
    gl.uniform1f(loc(gl, p, "u_contrast"), u.contrast);
    gl.uniform1f(loc(gl, p, "u_vibrance"), u.vibrance);
    gl.uniform1f(loc(gl, p, "u_saturation"), u.saturation);
    gl.uniform2f(loc(gl, p, "u_sharpen"), ...u.sharpen);
    gl.uniform2f(loc(gl, p, "u_vignette"), ...u.vignette);
    gl.uniform1i(loc(gl, p, "u_mode"), MODE_INDEX[params.mode]);
    gl.uniform1f(loc(gl, p, "u_split"), params.split);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.activeTexture(gl.TEXTURE0);
  }

  /** Draw to the canvas, resizing it to the output size. Returns the canvas size. */
  render(params: RenderParams): [number, number] {
    if (this.lost || !this.image) return [this.canvas.width, this.canvas.height];
    const [w, h] = this.outputSize(params.geometry);
    const width = params.mode === "side" ? w * 2 : w;
    if (this.canvas.width !== width) this.canvas.width = width;
    if (this.canvas.height !== h) this.canvas.height = h;
    this.draw(params, null, width, h);
    return [width, h];
  }

  /** Histogram of the edited result, from a small offscreen render. */
  histogram(params: Omit<RenderParams, "mode" | "split">, maxSide = 320): Histogram | null {
    if (this.lost || !this.image) return null;
    const gl = this.gl;
    const [w, h] = this.outputSize(params.geometry);
    const scale = Math.min(1, maxSide / Math.max(w, h));
    const tw = Math.max(1, Math.round(w * scale));
    const th = Math.max(1, Math.round(h * scale));
    if (!this.histogramTarget || this.histogramTarget.width !== tw || this.histogramTarget.height !== th) {
      if (this.histogramTarget) this.deleteTarget(this.histogramTarget);
      this.histogramTarget = this.createTarget(tw, th, false);
    }
    this.draw({ ...params, mode: "after", split: 0 }, this.histogramTarget, tw, th);
    const pixels = new Uint8Array(tw * th * 4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.histogramTarget.framebuffer);
    gl.readPixels(0, 0, tw, th, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return computeHistogram(pixels);
  }

  dispose(): void {
    const gl = this.gl;
    if (this.image) gl.deleteTexture(this.image);
    for (const t of this.blurTargets ?? []) this.deleteTarget(t);
    if (this.histogramTarget) this.deleteTarget(this.histogramTarget);
    gl.deleteProgram(this.final.program);
    gl.deleteProgram(this.blur.program);
    gl.deleteVertexArray(this.vao);
    this.image = null;
    this.bitmap?.close();
    this.bitmap = null;
  }
}

/** 256-bin histograms of RGBA bytes; fully transparent pixels are skipped. */
export function computeHistogram(pixels: Uint8Array): Histogram {
  const r = new Uint32Array(256);
  const g = new Uint32Array(256);
  const b = new Uint32Array(256);
  const l = new Uint32Array(256);
  let counted = 0;
  let low = 0;
  let high = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    if (pixels[i + 3] === 0) continue;
    const R = pixels[i] ?? 0;
    const G = pixels[i + 1] ?? 0;
    const B = pixels[i + 2] ?? 0;
    r[R] = (r[R] ?? 0) + 1;
    g[G] = (g[G] ?? 0) + 1;
    b[B] = (b[B] ?? 0) + 1;
    const L = Math.round(0.2126 * R + 0.7152 * G + 0.0722 * B);
    l[L] = (l[L] ?? 0) + 1;
    counted++;
    if (R <= 1 && G <= 1 && B <= 1) low++;
    if (R === 255 || G === 255 || B === 255) high++;
  }
  const n = Math.max(1, counted);
  return { r, g, b, l, clipped: { shadows: low / n, highlights: high / n } };
}
