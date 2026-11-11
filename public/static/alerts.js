/* Cirrus alerts: your home, alerts for home and for where you are now, an alarm sound, device notifications and e-mail.
   Everything about you stays in this browser unless you choose e-mail alerts. */
(() => {
  'use strict';
  const KEY = 'cirrus:v1', AWAY_KM = 25, EVERY = 5 * 60e3;
  const LABEL = { 1: 'Advisory', 2: 'Watch', 3: 'Warning', 4: 'Extreme' };
  const KIND = { heat: 'Heat', cold: 'Cold', rain: 'Heavy rain', wind: 'Wind', storm: 'Thunderstorm', snow: 'Snow', fog: 'Fog', air: 'Air quality',
    earthquake: 'Earthquake', cyclone: 'Cyclone', flood: 'Flood', volcano: 'Volcano', wildfire: 'Wildfire', landslide: 'Landslide' };
  const $ = (s, r = document) => r.querySelector(s);
  const RAD = Math.PI / 180;
  const km = (a, b, c, d) => { const p = Math.sin((c - a) * RAD / 2) ** 2 + Math.cos(a * RAD) * Math.cos(c * RAD) * Math.sin((d - b) * RAD / 2) ** 2; return 12742 * Math.asin(Math.min(1, Math.sqrt(p))); };
  function h(tag, props, ...kids) {   // tiny DOM builder; text always goes in as text, never as HTML
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(kid));
    return n;
  }

  /* ------------------------------------------------------------ saved state */
  const DEFAULT = { home: null, prefs: {}, seen: {}, dismissed: {}, askedAt: 0 };
  let S = (() => { try { return { ...DEFAULT, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch { return { ...DEFAULT }; } })();
  const P = () => ({ minLevel: 3, sound: true, notify: false, away: true, email: '', token: '', pid: '', ...S.prefs });
  const setPrefs = (patch) => { S.prefs = { ...P(), ...patch }; save(); };
  function save() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch { /* private mode: still works for this visit */ } mirror(); }
  const idb = () => new Promise((ok, no) => { const r = indexedDB.open('cirrus', 1); r.onupgradeneeded = () => r.result.createObjectStore('kv'); r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
  function mirror() {   // the background worker cannot read localStorage, so it gets a copy
    if (!window.indexedDB) return;
    idb().then((db) => db.transaction('kv', 'readwrite').objectStore('kv').put({ places: watchList().map(({ lat, lon, name }) => ({ lat, lon, name })), minLevel: P().minLevel,
      notify: P().notify, seen: S.seen }, 'state')).catch(() => {});
  }

  /* ------------------------------------------------------------ places */
  let here = null, active = [], lastCheck = 0, geoState = 'prompt';
  const viewed = () => { const b = document.body.dataset; return b.lat ? { lat: +b.lat, lon: +b.lon, name: b.name } : null; };
  const awayFromHome = () => here && (!S.home || km(S.home.lat, S.home.lon, here.lat, here.lon) > AWAY_KM);
  function watchList() {   // places that can trigger an alarm or notification
    const out = [];
    if (S.home) out.push({ ...S.home, where: 'Home', key: 'home' });
    if (P().away && awayFromHome()) out.push({ ...here, name: here.name || 'Your location', where: 'Your location', key: 'here' });
    return out;
  }
  function publishPlaces(focus) {
    window.cirrusPlaces = { home: S.home, here, focus };
    document.dispatchEvent(new CustomEvent('cirrus:places'));
  }
  async function api(path, opts) {
    const res = await fetch(path, opts), body = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(body.error || `Request failed (${res.status})`), { status: res.status });
    return body;
  }
  const post = (path, data) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  function locate() {   // device location; asks the browser for permission the first time
    return new Promise((ok, no) => {
      if (!navigator.geolocation) return no(new Error('This device cannot share its location.'));
      navigator.geolocation.getCurrentPosition(async (pos) => {
        const p = { lat: +pos.coords.latitude.toFixed(3), lon: +pos.coords.longitude.toFixed(3), name: '' };
        geoState = 'granted';
        try { Object.assign(p, await api(`/api/reverse?lat=${p.lat}&lon=${p.lon}`)); } catch { p.name = `${p.lat}, ${p.lon}`; }
        here = p; publishPlaces(); ok(p);
      }, (e) => { geoState = e.code === 1 ? 'denied' : geoState; no(new Error(e.code === 1 ? 'Location access is blocked. Allow it in the browser’s site settings.' : 'Could not get your location.')); },
      { enableHighAccuracy: false, timeout: 12000, maximumAge: 600000 });
    });
  }

  /* ------------------------------------------------------------ alarm sound */
  let ctx = null, siren = null, wantSiren = null;
  function unlock() { try { ctx = ctx || new (window.AudioContext || window.webkitAudioContext)(); if (ctx.state === 'suspended') ctx.resume(); } catch { /* no audio */ } }
  ['pointerdown', 'keydown', 'touchstart'].forEach((t) => addEventListener(t, () => { unlock(); if (wantSiren) { const l = wantSiren; wantSiren = null; startSiren(l); } }, { passive: true }));
  function startSiren(level) {   // two alternating tones: 2 s for a watch, 6 s for a warning, 10 s for an extreme event
    stopSiren(); unlock();
    if (!ctx || ctx.state !== 'running') { wantSiren = level; renderBanner(); return; }
    const secs = level >= 4 ? 10 : level >= 3 ? 6 : 2, t0 = ctx.currentTime, gain = ctx.createGain(), osc = ctx.createOscillator(), lp = ctx.createBiquadFilter();
    osc.type = 'sawtooth'; lp.type = 'lowpass'; lp.frequency.value = 2200;
    for (let t = 0; t < secs; t += 0.6) { osc.frequency.setValueAtTime(960, t0 + t); osc.frequency.setValueAtTime(700, t0 + t + 0.3); }
    gain.gain.setValueAtTime(0.0001, t0); gain.gain.exponentialRampToValueAtTime(0.2, t0 + 0.08);
    gain.gain.setValueAtTime(0.2, t0 + secs - 0.2); gain.gain.exponentialRampToValueAtTime(0.0001, t0 + secs);
    osc.connect(lp); lp.connect(gain); gain.connect(ctx.destination); osc.start(t0); osc.stop(t0 + secs + 0.05);
    siren = osc; osc.onended = () => { if (siren === osc) { siren = null; renderBanner(); } };
    try { if (navigator.userActivation?.hasBeenActive) navigator.vibrate?.([300, 150, 300, 150, 600]); } catch { /* not supported */ }
    renderBanner();
  }
  function stopSiren() { wantSiren = null; if (siren) { const o = siren; siren = null; try { o.stop(); } catch { /* already stopped */ } } renderBanner(); }

  /* ------------------------------------------------------------ notifications */
  const canNotify = () => 'Notification' in window && Notification.permission === 'granted' && P().notify;
  async function showNotification(a, place) {
    if (!canNotify()) return;
    const title = `${a.label}: ${a.title}`, opts = { body: `${place} · ${a.when}\n${a.detail}`, tag: a.id, renotify: true, requireInteraction: a.level >= 3,
      icon: '/static/icon-192.png', badge: '/static/icon-192.png', vibrate: [300, 150, 300], silent: false, data: { url: a.lat != null ? `/forecast/overview?lat=${a.lat}&lon=${a.lon}&name=${encodeURIComponent(a.title)}` : S.home ? `/forecast/overview?lat=${S.home.lat}&lon=${S.home.lon}&name=${encodeURIComponent(S.home.name)}` : '/' } };
    try { const reg = await navigator.serviceWorker.ready; await reg.showNotification(title, opts); } catch { try { new Notification(title, opts); } catch { /* blocked */ } }
  }
  async function enableNotifications() {
    if (!('Notification' in window)) throw new Error('This browser does not support notifications. On iPhone, add Cirrus to the Home Screen first.');
    const perm = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
    if (perm !== 'granted') throw new Error('Notifications are blocked. Allow them in the browser’s site settings.');
    setPrefs({ notify: true }); unlock();
    try { const reg = await navigator.serviceWorker.ready; if (reg.periodicSync) await reg.periodicSync.register('cirrus-alerts', { minInterval: 3 * 3600e3 }); } catch { /* optional */ }
    active.filter((a) => a.key !== 'view' && a.level >= P().minLevel).slice(0, 3).forEach((a) => showNotification(a, `${a.place} (${(a.where || '').toLowerCase()})`));   // alerts already showing
  }
  if ('serviceWorker' in navigator) addEventListener('load', () => navigator.serviceWorker.register('/static/sw.js', { scope: '/' }).catch(() => {}));

  /* ------------------------------------------------------------ checking for alerts */
  async function check(force) {
    if (!force && Date.now() - lastCheck < 60e3) return;
    lastCheck = Date.now();
    const q = new URLSearchParams(location.search).get('u') === 'f' ? '&u=f' : '';
    if (P().away && geoState === 'granted') { try { await locate(); } catch { /* keep the last position */ } }
    const list = [...watchList()]; const v = viewed();
    if (v && !list.some((p) => km(p.lat, p.lon, v.lat, v.lon) < 5)) list.push({ ...v, where: 'Viewing', key: 'view' });
    const merged = new Map();
    await Promise.all(list.map(async (p) => {
      try {
        const d = await api(`/api/alerts?lat=${p.lat.toFixed(2)}&lon=${p.lon.toFixed(2)}&name=${encodeURIComponent(p.name || '')}${q}`);
        for (const a of d.alerts) { const old = merged.get(a.id); if (!old || p.key === 'home') merged.set(a.id, { ...a, place: p.name, where: p.where, key: p.key }); }
      } catch { /* a place that fails is skipped this round */ }
    }));
    active = [...merged.values()].sort((a, b) => b.level - a.level || (a.key === 'home' ? -1 : 1));
    const now = Date.now(), fresh = [];
    for (const a of active) if (a.key !== 'view' && a.level >= P().minLevel && !S.seen[a.id]) { S.seen[a.id] = now; fresh.push(a); }
    for (const id of Object.keys(S.seen)) if (now - S.seen[id] > 3 * 864e5) delete S.seen[id];
    save(); renderBanner(); renderBell(); if (dialog?.open) renderDialog();
    if (fresh.length) {
      fresh.sort((a, b) => b.level - a.level);
      if (P().sound) startSiren(fresh[0].level);
      fresh.slice(0, 4).forEach((a) => showNotification(a, `${a.place} (${a.where.toLowerCase()})`));
    }
    syncServerPosition();
  }
  let lastSent = 0;
  async function syncServerPosition() {   // e-mail alerts use the last place this device reported, only while the site is open
    const { token } = P(); if (!token) return;
    const away = P().away && awayFromHome() && here ? { lat: here.lat, lon: here.lon } : null;
    if (Date.now() - lastSent < 30 * 60e3 && !(S.sentAway && !away)) return;
    try { await post('/api/subscribe/update', { token, away }); S.sentAway = !!away; lastSent = Date.now(); save(); }
    catch (e) { if (e.status === 404) { setPrefs({ token: '' }); renderDialog(); } }
  }
  addEventListener('online', () => check(true));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
  setInterval(() => { if (!document.hidden) check(true); }, EVERY);

  /* ------------------------------------------------------------ banner and bell */
  let banner = null;
  function renderBanner() {
    banner = banner || $('#alert-banner'); if (!banner) return;
    const shown = active.filter((a) => (S.dismissed[a.id] || 0) < 1 && a.level >= 1);
    const top = shown[0];
    banner.hidden = !top && !siren && !wantSiren; banner.replaceChildren();
    if (banner.hidden) return;
    banner.dataset.level = top ? top.level : 3;
    if (top) banner.append(h('div', { class: 'ab-text' }, h('strong', null, `${top.label}: ${top.title}`), h('span', { class: 'ab-where' }, ` · ${top.place || 'here'} · ${top.when}`),
      shown.length > 1 ? h('span', { class: 'ab-more' }, ` +${shown.length - 1} more`) : null));
    const acts = h('div', { class: 'ab-actions' });
    if (siren) acts.append(h('button', { type: 'button', class: 'ab-btn', onclick: stopSiren }, 'Stop alarm'));
    else if (wantSiren) acts.append(h('button', { type: 'button', class: 'ab-btn', onclick: () => { const l = wantSiren; wantSiren = null; unlock(); startSiren(l); } }, 'Tap to sound the alarm'));
    acts.append(h('button', { type: 'button', class: 'ab-btn', onclick: () => openDialog('alerts') }, 'Details'));
    if (top) acts.append(h('button', { type: 'button', class: 'ab-btn ghost', 'aria-label': 'Dismiss', onclick: () => { for (const a of shown) S.dismissed[a.id] = 1; save(); renderBanner(); } }, 'Dismiss'));
    banner.append(acts);
  }
  function renderBell() {
    const b = $('#bell-badge'); if (!b) return;
    const n = active.length; b.hidden = !n; b.textContent = String(n);
    b.dataset.level = String(Math.max(0, ...active.map((a) => a.level)));
  }

  /* ------------------------------------------------------------ dialog */
  let dialog = null, tab = 'alerts', picking = false, cfg = { cloud: false }, events = null, pollTimer = 0, msg = {};
  function openDialog(which) {
    if (!dialog) {
      dialog = h('dialog', { class: 'cd', 'aria-label': 'Alerts and home settings' });
      dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });
      dialog.addEventListener('close', () => { clearInterval(pollTimer); });
      document.body.append(dialog);
    }
    tab = which || tab; picking = !S.home;
    if (!dialog.open) dialog.showModal();
    renderDialog();
    if (!events) api('/api/hazards').then((d) => { events = d.events; renderDialog(); }).catch(() => { events = []; });
    if (P().pid) pollConfirm();
  }
  const sec = (title, ...kids) => h('section', { class: 'cd-sec' }, h('h3', null, title), ...kids);
  const note = (text, cls) => h('p', { class: 'cd-note ' + (cls || '') }, text);
  function renderDialog() {
    if (!dialog || !dialog.open) return;
    const keepScroll = dialog.querySelector('.cd-body')?.scrollTop || 0;
    const tabs = h('div', { class: 'cd-tabs', role: 'tablist' }, ...[['alerts', `Alerts${active.length ? ` (${active.length})` : ''}`], ['settings', 'Home & notifications']].map(([id, label]) =>
      h('button', { type: 'button', role: 'tab', 'aria-selected': String(tab === id), onclick: () => { tab = id; renderDialog(); } }, label)));
    const body = h('div', { class: 'cd-body' }, tab === 'alerts' ? alertsTab() : settingsTab());
    dialog.replaceChildren(h('header', { class: 'cd-head' }, h('h2', null, 'Cirrus alerts'), h('button', { type: 'button', class: 'cd-x', 'aria-label': 'Close', onclick: () => dialog.close() }, '×')), tabs, body);
    body.scrollTop = keepScroll;
  }
  function alertCard(a) {
    return h('article', { class: 'al', 'data-level': a.level }, h('div', { class: 'al-top' }, h('span', { class: 'al-badge' }, a.label), h('strong', null, a.title)),
      h('div', { class: 'al-meta' }, `${KIND[a.kind] || a.kind} · ${a.place || ''} (${(a.where || '').toLowerCase()}) · ${a.when} · ${a.source}`),
      a.detail ? h('p', null, a.detail) : null, a.advice ? h('p', { class: 'al-advice' }, h('strong', null, 'What to do: '), a.advice) : null,
      /^https:\/\//.test(a.url || '') ? h('a', { href: a.url, target: '_blank', rel: 'noopener noreferrer' }, 'Source details') : null);
  }
  function alertsTab() {
    const out = [];
    if (!S.home) out.push(h('div', { class: 'cd-cta' }, h('p', null, 'Set your home to get alerts for it, even while you are somewhere else.'), h('button', { type: 'button', class: 'btn primary', onclick: () => { tab = 'settings'; picking = true; renderDialog(); } }, 'Set my home')));
    out.push(active.length ? h('div', { class: 'al-list' }, active.map(alertCard)) : h('p', { class: 'cd-empty' }, `No active alerts for ${[S.home && 'your home', awayFromHome() && 'your location', viewed() && viewed().name].filter(Boolean).join(', ') || 'the places you follow'}.`));
    out.push(note('Early warnings from forecast models and public feeds (USGS, GDACS, NASA). They are not official alerts: always follow your local weather and disaster authority.'));
    const ev = (events || []).filter((e) => e.level >= 2).slice(0, 8);
    out.push(sec('Serious events right now', ev.length ? h('ul', { class: 'ev-list' }, ev.map((e) => h('li', null, h('span', { class: 'dot', 'data-level': e.level }), h('span', null, e.title), h('small', null, ` ${LABEL[e.level]}`)))) : note(events ? 'Nothing serious is being reported worldwide.' : 'Loading…')));
    return out;
  }
  function settingsTab() { return [homeSection(), deviceSection(), emailSection(), prefsSection(), dataSection()]; }

  let searchTimer = 0, results = [];
  function homeSection() {
    if (S.home && !picking) {
      return sec('Your home', h('p', { class: 'cd-home' }, h('strong', null, S.home.name), ` ${[S.home.region, S.home.country].filter(Boolean).join(', ')}`),
        h('div', { class: 'cd-row' }, h('button', { type: 'button', class: 'btn', onclick: () => { picking = true; results = []; renderDialog(); } }, 'Change home'),
          h('a', { class: 'btn', href: `/forecast/overview?${new URLSearchParams({ lat: S.home.lat, lon: S.home.lon, name: S.home.name, region: S.home.region || '', country: S.home.country || '' })}` }, 'Open forecast')));
    }
    const input = h('input', { type: 'search', class: 'cd-input', placeholder: 'Search your city or town', 'aria-label': 'Search your city or town', autocomplete: 'off', value: msg.q || '' });
    const list = h('ul', { class: 'suggest', role: 'listbox' });
    const fill = () => list.replaceChildren(...results.map((r) => h('li', null, h('button', { type: 'button', onclick: () => chooseHome(r) }, h('strong', null, r.name), ` ${[r.admin1, r.country].filter(Boolean).join(', ')}`))));
    fill();
    input.addEventListener('input', () => {
      clearTimeout(searchTimer); msg.q = input.value;
      searchTimer = setTimeout(async () => { if (input.value.trim().length < 2) { results = []; fill(); return; }
        try { results = (await api(`/api/geocode?q=${encodeURIComponent(input.value.trim())}`)).results || []; } catch { results = []; } fill(); if (!results.length && input.value.trim().length > 1) list.append(h('li', { class: 'cd-empty' }, 'No matching place.')); }, 250);
    });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && results[0]) { e.preventDefault(); chooseHome(results[0]); } });
    return sec(S.home ? 'Choose a new home' : 'Step 1: choose your home', note('Search for your city or town, or let this device find where you are.'), input, list,
      h('div', { class: 'cd-row' }, h('button', { type: 'button', class: 'btn primary', onclick: async (e) => { e.target.disabled = true; msg.geo = 'Finding you…'; renderDialog();
        try { const p = await locate(); await chooseHome({ ...p, country: p.country, admin1: p.region }); msg.geo = ''; } catch (err) { msg.geo = err.message; renderDialog(); } } }, 'Use my device location'),
        S.home ? h('button', { type: 'button', class: 'btn', onclick: () => { picking = false; renderDialog(); } }, 'Cancel') : null), msg.geo ? note(msg.geo, 'warn') : null);
  }
  async function chooseHome(r) {
    S.home = { lat: +(+r.lat).toFixed(3), lon: +(+r.lon).toFixed(3), name: r.name, region: r.admin1 || r.region || '', country: r.country || '' };
    S.dismissed = {}; picking = false; results = []; msg = {}; save(); publishPlaces();
    const { token } = P();
    if (token) { try { await post('/api/subscribe/update', { token, home: S.home }); msg.saved = 'Home updated for e-mail alerts too.'; } catch (e) { if (e.status === 404) setPrefs({ token: '' }); } }
    renderDialog(); check(true);
  }
  function deviceSection() {
    const supported = 'Notification' in window, perm = supported ? Notification.permission : 'unsupported', on = canNotify();
    const state = !supported ? 'Not supported here. On iPhone, tap Share, then Add to Home Screen, and open Cirrus from there.' : perm === 'denied' ? 'Blocked in this browser’s site settings.' : on ? 'On: alerts appear as notifications on this device.' : 'Off.';
    return sec('Step 2: alerts on this device',
      note(`Notifications: ${state}`, perm === 'denied' ? 'warn' : ''),
      h('label', { class: 'cd-check' }, h('input', { type: 'checkbox', checked: P().sound, onchange: (e) => { setPrefs({ sound: e.target.checked }); if (e.target.checked) { unlock(); startSiren(2); } } }), ' Sound an alarm in the page when a new alert arrives'),
      h('div', { class: 'cd-row' },
        on ? h('button', { type: 'button', class: 'btn', onclick: () => { setPrefs({ notify: false }); renderDialog(); } }, 'Turn notifications off')
          : h('button', { type: 'button', class: 'btn primary', disabled: !supported || perm === 'denied', onclick: async () => { try { await enableNotifications(); msg.dev = ''; } catch (e) { msg.dev = e.message; } renderDialog(); } }, 'Turn on notifications'),
        h('button', { type: 'button', class: 'btn', onclick: () => { unlock(); startSiren(3); showNotification({ id: 'test-' + Date.now(), level: 3, label: 'Test', title: 'This is how an alert looks and sounds', when: 'Now', detail: 'If you can hear this and see the notification, alerts will reach you.' }, 'Cirrus'); } }, 'Test alarm and notification')),
      msg.dev ? note(msg.dev, 'warn') : null,
      note('Notifications and the alarm work while Cirrus is open in a tab, and in the background when it is installed as an app on a phone that allows it. To be told while the site is closed, add an e-mail address below.'),
      installBtn());
  }
  let installEvt = null;
  addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); installEvt = e; if (dialog?.open) renderDialog(); });
  const installBtn = () => installEvt ? h('div', { class: 'cd-row' }, h('button', { type: 'button', class: 'btn', onclick: async () => { installEvt.prompt(); await installEvt.userChoice.catch(() => {}); installEvt = null; renderDialog(); } }, 'Install Cirrus as an app')) : null;

  function emailSection() {
    const p = P();
    if (!cfg.cloud) return sec('Step 3: alerts by e-mail', note('E-mail alerts are not switched on for this site yet. The site owner can enable them (see the README, “Alerts by e-mail”).'));
    if (p.token) return sec('Step 3: alerts by e-mail', h('p', null, '✓ Subscribed. ', h('strong', null, p.email || 'Your e-mail'), ' gets an e-mail when something at your home (or where this device last was) reaches your alert level.'),
      note('Changing your home above also changes it here. This device shares its position with the e-mail service only while Cirrus is open and “Watch where I am” is on.'), msg.saved ? note(msg.saved) : null,
      h('div', { class: 'cd-row' }, h('button', { type: 'button', class: 'btn', onclick: async () => { try { await post('/api/unsubscribe', { token: p.token }); } catch { /* already gone */ } setPrefs({ token: '', pid: '', email: '' }); renderDialog(); } }, 'Stop e-mail alerts')));
    if (p.pid) return sec('Step 3: alerts by e-mail', note(`We sent a confirmation link to ${p.email}. Open it (check spam too) and tap the button. This page notices automatically.`),
      h('div', { class: 'cd-row' }, h('button', { type: 'button', class: 'btn', onclick: pollConfirm }, 'I have confirmed'), h('button', { type: 'button', class: 'btn', onclick: () => { setPrefs({ pid: '' }); renderDialog(); } }, 'Use another e-mail')), msg.mail ? note(msg.mail, 'warn') : null);
    const input = h('input', { type: 'email', class: 'cd-input', placeholder: 'you@gmail.com', 'aria-label': 'Your e-mail address', autocomplete: 'email', value: msg.email || '' });
    return sec('Step 3: alerts by e-mail (optional)', note('Get an e-mail when something threatens your home, even if the site is closed and you are somewhere else. Any address works, Gmail included. You confirm it first and can stop any time. We store only the address, your home and, if allowed, where this device last was.'), input,
      h('div', { class: 'cd-row' }, h('button', { type: 'button', class: 'btn primary', disabled: !S.home, onclick: async (e) => {
        msg.email = input.value; e.target.disabled = true;
        try { const r = await post('/api/subscribe', { email: input.value.trim(), home: S.home, minLevel: P().minLevel }); setPrefs({ pid: r.pid, email: input.value.trim() }); msg.mail = ''; renderDialog(); pollConfirm(); }
        catch (err) { msg.mail = err.message; renderDialog(); } } }, 'Send confirmation e-mail')), !S.home ? note('Choose your home first.', 'warn') : null, msg.mail ? note(msg.mail, 'warn') : null);
  }
  async function pollConfirm() {
    clearInterval(pollTimer);
    const run = async () => {
      const { pid } = P(); if (!pid) return clearInterval(pollTimer);
      try { const r = await api(`/api/subscribe/status?pid=${encodeURIComponent(pid)}`); if (r.confirmed) { clearInterval(pollTimer); setPrefs({ token: r.token, pid: '' }); lastSent = 0; renderDialog(); syncServerPosition(); } } catch { /* try again */ }
    };
    await run(); if (P().pid) pollTimer = setInterval(run, 5000);
  }
  function prefsSection() {
    const p = P();
    return sec('Alert settings',
      h('label', { class: 'cd-field' }, 'Alert me from this level up', h('select', { onchange: (e) => { setPrefs({ minLevel: +e.target.value }); check(true); renderDialog(); } },
        [[1, 'Advisory: everything'], [2, 'Watch: serious weather'], [3, 'Warning: dangerous (recommended)'], [4, 'Extreme: life-threatening only']].map(([v, t]) => h('option', { value: v, selected: p.minLevel === v }, t)))),
      h('label', { class: 'cd-check' }, h('input', { type: 'checkbox', checked: p.away, onchange: async (e) => { setPrefs({ away: e.target.checked }); if (e.target.checked && geoState !== 'granted') { try { await locate(); } catch (err) { msg.geo = err.message; } } check(true); renderDialog(); } }),
        ' Also watch where I am now (needs location access; works while Cirrus is open)'),
      here && awayFromHome() ? note(`You seem to be away from home, near ${here.name}.`) : null, msg.geo && tab === 'settings' && S.home && !picking ? note(msg.geo, 'warn') : null);
  }
  function dataSection() {
    return sec('Your data', note('Your home and settings live in this browser. Clearing them also stops e-mail alerts.'),
      h('div', { class: 'cd-row' }, h('button', { type: 'button', class: 'btn danger', onclick: async () => {
        const { token } = P(); if (token) { try { await post('/api/unsubscribe', { token }); } catch { /* ignore */ } }
        S = { ...DEFAULT }; save(); here = null; active = []; publishPlaces(); picking = true; renderDialog(); renderBanner(); renderBell(); } }, 'Forget my home and settings')));
  }

  /* ------------------------------------------------------------ start up */
  window.cirrusAlerts = { locate, open: openDialog };
  $('#alert-bell')?.addEventListener('click', () => openDialog(S.home ? 'alerts' : 'settings'));
  $('#set-home')?.addEventListener('click', () => openDialog('settings'));
  document.addEventListener('click', async (e) => {   // the confirm / unsubscribe pages opened from e-mail
    const btn = e.target.closest('[data-action]'); if (!btn) return;
    const out = $('#notice-result'); btn.disabled = true;
    try {
      if (btn.dataset.action === 'confirm') { await post('/api/confirm', { t: btn.dataset.token }); out.textContent = 'Confirmed. You will get alerts by e-mail. You can return to Cirrus now.'; }
      else { await post('/api/unsubscribe', { token: btn.dataset.token }); if (P().token === btn.dataset.token) setPrefs({ token: '', pid: '', email: '' }); out.textContent = 'Done. You will not get more alert e-mails.'; }
    } catch (err) { out.textContent = err.message; btn.disabled = false; }
  });
  (async () => {
    try { cfg = await api('/api/config'); } catch { /* e-mail section stays off */ }
    try { if (navigator.permissions) { const st = await navigator.permissions.query({ name: 'geolocation' }); geoState = st.state; st.onchange = () => { geoState = st.state; }; } } catch { /* not supported */ }
    publishPlaces(); check(true);
    if (!S.home && !$('[data-action]') && Date.now() - S.askedAt > 7 * 864e5) { S.askedAt = Date.now(); save(); setTimeout(() => openDialog('settings'), 1200); }   // first visit: ask for a home, then not again for a week
  })();
})();
