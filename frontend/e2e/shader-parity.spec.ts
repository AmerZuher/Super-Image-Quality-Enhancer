/**
 * Runs the real preview shader (ADJUST in glsl.ts) on the GPU and checks it against the
 * fixture generated from the server formulas. Needs no running stack.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { ADJUST } from "../src/features/studio/gl/glsl";
import { uniformsFor } from "../src/features/studio/gl/uniforms";

interface Case {
  rgb: [number, number, number];
  ops: Record<string, Record<string, number>>;
  expected: [number, number, number];
}

const fixture = JSON.parse(
  readFileSync(fileURLToPath(new URL("../src/features/studio/ops_parity.json", import.meta.url)), "utf8"),
) as { cases: Case[] };

// float32 on the GPU versus float64 on the server: allow a little more than the CPU test.
const GPU_TOLERANCE = 5e-4;

test("the WebGL shader matches the server formulas", async ({ page }) => {
  await page.setContent("<canvas width='1' height='1'></canvas>");
  const cases = fixture.cases.map((c) => ({ rgb: c.rgb, u: uniformsFor(c.ops), expected: c.expected }));
  const results = await page.evaluate(
    ({ adjust, cases }) => {
      const canvas = document.querySelector("canvas") as HTMLCanvasElement;
      const gl = canvas.getContext("webgl2");
      if (!gl) return { error: "no WebGL 2" };
      if (!gl.getExtension("EXT_color_buffer_float")) return { error: "no float render targets" };
      const vs = `#version 300 es
        void main() { gl_Position = vec4(vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2)) * 2.0 - 1.0, 0.0, 1.0); }`;
      const fs = `#version 300 es
        precision highp float;
        precision highp int;
        uniform vec3 u_in;
        out vec4 outColor;
        ${adjust}
        void main() { outColor = vec4(clamp(adjust(u_in), 0.0, 1.0), 1.0); }`;
      const shader = (type: number, src: string) => {
        const s = gl.createShader(type) as WebGLShader;
        gl.shaderSource(s, src);
        gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(String(gl.getShaderInfoLog(s)));
        return s;
      };
      const program = gl.createProgram() as WebGLProgram;
      gl.attachShader(program, shader(gl.VERTEX_SHADER, vs));
      gl.attachShader(program, shader(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(program);
      gl.useProgram(program);
      gl.bindVertexArray(gl.createVertexArray());
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, 1, 1, 0, gl.RGBA, gl.FLOAT, null);
      const fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
      gl.viewport(0, 0, 1, 1);
      const at = (name: string) => gl.getUniformLocation(program, name);
      const out: number[][] = [];
      const pixel = new Float32Array(4);
      for (const c of cases) {
        gl.uniform3f(at("u_in"), ...c.rgb);
        gl.uniform1i(at("u_stages"), c.u.stages);
        gl.uniform3f(at("u_gain"), ...c.u.gain);
        gl.uniform2f(at("u_levels"), ...c.u.levels);
        gl.uniform2f(at("u_tone"), ...c.u.tone);
        gl.uniform1f(at("u_contrast"), c.u.contrast);
        gl.uniform1f(at("u_vibrance"), c.u.vibrance);
        gl.uniform1f(at("u_saturation"), c.u.saturation);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.FLOAT, pixel);
        out.push([pixel[0] ?? 0, pixel[1] ?? 0, pixel[2] ?? 0]);
      }
      return { out };
    },
    { adjust: ADJUST, cases },
  );
  if ("error" in results) test.skip(true, `This browser can't run the check: ${results.error}`);
  const worst = cases.reduce((max, c, i) => {
    const got = results.out?.[i] ?? [];
    return Math.max(max, ...c.expected.map((e, ch) => Math.abs((got[ch] ?? Number.NaN) - e)));
  }, 0);
  expect(worst).toBeLessThan(GPU_TOLERANCE);
});
