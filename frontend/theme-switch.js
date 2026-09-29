/* Light/dark theme switch with a WebGL2 "flow glass" track.
 * Vanilla port of the ThemeSwitchFlowGlass React component (shadcn Switch + next-themes):
 * same shader, glass overlay, thumb travel, icon states, mouse parallax and reduced-motion handling.
 * Emits a "themechange" event on <html> with detail {theme}. */
(() => {
  "use strict";
  const root = document.documentElement;
  const btn = document.getElementById("btn-theme");
  if (!btn) return;
  const canvas = btn.querySelector(".ts-canvas");
  const intensity = 1;
  const reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isDark = () => root.dataset.theme === "dark";

  const sync = () => btn.setAttribute("aria-checked", String(isDark()));
  sync();
  btn.addEventListener("click", () => {
    const theme = isDark() ? "light" : "dark";
    root.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch (_) { /* storage blocked */ }
    sync();
    root.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
  });

  // ---- mouse parallax (eased toward the pointer, back to centre on leave)
  const hover = { x: 0.5, y: 0.5 };
  btn.addEventListener("mousemove", (e) => {
    const r = btn.getBoundingClientRect();
    hover.x += ((e.clientX - r.left) / Math.max(1, r.width) - hover.x) * 0.25;
    hover.y += ((e.clientY - r.top) / Math.max(1, r.height) - hover.y) * 0.25;
  });
  btn.addEventListener("mouseleave", () => { hover.x += (0.5 - hover.x) * 0.25; hover.y += (0.5 - hover.y) * 0.25; });

  // ---- WebGL2 shader background (graceful fallback: plain track colour)
  const gl = canvas.getContext("webgl2", { antialias: true, premultipliedAlpha: true });
  if (!gl) return;

  const vert = `#version 300 es
    precision highp float;
    layout(location=0) in vec2 a_pos;
    out vec2 v_uv;
    void main(){ v_uv = a_pos * 0.5 + 0.5; gl_Position = vec4(a_pos, 0.0, 1.0); }`;

  const frag = `#version 300 es
    precision highp float;
    out vec4 fragColor;
    in vec2 v_uv;
    uniform vec2 iResolution; uniform float iTime; uniform int iTheme; uniform vec2 iMouse; uniform float iPower;
    float hash(vec2 p){ p=fract(p*vec2(123.34,456.21)); p+=dot(p,p+45.32); return fract(p.x*p.y); }
    float noise(vec2 p){ vec2 i=floor(p), f=fract(p);
      float a=hash(i), b=hash(i+vec2(1.,0.)), c=hash(i+vec2(0.,1.)), d=hash(i+vec2(1.,1.));
      vec2 u=f*f*(3.-2.*f); return mix(mix(a,b,u.x), mix(c,d,u.x), u.y); }
    float fbm(vec2 p){ float s=0.0, a=0.5; for(int i=0;i<5;i++){ s+=a*noise(p); p*=2.0; a*=0.5; } return s; }
    vec2 flow(vec2 p){ float e=0.01; float n1=fbm(p), nx=fbm(p+vec2(e,0.0)), ny=fbm(p+vec2(0.0,e));
      vec2 g=vec2(nx-n1, ny-n1)/e; return vec2(-g.y, g.x); }
    vec3 tonemap(vec3 c){ return c/(c+vec3(1.0)); }
    void main(){
      vec2 uv = v_uv;
      vec2 center = mix(vec2(0.5), iMouse, 0.35);
      vec2 p = uv - center;
      p.x *= iResolution.x / max(iResolution.y, 1.0);
      float t = iTime * (0.6 + 0.6*iPower);
      vec2 q = p * (2.2 + 0.2*iPower);
      q += 0.15 * flow(q + vec2(t*0.2, -t*0.17));
      q += 0.10 * flow(q*1.7 + vec2(-t*0.18, t*0.21));
      float f1 = fbm(q*2.0 + vec2(t*0.10, -t*0.13));
      float f2 = fbm(q*3.4 + vec2(-t*0.09, t*0.07));
      float ink = smoothstep(0.25, 0.85, 0.55*f1 + 0.45*f2);
      float th = float(iTheme);
      vec3 base = mix(vec3(1.00,0.96,0.90), vec3(0.86,0.92,1.00), th);
      vec3 colInk = mix(vec3(0.22,0.20,0.18), vec3(0.18,0.22,0.28), th);
      vec3 colBg  = mix(vec3(0.97,0.98,1.00), vec3(0.10,0.12,0.16), th);
      vec3 col = mix(colBg, mix(base, colInk, 0.35), ink);
      float sweep = 0.25 + 0.25*sin(t*0.9 + uv.x*6.0 - uv.y*3.0);
      float h = smoothstep(0.03, 0.0, abs(length(p*vec2(1.2,1.8)) - sweep));
      col += 0.15 * mix(vec3(1.0,0.95,0.85), vec3(0.80,0.88,1.0), th) * h;
      col *= mix(1.0, 0.93, smoothstep(0.78, 0.35, length(p)));
      fragColor = vec4(tonemap(col), 0.88);
    }`;

  const compile = (type, src) => {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src); gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) { console.error("[ThemeSwitch]", gl.getShaderInfoLog(sh)); return null; }
    return sh;
  };
  const vs = compile(gl.VERTEX_SHADER, vert), fs = compile(gl.FRAGMENT_SHADER, frag);
  if (!vs || !fs) return;
  const prog = gl.createProgram();
  gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.bindAttribLocation(prog, 0, "a_pos"); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.error("[ThemeSwitch]", gl.getProgramInfoLog(prog)); return; }
  gl.deleteShader(vs); gl.deleteShader(fs);

  gl.bindVertexArray(gl.createVertexArray());
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  const U = (n) => gl.getUniformLocation(prog, n);
  const u = { res: U("iResolution"), time: U("iTime"), theme: U("iTheme"), mouse: U("iMouse"), power: U("iPower") };

  let start = 0;
  const render = (ts) => {
    if (!start) start = ts;
    const dpr = Math.min(2, window.devicePixelRatio || 1), r = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(r.width * dpr)), h = Math.max(1, Math.floor(r.height * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, w, h);
    gl.useProgram(prog);
    gl.uniform2f(u.res, w, h);
    gl.uniform1f(u.time, reduced ? 0 : (ts - start) / 1000);
    gl.uniform1i(u.theme, isDark() ? 1 : 0);
    gl.uniform2f(u.mouse, hover.x, hover.y);
    gl.uniform1f(u.power, Math.max(0.5, Math.min(2, intensity)));
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    // pause the animation while the tab is hidden to save battery
    if (!document.hidden) requestAnimationFrame(render);
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) requestAnimationFrame(render); });
  requestAnimationFrame(render);
})();
