/* Service worker: hace que la app funcione sin conexión.
   - Archivos de la app (index.html, data.js…): primero la red, para recibir los cambios
     al momento; si no hay conexión o tarda más de 3 s, la copia guardada.
   - Audios: primero la copia guardada. Llevan ?v=<huella> en la URL, así que un audio
     regenerado tiene otra URL y se descarga de nuevo. Al arrancar la app (mensaje 'sync')
     se descargan los que falten y se borran los que ya no están en audio/manifest.json.
   - Fuentes e iconos: primero la copia guardada.
   Sube VERSION si cambias este archivo o la lista APP. */
const VERSION = 'v1';
const APP_CACHE = 'app-' + VERSION;
const MEDIA_CACHE = 'media';
const APP = ['./', 'index.html', 'data.js', 'manifest.webmanifest', 'audio/manifest.json',
  'fonts/andika-700.woff2', 'fonts/nunito.woff2',
  'icons/apple-touch-icon.png', 'icons/icon-192.png', 'icons/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(APP_CACHE).then(c => c.addAll(APP)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== APP_CACHE && k !== MEDIA_CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('message', e => {
  if (e.data === 'sync') e.waitUntil(syncAudios());
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.endsWith('.mp3')) e.respondWith(media(req));
  else if (/\/(fonts|icons)\//.test(url.pathname)) e.respondWith(cacheFirst(req));
  else e.respondWith(networkFirst(req));
});

/* ---------- estrategias ---------- */

function networkFirst(req) {
  return new Promise(resolve => {
    let done = false;
    const finish = r => { if (!done && r) { done = true; clearTimeout(t); resolve(r); return true; } return false; };
    const fromCache = () => caches.match(req).then(r => r || (req.mode === 'navigate' ? caches.match('./') : undefined));
    /* red lenta: si a los 3 s no ha llegado nada, se usa la copia guardada */
    const t = setTimeout(() => fromCache().then(finish), 3000);
    fetch(req).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(APP_CACHE).then(c => c.put(req, copy)); }
      finish(res);
    }).catch(() => fromCache().then(r => { if (!finish(r)) finish(Response.error()); }));
  });
}

async function cacheFirst(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) { const copy = res.clone(); caches.open(APP_CACHE).then(c => c.put(req, copy)); }
  return res;
}

/* Safari pide los audios por trozos (cabecera Range) y no los reproduce si el
   service worker responde con el archivo entero: hay que devolver un 206. */
async function media(req) {
  const cache = await caches.open(MEDIA_CACHE);
  let res = await cache.match(req.url);
  if (!res) {
    res = await fetch(req.url);
    if (!res.ok) return res;
    await cache.put(req.url, res.clone());
  }
  const range = req.headers.get('range');
  if (!range) return res;
  const buf = await res.arrayBuffer();
  const size = buf.byteLength;
  const m = /bytes=(\d*)-(\d*)/.exec(range);
  let start = 0, end = size - 1;
  if (m && m[1] === '' && m[2] !== '') start = Math.max(0, size - Number(m[2]));
  else if (m) { start = Number(m[1] || 0); if (m[2] !== '') end = Math.min(size - 1, Number(m[2])); }
  return new Response(buf.slice(start, end + 1), {
    status: 206,
    headers: {
      'Content-Type': 'audio/mpeg',
      'Content-Range': `bytes ${start}-${end}/${size}`,
      'Content-Length': String(end - start + 1),
      'Accept-Ranges': 'bytes',
    },
  });
}

/* ---------- descarga de todos los audios ---------- */

let syncing = null;
function syncAudios() {
  if (!syncing) syncing = doSync().finally(() => { syncing = null; });
  return syncing;
}

async function doSync() {
  let man;
  try {
    const r = await fetch('audio/manifest.json', { cache: 'no-cache' });
    if (!r.ok) return;
    await (await caches.open(APP_CACHE)).put('audio/manifest.json', r.clone());
    man = await r.json();
  } catch (e) { return; } /* sin conexión: se queda con lo que ya tiene */
  const h = man.huellas || {};
  const want = new Set(man.files.map(k => new URL('audio/' + k + '.mp3' + (h[k] ? '?v=' + h[k] : ''), self.registration.scope).href));
  const cache = await caches.open(MEDIA_CACHE);
  const have = new Set((await cache.keys()).map(r => r.url));
  await Promise.all([...have].filter(u => !want.has(u)).map(u => cache.delete(u)));
  const missing = [...want].filter(u => !have.has(u));
  let done = want.size - missing.length;
  const total = want.size;
  const report = () => self.clients.matchAll().then(cs => cs.forEach(c => c.postMessage({ type: 'audio', done, total })));
  /* 6 descargas a la vez */
  const queue = missing.slice();
  const worker = async () => {
    while (queue.length) {
      const u = queue.shift();
      try { const r = await fetch(u); if (r.ok) { await cache.put(u, r); done++; } } catch (e) { /* se reintenta en el próximo arranque */ }
      if (done % 25 === 0) report();
    }
  };
  await Promise.all(Array.from({ length: 6 }, worker));
  report();
}
