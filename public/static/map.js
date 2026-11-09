/* Cirrus weather map: a small self-contained slippy map (no libraries) with
   animated wind, heat layers, isobars, RainViewer radar and a 48-hour timeline. */
(() => {
  'use strict';

  const TILE = 256, RAD = Math.PI / 180;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const mod = (a, n) => ((a % n) + n) % n;
  const $ = (sel, root = document) => root.querySelector(sel);
  const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  const compass = (deg) => COMPASS[Math.floor(mod(deg, 360) / 22.5 + 0.5) % 16];
  const reducedMotion = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------------------------------------------------------------- projection */
  const worldPx = (z) => TILE * 2 ** z;
  function project(lat, lon, z) {
    const s = worldPx(z), sin = Math.sin(clamp(lat, -85.0511, 85.0511) * RAD);
    return [(lon + 180) / 360 * s, (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s];
  }
  function unproject(x, y, z) {
    const s = worldPx(z), n = Math.PI - 2 * Math.PI * y / s;
    return [Math.atan(Math.sinh(n)) / RAD, x / s * 360 - 180];
  }

  class Emitter {
    on(type, fn) { ((this._h ??= {})[type] ??= []).push(fn); return this; }
    emit(type, ...args) { for (const fn of this._h?.[type] ?? []) fn(...args); }
  }

  /* ---------------------------------------------------------------- the map itself */
  class SlippyMap extends Emitter {
    constructor(box, { lat, lon, zoom, minZoom = 3, maxZoom = 11 }) {
      super();
      Object.assign(this, { box, lat, lon, zoom, zoomTarget: zoom, minZoom, maxZoom });
      this.size = { w: 1, h: 1, dpr: 1 };
      this.anchor = null; this.vx = 0; this.vy = 0; this.dragging = false; this.dirty = true;
      this.lastMove = 0; this.pointers = new Map(); this.pinch = null; this.tap = null; this.samples = [];
      this._bind();
      this.resize();
    }
    resize() {
      const r = this.box.getBoundingClientRect();
      this.size = { w: Math.max(1, r.width), h: Math.max(1, r.height), dpr: Math.min(window.devicePixelRatio || 1, 2) };
      this.emit('resize');
      this.dirty = true;
    }
    invalidate() { this.dirty = true; }
    viewChanged() { this.dirty = true; this.lastMove = performance.now(); this.emit('viewchange'); }
    get moving() {
      return this.dragging || !!this.pinch || !!this.anchor || Math.abs(this.vx) + Math.abs(this.vy) > 0.01
        || performance.now() - this.lastMove < 140;
    }
    frame() { const [cx, cy] = project(this.lat, this.lon, this.zoom); return { cx, cy, s: worldPx(this.zoom) }; }
    toScreen(lat, lon) {
      const f = this.frame(), [x, y] = project(lat, lon, this.zoom);
      return [this.size.w / 2 + x - f.cx, this.size.h / 2 + y - f.cy];
    }
    latLonAt(x, y) {
      const f = this.frame();
      return unproject(f.cx + x - this.size.w / 2, f.cy + y - this.size.h / 2, this.zoom);
    }
    bounds() {
      const [north, west] = this.latLonAt(0, 0), [south, east] = this.latLonAt(this.size.w, this.size.h);
      return { south, west, north, east };
    }
    _centerFromPx(cx, cy) {
      const [lat, lon] = unproject(cx, cy, this.zoom);
      this.lat = clamp(lat, -84, 84);
      this.lon = mod(lon + 180, 360) - 180;
    }
    panBy(dx, dy) { const f = this.frame(); this._centerFromPx(f.cx - dx, f.cy - dy); this.viewChanged(); }
    zoomAround(z, sx, sy) {
      z = clamp(z, this.minZoom, this.maxZoom);
      const [alat, alon] = this.latLonAt(sx, sy);
      this.zoom = z;
      const [px, py] = project(alat, alon, z);
      this._centerFromPx(px - (sx - this.size.w / 2), py - (sy - this.size.h / 2));
      this.viewChanged();
    }
    zoomBy(delta, sx = this.size.w / 2, sy = this.size.h / 2) {
      const base = this.anchor ? this.zoomTarget : this.zoom;
      this.zoomTarget = clamp(base + delta, this.minZoom, this.maxZoom);
      this.anchor = { x: sx, y: sy };
    }
    setView(lat, lon, zoom) { this.lat = lat; this.lon = lon; this.zoom = this.zoomTarget = clamp(zoom, this.minZoom, this.maxZoom); this.anchor = null; this.viewChanged(); }
    step(dt) {
      if (this.anchor) {
        const dz = this.zoomTarget - this.zoom;
        if (Math.abs(dz) < 0.003) { this.zoomAround(this.zoomTarget, this.anchor.x, this.anchor.y); this.anchor = null; }
        else this.zoomAround(this.zoom + dz * (1 - Math.exp(-dt / 85)), this.anchor.x, this.anchor.y);
      }
      if (!this.dragging && !this.pinch && Math.abs(this.vx) + Math.abs(this.vy) > 0.01) {
        this.panBy(this.vx * dt, this.vy * dt);
        const k = Math.exp(-dt / 220);
        this.vx *= k; this.vy *= k;
        if (Math.abs(this.vx) + Math.abs(this.vy) <= 0.01) this.vx = this.vy = 0;
      }
    }
    _pt(e) { const r = this.box.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
    _bind() {
      const el = this.box;
      el.addEventListener('pointerdown', (e) => {
        if (e.button > 0) return;
        el.setPointerCapture(e.pointerId);
        const p = this._pt(e);
        this.pointers.set(e.pointerId, { ...p, type: e.pointerType });
        if (this.pointers.size === 1) {
          this.dragging = true; this.vx = this.vy = 0; this.anchor = null; this.zoomTarget = this.zoom;
          this.tap = { x: p.x, y: p.y, t: performance.now() };
          this.samples = [{ t: performance.now(), x: p.x, y: p.y }];
          el.classList.add('dragging');
        } else if (this.pointers.size === 2) {
          this.tap = null;
          const [a, b] = [...this.pointers.values()];
          this.pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, z: this.zoom, mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
        }
      });
      el.addEventListener('pointermove', (e) => {
        const p = this._pt(e), prev = this.pointers.get(e.pointerId);
        if (!prev) { if (e.pointerType === 'mouse') this._hover(p); return; }
        if (this.pinch && this.pointers.size === 2) {
          this.pointers.set(e.pointerId, { ...p, type: prev.type });
          const [a, b] = [...this.pointers.values()];
          const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
          this.panBy(mx - this.pinch.mx, my - this.pinch.my);
          this.zoomAround(this.pinch.z + Math.log2(d / this.pinch.d), mx, my);
          this.zoomTarget = this.zoom;
          this.pinch.mx = mx; this.pinch.my = my;
          return;
        }
        this.pointers.set(e.pointerId, { ...p, type: prev.type });
        if (!this.dragging) return;
        this.panBy(p.x - prev.x, p.y - prev.y);
        const now = performance.now();
        this.samples.push({ t: now, x: p.x, y: p.y });
        while (this.samples.length > 2 && now - this.samples[0].t > 100) this.samples.shift();
        if (this.tap && Math.hypot(p.x - this.tap.x, p.y - this.tap.y) > 6) this.tap = null;
        this.emit('leave');
      });
      const end = (e) => {
        const p = this._pt(e);
        if (!this.pointers.delete(e.pointerId)) return;
        if (this.pinch) {
          this.pinch = null;
          const rest = [...this.pointers.entries()][0];
          if (rest) { this.tap = null; this.samples = [{ t: performance.now(), x: rest[1].x, y: rest[1].y }]; }
        }
        if (this.pointers.size === 0) {
          this.dragging = false;
          el.classList.remove('dragging');
          if (e.type === 'pointerup' && this.tap && performance.now() - this.tap.t < 500) {
            const [lat, lon] = this.latLonAt(p.x, p.y);
            this.emit('click', lat, lon, p.x, p.y);
          } else if (this.samples.length > 1) {
            const a = this.samples[0], b = this.samples[this.samples.length - 1], dt = b.t - a.t;
            if (dt > 0 && performance.now() - b.t < 80) { this.vx = clamp((b.x - a.x) / dt, -3, 3); this.vy = clamp((b.y - a.y) / dt, -3, 3); }
          }
          this.tap = null;
        }
      };
      el.addEventListener('pointerup', end);
      el.addEventListener('pointercancel', end);
      el.addEventListener('pointerleave', () => this.emit('leave'));
      el.addEventListener('wheel', (e) => {
        e.preventDefault();
        const p = this._pt(e), d = e.deltaY * (e.deltaMode === 1 ? 16 : 1);
        this.zoomBy(-d * (e.ctrlKey ? 0.012 : 0.0035), p.x, p.y);
      }, { passive: false });
      el.addEventListener('dblclick', (e) => { const p = this._pt(e); this.zoomBy(1, p.x, p.y); });
      new ResizeObserver(() => this.resize()).observe(el);
    }
    _hover(p) {
      const [lat, lon] = this.latLonAt(p.x, p.y);
      this.emit('hover', lat, lon, p.x, p.y);
    }
  }

  /* ---------------------------------------------------------------- tiles */
  class TileLayer {
    constructor(map, canvas, { template = null, maxNative = 19 } = {}) {
      Object.assign(this, { map, canvas, template, maxNative, prev: null });
      this.ctx = canvas.getContext('2d');
      this.cache = new Map();
    }
    setTemplate(t) { if (t === this.template) return; this.prev = this.template; this.template = t; this.map.invalidate(); }
    clear() { const { w, h, dpr } = this.map.size; this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); this.ctx.clearRect(0, 0, w, h); }
    _tile(tpl, z, x, y, load) {
      const key = `${tpl}|${z}/${x}/${y}`;
      let e = this.cache.get(key);
      if (!e && load) {
        const img = new Image();
        e = { img, ok: false, err: false };
        img.onload = () => { e.ok = true; this.map.invalidate(); };
        img.onerror = () => { e.err = true; };
        img.src = tpl.replace('{z}', z).replace('{x}', x).replace('{y}', y);
        this.cache.set(key, e);
        if (this.cache.size > 700) this.cache.delete(this.cache.keys().next().value);
      }
      return e;
    }
    draw() {
      const { map, ctx } = this, { w, h } = map.size;
      this.clear();
      if (!this.template) return;
      const z = clamp(Math.round(map.zoom), 0, this.maxNative), scale = 2 ** (map.zoom - z), n = 2 ** z;
      const [cx, cy] = project(map.lat, map.lon, z);
      const left = cx - w / 2 / scale, top = cy - h / 2 / scale;
      const x0 = Math.floor(left / TILE), x1 = Math.floor((left + w / scale) / TILE);
      const y0 = Math.max(0, Math.floor(top / TILE)), y1 = Math.min(n - 1, Math.floor((top + h / scale) / TILE));
      const tiles = [];
      for (let ty = y0; ty <= y1; ty++) for (let tx = x0; tx <= x1; tx++) tiles.push([tx, ty]);
      let tpl = this.template;
      if (this.prev) {                       // keep showing the previous radar frame until the new one has loaded
        let ready = true;
        for (const [tx, ty] of tiles) { const e = this._tile(this.template, z, mod(tx, n), ty, true); if (!e.ok && !e.err) ready = false; }
        if (ready) this.prev = null; else tpl = this.prev;
      }
      const size = TILE * scale + 0.6;
      for (const [tx, ty] of tiles) {
        const wx = mod(tx, n), sx = (tx * TILE - left) * scale, sy = (ty * TILE - top) * scale;
        const e = this._tile(tpl, z, wx, ty, true);
        if (e.ok) { ctx.drawImage(e.img, sx, sy, size, size); continue; }
        for (let k = 1; k <= 3 && z - k >= 0; k++) {   // blurry parent tile while the sharp one loads
          const p = this._tile(tpl, z - k, wx >> k, ty >> k, false);
          if (p?.ok) { const s = TILE / 2 ** k, m = (1 << k) - 1; ctx.drawImage(p.img, (wx & m) * s, (ty & m) * s, s, s, sx, sy, size, size); break; }
        }
      }
    }
  }

  /* ---------------------------------------------------------------- gridded forecast data */
  class Field {
    constructor(d) {
      Object.assign(this, { nx: d.nx, ny: d.ny, south: d.south, west: d.west, dx: d.dlon, dy: d.dlat, zoom: d.zoom ?? 0 });
      this.times = d.times.map((t) => Date.parse(t + 'Z'));
      this.T = this.times.length; this.n = this.nx * this.ny; this._s = {};
      this.vars = {}; this.req = '';
      this.add(d);
    }
    has(name) { return !!this.vars[name]; }
    same(d) {
      return d.nx === this.nx && d.ny === this.ny && d.south === this.south && d.west === this.west
        && d.dlon === this.dx && d.dlat === this.dy && d.times.length === this.T;
    }
    add(d) {   // the server sends only the variables asked for, so more can be merged in later
      for (const [k, rows] of Object.entries(d.vars)) { this.vars[k] = rows.map((r) => Float32Array.from(r)); delete this._s[k]; }
      const ws = this.vars.wind_speed_10m, wd = this.vars.wind_direction_10m;   // km/h, degrees the wind comes FROM
      if (ws && wd) {
        this.vars.u = ws.map((row, t) => row.map((s, k) => -s * Math.sin(wd[t][k] * RAD)));
        this.vars.v = ws.map((row, t) => row.map((s, k) => -s * Math.cos(wd[t][k] * RAD)));
        delete this._s.u; delete this._s.v;
      }
    }
    covers(b) {
      return b.west >= this.west && b.east <= this.west + (this.nx - 1) * this.dx
        && b.south >= this.south && b.north <= this.south + (this.ny - 1) * this.dy;
    }
    slice(name, ft) {
      const f = clamp(ft, 0, this.T - 1), rows = this.vars[name], t0 = Math.floor(f), a = f - t0;
      if (a < 0.002 || t0 >= this.T - 1) return rows[Math.min(this.T - 1, t0 + (a > 0.5 ? 1 : 0))];
      let c = this._s[name];
      if (c && c.f === f) return c.arr;
      if (!c) c = this._s[name] = { f: -1, arr: new Float32Array(this.n) };
      const A = rows[t0], B = rows[t0 + 1], out = c.arr;
      for (let k = 0; k < this.n; k++) out[k] = A[k] + (B[k] - A[k]) * a;
      c.f = f;
      return out;
    }
    interp(arr, lat, lon) {
      let gx = (lon - this.west) / this.dx, gy = (lat - this.south) / this.dy;
      if (gx < -0.5 || gy < -0.5 || gx > this.nx - 0.5 || gy > this.ny - 0.5) return NaN;
      gx = clamp(gx, 0, this.nx - 1.0001); gy = clamp(gy, 0, this.ny - 1.0001);
      const i = gx | 0, j = gy | 0, fx = gx - i, fy = gy - j, k = j * this.nx + i, nx = this.nx;
      return (arr[k] * (1 - fx) + arr[k + 1] * fx) * (1 - fy) + (arr[k + nx] * (1 - fx) + arr[k + nx + 1] * fx) * fy;
    }
    sample(name, ft, lat, lon) { return this.interp(this.slice(name, ft), lat, lon); }
    sampleAll(ft, lat, lon) {
      const g = (n) => (this.has(n) ? this.sample(n, ft, lat, lon) : NaN), u = g('u'), v = g('v');
      return { temp: g('temperature_2m'), rh: g('relative_humidity_2m'), rain: g('precipitation'), pressure: g('pressure_msl'),
        cloud: g('cloud_cover'), wind: g('wind_speed_10m'), gust: g('wind_gusts_10m'), dir: mod(Math.atan2(-u, -v) / RAD, 360) };
    }
  }

  /* ---------------------------------------------------------------- colour ramps + layer definitions */
  const RAMPS = {
    temp: { min: -25, max: 48, stops: [[-25, [130, 80, 210, .8]], [-10, [70, 110, 235, .8]], [0, [60, 170, 240, .8]], [10, [70, 200, 190, .8]],
      [18, [120, 210, 110, .78]], [24, [235, 225, 80, .8]], [30, [250, 170, 50, .82]], [36, [240, 100, 40, .85]], [42, [200, 40, 50, .88]], [48, [120, 20, 70, .9]]] },
    wind: { min: 0, max: 120, stops: [[0, [60, 120, 190, .5]], [8, [70, 170, 200, .55]], [16, [90, 200, 150, .6]], [25, [170, 215, 90, .62]],
      [35, [240, 215, 70, .65]], [50, [245, 150, 50, .7]], [70, [235, 80, 60, .75]], [95, [190, 40, 120, .8]], [120, [130, 40, 160, .85]]] },
    rain: { min: 0, max: 20, stops: [[0, [130, 200, 255, 0]], [0.05, [130, 200, 255, .25]], [0.5, [90, 170, 255, .6]], [2, [60, 110, 240, .75]],
      [5, [110, 70, 220, .8]], [10, [200, 60, 200, .85]], [20, [255, 160, 230, .9]]] },
    clouds: { min: 0, max: 100, stops: [[0, [235, 240, 247, 0]], [30, [215, 224, 235, .2]], [60, [205, 214, 226, .5]], [100, [240, 244, 250, .88]]] },
    pressure: { min: 980, max: 1040, stops: [[980, [120, 90, 200, .55]], [1000, [80, 150, 230, .45]], [1010, [110, 200, 200, .3]],
      [1016, [230, 220, 120, .35]], [1026, [245, 170, 80, .5]], [1040, [235, 90, 80, .6]]] },
    humidity: { min: 10, max: 100, stops: [[10, [220, 170, 90, .5]], [40, [150, 200, 120, .35]], [70, [70, 170, 190, .5]], [100, [40, 90, 200, .7]]] },
  };
  function buildLut(stops, min, max) {
    const lut = new Uint8ClampedArray(256 * 4);
    for (let i = 0; i < 256; i++) {
      const v = min + (max - min) * i / 255;
      let k = 0;
      while (k < stops.length - 2 && v > stops[k + 1][0]) k++;
      const [v0, c0] = stops[k], [v1, c1] = stops[k + 1], t = clamp((v - v0) / (v1 - v0), 0, 1);
      for (let c = 0; c < 3; c++) lut[i * 4 + c] = c0[c] + (c1[c] - c0[c]) * t;
      lut[i * 4 + 3] = (c0[3] + (c1[3] - c0[3]) * t) * 255;
    }
    return lut;
  }
  for (const r of Object.values(RAMPS)) r.lut = buildLut(r.stops, r.min, r.max);

  const LAYERS = {
    wind: { label: 'Wind speed', kind: 'field', var: 'wind_speed_10m', vars: ['wind_speed_10m', 'wind_direction_10m'], ramp: 'wind', particles: true,
      unit: (i) => (i ? 'mph' : 'km/h'), conv: (v, i) => (i ? v * 0.621371 : v), dec: () => 0 },
    radar: { label: 'Rain radar', kind: 'radar' },
    temp: { label: 'Temperature', kind: 'field', var: 'temperature_2m', ramp: 'temp',
      unit: (i) => (i ? '°F' : '°C'), conv: (v, i) => (i ? v * 9 / 5 + 32 : v), dec: () => 0 },
    rain: { label: 'Rain forecast', kind: 'field', var: 'precipitation', ramp: 'rain',
      unit: (i) => (i ? 'in/h' : 'mm/h'), conv: (v, i) => (i ? v / 25.4 : v), dec: (i) => (i ? 2 : 1) },
    clouds: { label: 'Cloud cover', kind: 'field', var: 'cloud_cover', ramp: 'clouds', unit: () => '%', conv: (v) => v, dec: () => 0 },
    pressure: { label: 'Sea-level pressure', kind: 'field', var: 'pressure_msl', ramp: 'pressure', isobars: true,
      unit: () => 'hPa', conv: (v) => v, dec: () => 0 },
    humidity: { label: 'Humidity', kind: 'field', var: 'relative_humidity_2m', ramp: 'humidity', unit: () => '%', conv: (v) => v, dec: () => 0 },
  };

  const ALL_VARS = ['temperature_2m', 'relative_humidity_2m', 'precipitation', 'pressure_msl', 'cloud_cover', 'wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m'];

  /* ---------------------------------------------------------------- field renderers */
  function drawHeat(ctx, map, off, field, ft, layer) {
    const { w, h, dpr } = map.size, CELL = 4, cw = Math.ceil(w / CELL), ch = Math.ceil(h / CELL);
    if (off.width !== cw || off.height !== ch) { off.width = cw; off.height = ch; off.img = off.getContext('2d').createImageData(cw, ch); }
    const ramp = RAMPS[layer.ramp], lut = ramp.lut, data = off.img.data, arr = field.slice(layer.var, ft);
    const f = map.frame(), kx = 360 / f.s, { nx, ny, west, south, dx, dy } = field, scale = 255 / (ramp.max - ramp.min);
    const lons = new Float64Array(cw);
    for (let i = 0; i < cw; i++) lons[i] = map.lon + ((i + 0.5) * CELL - w / 2) * kx;
    let p = 0;
    for (let j = 0; j < ch; j++) {
      const yy = f.cy + ((j + 0.5) * CELL - h / 2), lat = Math.atan(Math.sinh(Math.PI - 2 * Math.PI * yy / f.s)) / RAD;
      let gy = (lat - south) / dy;
      const rowOk = gy >= -0.5 && gy <= ny - 0.5;
      gy = clamp(gy, 0, ny - 1.0001);
      const j0 = gy | 0, fy = gy - j0;
      for (let i = 0; i < cw; i++, p += 4) {
        let gx = (lons[i] - west) / dx;
        if (!rowOk || gx < -0.5 || gx > nx - 0.5) { data[p + 3] = 0; continue; }
        gx = clamp(gx, 0, nx - 1.0001);
        const i0 = gx | 0, fx = gx - i0, k = j0 * nx + i0;
        const v = (arr[k] * (1 - fx) + arr[k + 1] * fx) * (1 - fy) + (arr[k + nx] * (1 - fx) + arr[k + nx + 1] * fx) * fy;
        const idx = clamp(((v - ramp.min) * scale) | 0, 0, 255) * 4;
        data[p] = lut[idx]; data[p + 1] = lut[idx + 1]; data[p + 2] = lut[idx + 2]; data[p + 3] = lut[idx + 3];
      }
    }
    off.getContext('2d').putImageData(off.img, 0, 0);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(off, 0, 0, cw, ch, 0, 0, w, h);
  }

  function drawIsobars(ctx, map, field, ft) {
    const arr = field.slice('pressure_msl', ft), { nx, ny } = field, { w, h } = map.size;
    const k = clamp(Math.ceil(48 / Math.max(1, nx - 1)), 1, 8), FN = (nx - 1) * k + 1, FM = (ny - 1) * k + 1;
    const F = new Float32Array(FN * FM);
    let lo = Infinity, hi = -Infinity;
    for (let fj = 0; fj < FM; fj++) {
      const gy = fj / k, j0 = Math.min(ny - 2, gy | 0), fy = gy - j0;
      for (let fi = 0; fi < FN; fi++) {
        const gx = fi / k, i0 = Math.min(nx - 2, gx | 0), fx = gx - i0, q = j0 * nx + i0;
        const v = (arr[q] * (1 - fx) + arr[q + 1] * fx) * (1 - fy) + (arr[q + nx] * (1 - fx) + arr[q + nx + 1] * fx) * fy;
        F[fj * FN + fi] = v;
        if (v < lo) lo = v; if (v > hi) hi = v;
      }
    }
    const X = new Float32Array(FN), Y = new Float32Array(FM);
    for (let i = 0; i < FN; i++) X[i] = map.toScreen(field.south, field.west + i * field.dx / k)[0];
    for (let j = 0; j < FM; j++) Y[j] = map.toScreen(field.south + j * field.dy / k, field.west)[1];
    ctx.lineWidth = 1.2; ctx.strokeStyle = 'rgba(255,255,255,.78)'; ctx.lineJoin = 'round';
    const labels = [];
    for (let L = Math.ceil(lo / 4) * 4; L <= hi; L += 4) {
      ctx.beginPath();
      let count = 0;
      for (let j = 0; j < FM - 1; j++) {
        if (Math.max(Y[j], Y[j + 1]) < -20 || Math.min(Y[j], Y[j + 1]) > h + 20) continue;
        for (let i = 0; i < FN - 1; i++) {
          const a = F[j * FN + i], b = F[j * FN + i + 1], c = F[(j + 1) * FN + i + 1], d = F[(j + 1) * FN + i];
          const m = (a > L ? 8 : 0) | (b > L ? 4 : 0) | (c > L ? 2 : 0) | (d > L ? 1 : 0);
          if (m === 0 || m === 15) continue;
          const T = () => [X[i] + (X[i + 1] - X[i]) * ((L - a) / (b - a)), Y[j]];
          const R = () => [X[i + 1], Y[j] + (Y[j + 1] - Y[j]) * ((L - b) / (c - b))];
          const B = () => [X[i] + (X[i + 1] - X[i]) * ((L - d) / (c - d)), Y[j + 1]];
          const Lf = () => [X[i], Y[j] + (Y[j + 1] - Y[j]) * ((L - a) / (d - a))];
          let segs;
          switch (m) {
            case 1: case 14: segs = [[Lf, B]]; break;
            case 2: case 13: segs = [[B, R]]; break;
            case 3: case 12: segs = [[Lf, R]]; break;
            case 4: case 11: segs = [[T, R]]; break;
            case 5: segs = [[T, Lf], [B, R]]; break;
            case 6: case 9: segs = [[T, B]]; break;
            case 7: case 8: segs = [[T, Lf]]; break;
            default: segs = [[T, R], [Lf, B]];
          }
          for (const [pa, pb] of segs) {
            const [x1, y1] = pa(), [x2, y2] = pb();
            ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
            const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
            if (++count % 45 === 20 && mx > 24 && mx < w - 24 && my > 24 && my < h - 24) labels.push([mx, my, L]);
          }
        }
      }
      ctx.stroke();
    }
    ctx.font = '600 11px Inter, system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(13,20,27,.85)'; ctx.fillStyle = '#fff';
    for (const [x, y, L] of labels) { ctx.strokeText(L, x, y); ctx.fillText(L, x, y); }
    // highs and lows on the original (coarse) grid
    if (nx > 3 && ny > 3) {
      ctx.font = '700 22px Inter, system-ui, sans-serif';
      for (let j = 1; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++) {
        const c = arr[j * nx + i];
        let isMax = true, isMin = true;
        for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
          if (!dj && !di) continue;
          const o = arr[(j + dj) * nx + i + di];
          if (o >= c) isMax = false;
          if (o <= c) isMin = false;
        }
        if (!isMax && !isMin) continue;
        const [x, y] = map.toScreen(field.south + j * field.dy, field.west + i * field.dx);
        if (x < 20 || x > w - 20 || y < 20 || y > h - 20) continue;
        ctx.fillStyle = isMax ? '#8FCBFF' : '#FF8A7A';
        ctx.lineWidth = 4; ctx.strokeStyle = 'rgba(13,20,27,.9)';
        ctx.strokeText(isMax ? 'H' : 'L', x, y - 8); ctx.fillText(isMax ? 'H' : 'L', x, y - 8);
        ctx.font = '600 11px Inter, system-ui, sans-serif'; ctx.lineWidth = 3;
        ctx.strokeText(Math.round(c), x, y + 9); ctx.fillStyle = '#fff'; ctx.fillText(Math.round(c), x, y + 9);
        ctx.font = '700 22px Inter, system-ui, sans-serif';
      }
    }
  }

  function drawArrows(ctx, map, field, ft) {          // calm alternative to particles (reduced motion)
    const { w, h } = map.size, us = field.slice('u', ft), vs = field.slice('v', ft);
    ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.fillStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 1.5; ctx.lineCap = 'round';
    for (let y = 30; y < h; y += 56) for (let x = 30; x < w; x += 56) {
      const [lat, lon] = map.latLonAt(x, y), u = field.interp(us, lat, lon), v = field.interp(vs, lat, lon);
      if (Number.isNaN(u)) continue;
      const sp = Math.hypot(u, v), len = 8 + Math.min(sp, 60) * 0.25, ang = Math.atan2(-v, u);
      ctx.save(); ctx.translate(x, y); ctx.rotate(ang);
      ctx.beginPath(); ctx.moveTo(-len, 0); ctx.lineTo(len, 0); ctx.moveTo(len - 5, -4); ctx.lineTo(len, 0); ctx.lineTo(len - 5, 4); ctx.stroke();
      ctx.restore();
    }
  }

  /* ---------------------------------------------------------------- animated wind */
  const PX_PER_KMH = 1.6;               // pixels per second for each km/h of wind
  class WindParticles {
    constructor(map, canvas) {
      Object.assign(this, { map, cv: canvas, step: 14, U: null, V: null, cols: 0, rows: 0, vu: 0, vv: 0, parts: [], ready: false });
      this.ctx = canvas.getContext('2d');
    }
    resize() {
      const { w, h } = this.map.size, n = clamp(Math.round(w * h / 1200), 250, 2000);
      this.parts = Array.from({ length: n }, () => ({ x: 0, y: 0, px: 0, py: 0, age: 0, life: 1 }));
      this.reset();
    }
    clear() { this.ctx.setTransform(1, 0, 0, 1, 0, 0); this.ctx.clearRect(0, 0, this.cv.width, this.cv.height); }
    reset() { for (const p of this.parts) this._spawn(p, true); this.clear(); }
    _spawn(p, randomAge) {
      const { w, h } = this.map.size;
      p.x = p.px = Math.random() * w; p.y = p.py = Math.random() * h;
      p.life = 0.9 + Math.random() * 1.8; p.age = randomAge ? Math.random() * p.life : 0;
    }
    build(field, ft) {
      const { w, h } = this.map.size, st = this.step;
      this.cols = Math.ceil(w / st) + 2; this.rows = Math.ceil(h / st) + 2;
      const n = this.cols * this.rows;
      if (!this.U || this.U.length !== n) { this.U = new Float32Array(n); this.V = new Float32Array(n); }
      const us = field.slice('u', ft), vs = field.slice('v', ft);
      for (let j = 0; j < this.rows; j++) for (let i = 0; i < this.cols; i++) {
        const [lat, lon] = this.map.latLonAt(i * st, j * st), k = j * this.cols + i;
        this.U[k] = field.interp(us, lat, lon) * PX_PER_KMH;
        this.V[k] = -field.interp(vs, lat, lon) * PX_PER_KMH;       // screen y points down
      }
      this.ready = true;
    }
    _lookup(x, y) {
      if (!this.ready) return false;
      const st = this.step, gx = x / st, gy = y / st, i = gx | 0, j = gy | 0, c = this.cols;
      if (gx < 0 || gy < 0 || i >= c - 1 || j >= this.rows - 1) return false;
      const fx = gx - i, fy = gy - j, k = j * c + i, U = this.U, V = this.V;
      const u = (U[k] * (1 - fx) + U[k + 1] * fx) * (1 - fy) + (U[k + c] * (1 - fx) + U[k + c + 1] * fx) * fy;
      const v = (V[k] * (1 - fx) + V[k + 1] * fx) * (1 - fy) + (V[k + c] * (1 - fx) + V[k + c + 1] * fx) * fy;
      if (Number.isNaN(u) || Number.isNaN(v)) return false;
      this.vu = u; this.vv = v;
      return true;
    }
    draw(dt) {
      const { ctx } = this, { w, h, dpr } = this.map.size;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.globalCompositeOperation = 'destination-out';
      ctx.fillStyle = `rgba(0,0,0,${1 - Math.exp(-dt / 520)})`;          // trails last roughly a second
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = 'source-over';
      const buckets = [new Path2D(), new Path2D(), new Path2D(), new Path2D()], s = dt / 1000;
      for (const p of this.parts) {
        p.age += s;
        if (p.age > p.life || !this._lookup(p.x, p.y)) { this._spawn(p, false); continue; }
        let vx = this.vu, vy = this.vv;
        const sp = Math.hypot(vx, vy);
        if (sp > 260) { vx *= 260 / sp; vy *= 260 / sp; }
        p.px = p.x; p.py = p.y; p.x += vx * s; p.y += vy * s;
        const b = sp < 25 ? 0 : sp < 60 ? 1 : sp < 120 ? 2 : 3;
        buckets[b].moveTo(p.px, p.py); buckets[b].lineTo(p.x, p.y);
      }
      ctx.lineWidth = 1.3; ctx.lineCap = 'round';
      const alphas = [0.5, 0.65, 0.8, 0.95];
      buckets.forEach((path, i) => { ctx.strokeStyle = `rgba(255,255,255,${alphas[i]})`; ctx.stroke(path); });
    }
  }

  /* ---------------------------------------------------------------- the controller */
  const PREFS_KEY = 'cirrus-map-prefs';
  const loadPrefs = () => { try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || {}; } catch { return {}; } };
  const savePrefs = (p) => { try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* storage may be blocked */ } };

  class WeatherMap {
    constructor(card) {
      this.card = card;
      const d = card.dataset;
      this.place = { lat: +d.lat, lon: +d.lon, name: d.name };
      this.imp = d.imperial === '1';
      this.prefs = loadPrefs();
      try { this.fmt = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true, timeZone: d.tz }); }
      catch { this.fmt = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true }); }

      this.stage = $('#map-stage', card); this.box = $('#map-layers', card);
      const mk = (cls) => { const c = document.createElement('canvas'); c.className = 'cv ' + cls; this.box.appendChild(c); return c; };
      this.cv = { base: mk('cv-base'), radar: mk('cv-radar'), field: mk('cv-field'), wind: mk('cv-wind') };
      this.off = document.createElement('canvas');
      this.map = new SlippyMap(this.box, { lat: this.place.lat, lon: this.place.lon, zoom: 6 });
      this.base = new TileLayer(this.map, this.cv.base, { template: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', maxNative: 19 });
      this.radarTiles = new TileLayer(this.map, this.cv.radar, { maxNative: 7 });
      this.wind = new WindParticles(this.map, this.cv.wind);
      this.fctx = this.cv.field.getContext('2d');

      Object.assign(this, { field: null, radar: null, ft: 0, ridx: 0, playing: false, acc: 0, seq: 0, layerId: null,
        windReset: true, windDirty: true, lastBuild: 0, lastFrame: 0, wasMoving: true, layerDirty: true, timeDirty: true, radarCleared: true });

      this.ui = {
        range: $('#tl-range', card), play: $('#btn-play', card), now: $('#btn-now', card), start: $('#tl-start', card),
        label: $('#tl-now', card), end: $('#tl-end', card), legend: $('#legend', card), chip: $('#cursor-chip', card),
        popup: $('#popup', card), status: $('#map-status', card), pin: $('#pin', card),
      };
      this.ui.pin.querySelector('.pin-label').textContent = this.place.name;
      this.pickPin = this.ui.pin.cloneNode(true); this.pickPin.id = 'pin-picked'; this.pickPin.classList.add('picked');
      this.pickPin.querySelector('.pin-label').textContent = '';
      this.ui.pin.after(this.pickPin); this.pickPin.hidden = true; this.ui.pin.hidden = false;
      this.picked = null;

      this.map.on('resize', () => this.onResize());
      this.map.on('viewchange', () => { this.windReset = true; this.windDirty = true; this.layerDirty = true; this.hideChip(); });
      this.map.on('hover', (lat, lon, x, y) => this.onHover(lat, lon, x, y));
      this.map.on('leave', () => this.hideChip());
      this.map.on('click', (lat, lon, x, y) => this.openPopup(lat, lon));
      this.bindUi();
      this.onResize();
      this.setBasemap(this.prefs.base || 'dark');
      this.setOpacity(this.prefs.opacity ?? 85);
      const start = this.prefs.layer && LAYERS[this.prefs.layer] ? this.prefs.layer : (LAYERS[d.layer] ? d.layer : 'wind');
      this.setLayer(start === 'radar' ? 'wind' : start, true);
      this.loadField(true);
      this.loadRadar(start === 'radar');
      requestAnimationFrame((t) => this.tick(t));
    }

    /* ---- setup */
    onResize() {
      const { w, h, dpr } = this.map.size;
      for (const c of Object.values(this.cv)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
      this.wind.resize(); this.windReset = true; this.windDirty = true; this.layerDirty = true; this.radarCleared = false;
    }
    bindUi() {
      const c = this.card, u = this.ui;
      c.querySelectorAll('[data-layer]').forEach((b) => b.addEventListener('click', () => this.setLayer(b.dataset.layer)));
      u.range.addEventListener('input', () => { this.stopPlay(); const v = +u.range.value; if (this.layerId === 'radar') this.ridx = v; else this.ft = v; this.timeChanged(); });
      u.play.addEventListener('click', () => (this.playing ? this.stopPlay() : this.startPlay()));
      u.now.addEventListener('click', () => { this.stopPlay(); if (this.layerId === 'radar') this.ridx = (this.radar?.frames.length || 1) - 1; else this.ft = 0; this.timeChanged(); });
      $('#zoom-in', c).addEventListener('click', () => this.map.zoomBy(1));
      $('#zoom-out', c).addEventListener('click', () => this.map.zoomBy(-1));
      $('#btn-base', c).addEventListener('click', () => this.setBasemap(this.stage.dataset.basemap === 'dark' ? 'light' : 'dark'));
      $('#btn-full', c).addEventListener('click', () => this.toggleFull());
      $('.opacity-range', c).addEventListener('input', (e) => this.setOpacity(+e.target.value));
      this.stage.addEventListener('keydown', (e) => {
        const k = e.key, step = 90;
        if (k === 'ArrowLeft') this.map.panBy(step, 0); else if (k === 'ArrowRight') this.map.panBy(-step, 0);
        else if (k === 'ArrowUp') this.map.panBy(0, step); else if (k === 'ArrowDown') this.map.panBy(0, -step);
        else if (k === '+' || k === '=') this.map.zoomBy(0.75); else if (k === '-' || k === '_') this.map.zoomBy(-0.75);
        else if (k === ' ') { this.playing ? this.stopPlay() : this.startPlay(); }
        else if (k === 'Escape') { if (!this.ui.popup.hidden) this.closePopup(); else if (c.classList.contains('is-full')) this.toggleFull(); else return; }
        else return;
        e.preventDefault();
      });
    }
    persist() { savePrefs({ ...this.prefs, layer: this.layerId, base: this.stage.dataset.basemap, opacity: this.opacityValue }); }
    setBasemap(b) { this.stage.dataset.basemap = b; this.persist(); }
    setOpacity(v) {
      this.opacityValue = v;
      this.cv.field.style.opacity = this.cv.radar.style.opacity = v / 100;
      $('.opacity-range', this.card).value = v;
      this.persist();
    }
    toggleFull() {
      const on = this.card.classList.toggle('is-full');
      document.body.classList.toggle('no-scroll', on);
      requestAnimationFrame(() => this.map.resize());
    }
    status(text, retry) {
      const s = this.ui.status;
      s.textContent = text || '';
      if (text && retry) { const b = document.createElement('button'); b.type = 'button'; b.textContent = 'Retry'; b.onclick = () => this.loadField(true); s.append(b); }
    }

    /* ---- data */
    layerVars(id = this.layerId) {
      const L = LAYERS[id];
      return L && L.kind === 'field' ? (L.vars || [L.var]) : [];
    }
    async fetchField(params, vars) {   // the server sends only the variables asked for, which keeps downloads small
      const qs = new URLSearchParams(params);
      qs.set('vars', vars.join(','));
      const res = await fetch('/api/field?' + qs);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    }
    async ensureVars(names) {   // add variables to the grid already on screen (same grid, so no new upstream calls)
      const f = this.field, missing = f ? names.filter((n) => !f.has(n)) : [];
      if (!missing.length) return;
      this.status('Loading weather grid…');
      try {
        const data = await this.fetchField(f.req, missing);
        if (this.field !== f) return;
        if (!f.same(data)) throw new Error('the grid changed, please retry');
        f.add(data);
        this.status('');
        this.layerDirty = this.timeDirty = this.windReset = this.windDirty = true;
        this.updateTimeline();
      } catch (err) {
        if (this.field === f) this.status(`Weather grid unavailable: ${err.message}`, true);
      }
    }
    async loadField(force = false) {
      const need = this.layerVars();
      if (!need.length && !force) return;   // the radar layer needs no grid
      const raw = this.map.bounds();
      const view = { south: clamp(raw.south, -85, 85), north: clamp(raw.north, -85, 85), west: clamp(raw.west, -180, 180), east: clamp(raw.east, -180, 180) };
      if (!force && this.field && this.field.covers(view) && this.map.zoom <= this.field.zoom + 1.2) { this.ensureVars(need); return; }
      // Round the request outward to a coarse lattice so visitors looking at the same area ask for the same address.
      // That lets the CDN and the browser answer without going back to the weather API.
      const zoom = this.map.zoom, step = zoom < 5 ? 2 : zoom < 7 ? 1 : zoom < 9 ? 0.5 : 0.25;
      const lo = (v, min) => Math.max(min, Math.floor(v / step) * step).toFixed(2);
      const hi = (v, max) => Math.min(max, Math.ceil(v / step) * step).toFixed(2);
      const qs = new URLSearchParams({ south: lo(view.south, -85), west: lo(view.west, -180), north: hi(view.north, 85), east: hi(view.east, 180), zoom: String(Math.round(zoom)) });
      const vars = need.length ? need : this.layerVars('wind'), key = qs.toString() + '|' + vars.join();
      if (this.pendingKey === key) return;   // this exact grid is already on its way: don't download it twice
      this.pendingKey = key;
      const seq = ++this.seq;
      this.status('Loading weather grid…');
      try {
        const data = await this.fetchField(qs, vars);
        if (seq !== this.seq) return;
        this.field = new Field(data);
        this.field.req = qs.toString();
        this.ft = clamp(this.ft, 0, this.field.T - 1);
        this.status('');
        this.layerDirty = this.timeDirty = this.windReset = this.windDirty = true;
        this.updateTimeline();
      } catch (err) {
        if (seq === this.seq) this.status(`Weather grid unavailable: ${err.message}`, true);
      } finally {
        if (this.pendingKey === key) this.pendingKey = null;
      }
    }
    async loadRadar(activate) {
      const chip = this.card.querySelector('[data-layer="radar"]');
      chip.disabled = true; chip.title = 'Loading radar…';
      try {
        const res = await fetch('/api/radar'), d = await res.json();
        if (!res.ok || !d.frames?.length) throw new Error(d.error || 'No radar frames');
        this.radar = d; this.ridx = d.frames.length - 1;
        chip.disabled = false; chip.title = 'Observed rain from weather radars (last two hours)';
        if (activate) this.setLayer('radar');
      } catch {
        chip.disabled = true; chip.title = 'Radar is not available right now';
      }
    }
    radarTemplate() {
      const f = this.radar.frames[this.ridx];
      return `${this.radar.host}${f.path}/256/{z}/{x}/{y}/2/1_1.png`;
    }

    /* ---- layers + timeline */
    setLayer(id, silent) {
      if (!LAYERS[id]) return;
      if (id === 'radar' && !this.radar) return;
      this.layerId = id;
      this.card.querySelectorAll('[data-layer]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.layer === id)));
      this.stopPlay(); this.hideChip();
      if (id === 'radar') this.radarTiles.setTemplate(this.radarTemplate()); else { this.radarTiles.template = this.radarTiles.prev = null; }
      this.radarCleared = false; this.layerDirty = this.windReset = this.windDirty = true;
      this.updateLegend(); this.updateTimeline();
      if (this.field && id !== 'radar') this.loadField();   // fetches this layer's variables if the grid doesn't have them yet
      if (!silent) this.persist();
    }
    timeChanged() {
      if (this.layerId === 'radar') this.radarTiles.setTemplate(this.radarTemplate());
      this.timeDirty = this.windDirty = true; this.layerDirty = true;
      this.updateTimeline(true);
    }
    fmtMs(ms) { return this.fmt.format(new Date(ms)); }
    updateTimeline(valueOnly) {
      const u = this.ui, radar = this.layerId === 'radar';
      const n = radar ? this.radar?.frames.length || 0 : this.field?.T || 0;
      u.range.disabled = n < 2;
      if (!valueOnly) { u.range.max = Math.max(0, n - 1); u.range.step = 1; }
      u.range.value = Math.round(radar ? this.ridx : this.ft);
      if (radar && n) {
        const fr = this.radar.frames;
        u.start.textContent = this.fmtMs(fr[0].time * 1000); u.end.textContent = this.fmtMs(fr[n - 1].time * 1000);
        u.label.textContent = this.fmtMs(fr[this.ridx].time * 1000) + ' · observed';
      } else if (this.field) {
        const ms = this.field.times[0] + this.ft * 3600e3, hrs = Math.round(this.ft);
        u.start.textContent = this.fmtMs(this.field.times[0]); u.end.textContent = this.fmtMs(this.field.times[this.field.T - 1]);
        u.label.textContent = this.fmtMs(ms) + (hrs ? ` · +${hrs} h` : ' · now');
      } else { u.label.textContent = 'Loading…'; u.start.textContent = u.end.textContent = ''; }
      u.range.setAttribute('aria-valuetext', u.label.textContent);
    }
    startPlay() {
      const n = this.layerId === 'radar' ? this.radar?.frames.length : this.field?.T;
      if (!n || n < 2) return;
      this.playing = true; this.acc = 0; this.ui.play.classList.add('on'); this.ui.play.setAttribute('aria-label', 'Pause animation');
    }
    stopPlay() { this.playing = false; this.ui.play.classList.remove('on'); this.ui.play.setAttribute('aria-label', 'Play animation'); }
    advance(dt) {
      if (this.layerId === 'radar') {
        this.acc += dt;
        if (this.acc < 650) return;
        this.acc = 0; this.ridx = (this.ridx + 1) % this.radar.frames.length;
      } else if (this.field) {
        this.ft += dt / 1000 * 2.2;
        if (this.ft >= this.field.T - 1) this.ft = 0;
      }
      this.timeChanged();
    }
    updateLegend() {
      const el = this.ui.legend, L = LAYERS[this.layerId], title = $('.legend-title', el), bar = $('.legend-bar', el), ticks = $('.legend-ticks', el);
      ticks.textContent = '';
      if (L.kind === 'radar') {
        title.textContent = 'Observed rain (RainViewer radar)';
        bar.style.background = 'linear-gradient(90deg,#9AD0F5,#2F7FE0,#4B3FC2,#B0239B,#FF9BE0)';
        ['Light', 'Moderate', 'Heavy'].forEach((t) => { const s = document.createElement('span'); s.textContent = t; ticks.append(s); });
        return;
      }
      const r = RAMPS[L.ramp], span = r.max - r.min;
      title.textContent = `${L.label} (${L.unit(this.imp)})`;
      bar.style.background = 'linear-gradient(90deg,' + r.stops.map(([v, c]) => `rgb(${c[0]},${c[1]},${c[2]}) ${((v - r.min) / span * 100).toFixed(1)}%`).join(',') + ')';
      for (let i = 0; i < 6; i++) {
        const v = L.conv(r.min + span * i / 5, this.imp), s = document.createElement('span');
        s.textContent = v.toFixed(L.dec(this.imp));
        ticks.append(s);
      }
    }

    /* ---- pointer feedback */
    hideChip() { this.ui.chip.hidden = true; }
    fmtValue(L, v) {
      const unit = L.unit(this.imp), sep = unit === '%' || unit.startsWith('°') ? '' : ' ';
      return `${L.conv(v, this.imp).toFixed(L.dec(this.imp))}${sep}${unit}`;
    }
    onHover(lat, lon) {
      const L = LAYERS[this.layerId], chip = this.ui.chip;
      if (!this.field || L.kind !== 'field' || !this.field.has(L.var)) { chip.hidden = true; return; }
      const v = this.field.sample(L.var, this.ft, lat, lon);
      if (Number.isNaN(v)) { chip.hidden = true; return; }
      chip.textContent = this.fmtValue(L, v);
      const small = document.createElement('small');
      if (L.var === 'wind_speed_10m') small.textContent = 'from the ' + compass(this.field.sampleAll(this.ft, lat, lon).dir);
      else small.textContent = `${lat.toFixed(2)}°, ${lon.toFixed(2)}°`;
      chip.append(small); chip.hidden = false;
    }
    openPopup(lat, lon) {
      this.picked = { lat, lon };
      const p = this.ui.popup;
      p.textContent = '';
      const h = document.createElement('h3'); h.textContent = 'Selected point'; p.append(h);
      const sub = document.createElement('div'); sub.className = 'muted';
      sub.textContent = `${lat.toFixed(2)}°, ${lon.toFixed(2)}°` + (this.field ? ' · ' + this.fmtMs(this.field.times[0] + this.ft * 3600e3) : '');
      p.append(sub);
      const x = document.createElement('button'); x.type = 'button'; x.className = 'x'; x.setAttribute('aria-label', 'Close');
      x.textContent = '×'; x.onclick = () => this.closePopup(); p.append(x);
      const s = this.field && this.field.sampleAll(this.ft, lat, lon);
      const partial = !!this.field && !ALL_VARS.every((n) => this.field.has(n));
      if (partial) {   // the grid holds only the active layer so far: fetch the rest, then draw the popup again
        const note = document.createElement('div'); note.className = 'muted'; note.textContent = 'Loading values…'; p.append(note);
        this.ensureVars(ALL_VARS).then(() => {
          if (!this.picked || this.picked.lat !== lat || this.picked.lon !== lon) return;
          if (this.field && ALL_VARS.every((n) => this.field.has(n))) this.openPopup(lat, lon);
          else note.textContent = 'Values unavailable right now.';
        });
      }
      if (s && !partial && !Number.isNaN(s.temp)) {
        const imp = this.imp, g = LAYERS;
        const rows = [['Temperature', this.fmtValue(g.temp, s.temp)], ['Wind', `${this.fmtValue(g.wind, s.wind)} ${compass(s.dir)}`],
          ['Gusts', this.fmtValue(g.wind, s.gust)], ['Rain', this.fmtValue(g.rain, s.rain)], ['Cloud', `${s.cloud.toFixed(0)}%`],
          ['Humidity', `${s.rh.toFixed(0)}%`], ['Pressure', imp ? `${(s.pressure * 0.02953).toFixed(2)} inHg` : `${s.pressure.toFixed(0)} hPa`]];
        const grid = document.createElement('div'); grid.className = 'vals';
        for (const [k, v] of rows) { const d = document.createElement('div'); d.append(k); const st = document.createElement('strong'); st.textContent = v; d.append(st); grid.append(d); }
        p.append(grid);
      }
      const a = document.createElement('a'); a.className = 'btn primary';
      a.href = '/forecast/overview?' + new URLSearchParams({ lat: lat.toFixed(4), lon: lon.toFixed(4), name: `Point ${lat.toFixed(2)}, ${lon.toFixed(2)}`, ...(this.imp ? { u: 'f' } : {}) });
      a.textContent = 'Full forecast here'; p.append(a);
      p.hidden = false; this.pickPin.hidden = false; this.map.invalidate();
    }
    closePopup() { this.ui.popup.hidden = true; this.pickPin.hidden = true; this.picked = null; }
    placeOverlays() {
      const { w, h } = this.map.size, put = (el, lat, lon) => {
        const [x, y] = this.map.toScreen(lat, lon);
        el.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px)`;
        el.style.visibility = x < -20 || y < -20 || x > w + 20 || y > h + 20 ? 'hidden' : 'visible';
        return [x, y];
      };
      put(this.ui.pin, this.place.lat, this.place.lon);
      if (this.picked) {
        const [x, y] = put(this.pickPin, this.picked.lat, this.picked.lon), p = this.ui.popup, ph = p.offsetHeight || 220;
        p.style.left = `${clamp(x - 125, 8, Math.max(8, w - 258))}px`;
        p.style.top = `${y - ph - 18 < 8 ? y + 18 : y - ph - 18}px`;
      }
    }

    /* ---- frame loop */
    render() {
      const L = LAYERS[this.layerId], map = this.map, { w, h, dpr } = map.size;
      this.base.draw();
      if (L.kind === 'radar') this.radarTiles.draw(); else if (!this.radarCleared) { this.radarTiles.clear(); this.radarCleared = true; }
      this.fctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (L.kind === 'field' && this.field && this.field.has(L.var)) {
        drawHeat(this.fctx, map, this.off, this.field, this.ft, L);
        if (L.isobars) drawIsobars(this.fctx, map, this.field, this.ft);
        if (L.particles && reducedMotion && this.field.has('u')) drawArrows(this.fctx, map, this.field, this.ft);
      } else this.fctx.clearRect(0, 0, w, h);
      this.placeOverlays();
    }
    tick(now) {
      const dt = Math.min(50, now - (this.lastFrame || now));
      this.lastFrame = now;
      const map = this.map;
      map.step(dt);
      if (this.playing) this.advance(dt);
      const moving = map.moving;
      if (this.wasMoving && !moving) this.loadField();
      this.wasMoving = moving;
      if (map.dirty || this.layerDirty || this.timeDirty) { map.dirty = this.layerDirty = this.timeDirty = false; this.render(); }
      const L = LAYERS[this.layerId];
      if (L.particles && this.field && this.field.has('u') && !reducedMotion) {
        if (moving) { if (this.windReset) { this.wind.clear(); this.wind.ready = false; } }
        else {
          if (this.windDirty && (now - this.lastBuild > 110 || this.windReset)) {
            this.wind.build(this.field, this.ft);
            this.lastBuild = now; this.windDirty = false;
            if (this.windReset) { this.wind.reset(); this.windReset = false; }
          }
          if (this.wind.ready) this.wind.draw(dt);
        }
      } else if (this.windReset) { this.wind.clear(); this.windReset = false; }
      requestAnimationFrame((t) => this.tick(t));
    }
  }

  const boot = () => {
    const card = document.getElementById('mapcard');
    if (card && !window.cirrusMap) window.cirrusMap = new WeatherMap(card);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
