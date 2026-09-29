/* BUMBLEBLE lightning — shared WebGL effect (vanilla port of the Hero Odyssey <Lightning/> shader).
 *
 *   const fx = Lightning.mount(canvas, { hue: 220, xOffset: 0, speed: 1.6, intensity: 0.6, size: 2 });
 *   fx.set({ xOffset: 0.3 });   // update any parameter live
 *   fx.destroy();
 *
 * Unlike the original, it renders on a TRANSPARENT background (premultiplied alpha), so it can
 * sit behind or over any page. In light theme (options.light() === true) the bolt is drawn in
 * deep blue instead of glowing white-blue, so it stays visible on white backgrounds.
 * Rendering pauses when the canvas is off-screen or the tab is hidden; with
 * prefers-reduced-motion a single still frame is drawn.
 */
(() => {
  "use strict";
  const VS = "attribute vec2 aPosition; void main(){ gl_Position = vec4(aPosition, 0.0, 1.0); }";
  const FS = `precision mediump float;
    uniform vec2 iResolution; uniform float iTime; uniform float uHue; uniform float uXOffset;
    uniform float uSpeed; uniform float uIntensity; uniform float uSize; uniform float uLight;
    #define OCTAVE_COUNT 10
    vec3 hsv2rgb(vec3 c){ vec3 rgb = clamp(abs(mod(c.x*6.0+vec3(0.0,4.0,2.0),6.0)-3.0)-1.0,0.0,1.0); return c.z*mix(vec3(1.0),rgb,c.y); }
    float hash11(float p){ p = fract(p*.1031); p *= p+33.33; p *= p+p; return fract(p); }
    float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx)*.1031); p3 += dot(p3, p3.yzx+33.33); return fract((p3.x+p3.y)*p3.z); }
    mat2 rotate2d(float t){ float c = cos(t), s = sin(t); return mat2(c,-s,s,c); }
    float noise(vec2 p){ vec2 ip = floor(p); vec2 fp = fract(p);
      float a = hash12(ip), b = hash12(ip+vec2(1.0,0.0)), c = hash12(ip+vec2(0.0,1.0)), d = hash12(ip+vec2(1.0,1.0));
      vec2 t = smoothstep(0.0,1.0,fp); return mix(mix(a,b,t.x), mix(c,d,t.x), t.y); }
    float fbm(vec2 p){ float v = 0.0, a = 0.5; for (int i = 0; i < OCTAVE_COUNT; ++i){ v += a*noise(p); p *= rotate2d(0.45); p *= 2.0; a *= 0.5; } return v; }
    void main(){
      vec2 uv = gl_FragCoord.xy / iResolution.xy; uv = 2.0*uv - 1.0; uv.x *= iResolution.x / iResolution.y; uv.x += uXOffset;
      uv += 2.0*fbm(uv*uSize + 0.8*iTime*uSpeed) - 1.0;
      float dist = abs(uv.x);
      vec3 baseColor = hsv2rgb(vec3(uHue/360.0, 0.7, 0.8));
      vec3 col = baseColor * pow(mix(0.0, 0.07, hash11(iTime*uSpeed)) / dist, 1.0) * uIntensity;
      float a = clamp(max(col.r, max(col.g, col.b)), 0.0, 1.0);
      // light theme: same shape, drawn as a deep-blue bolt (premultiplied) so it shows on white
      vec3 dark = hsv2rgb(vec3(uHue/360.0, 0.85, 0.55)) * a;
      gl_FragColor = vec4(mix(min(col, vec3(a)), dark, uLight), a);
    }`;

  function mount(canvas, opts = {}) {
    const P = Object.assign({ hue: 220, xOffset: 0, speed: 1.6, intensity: 0.6, size: 2, maxDpr: 1.5, light: () => false }, opts);
    const gl = canvas && canvas.getContext("webgl", { premultipliedAlpha: true, alpha: true, antialias: false });
    if (!gl) return { set() {}, destroy() {} }; // graceful: no WebGL, no effect
    const sh = (src, type) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.error("[Lightning]", gl.getShaderInfoLog(s)); return null; } return s; };
    const v = sh(VS, gl.VERTEX_SHADER), f = sh(FS, gl.FRAGMENT_SHADER);
    if (!v || !f) return { set() {}, destroy() {} };
    const prog = gl.createProgram(); gl.attachShader(prog, v); gl.attachShader(prog, f); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.error("[Lightning]", gl.getProgramInfoLog(prog)); return { set() {}, destroy() {} }; }
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "aPosition"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const U = (n) => gl.getUniformLocation(prog, n);
    const u = { res: U("iResolution"), t: U("iTime"), hue: U("uHue"), x: U("uXOffset"), sp: U("uSpeed"),
      it: U("uIntensity"), sz: U("uSize"), lt: U("uLight") };
    const reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const start = performance.now();
    let visible = true, raf = 0, alive = true;

    const draw = () => {
      const dpr = Math.min(P.maxDpr, window.devicePixelRatio || 1);
      const w = Math.max(1, Math.floor(canvas.clientWidth * dpr)), h = Math.max(1, Math.floor(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform2f(u.res, w, h);
      gl.uniform1f(u.t, reduced ? 2.0 : (performance.now() - start) / 1000);
      gl.uniform1f(u.hue, P.hue); gl.uniform1f(u.x, P.xOffset); gl.uniform1f(u.sp, P.speed);
      gl.uniform1f(u.it, P.intensity); gl.uniform1f(u.sz, P.size); gl.uniform1f(u.lt, P.light() ? 1 : 0);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };
    const loop = () => {
      if (!alive) return;
      draw();
      if (visible && !document.hidden && !reduced) raf = requestAnimationFrame(loop);
    };
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; cancelAnimationFrame(raf); if (visible) loop(); });
    io.observe(canvas);
    const onVis = () => { cancelAnimationFrame(raf); if (!document.hidden) loop(); };
    document.addEventListener("visibilitychange", onVis);
    addEventListener("resize", draw);
    loop();
    return {
      set(o) { Object.assign(P, o); if (reduced || !visible) draw(); },
      redraw: draw,
      destroy() { alive = false; cancelAnimationFrame(raf); io.disconnect(); document.removeEventListener("visibilitychange", onVis); removeEventListener("resize", draw); },
    };
  }

  window.Lightning = { mount };
})();
