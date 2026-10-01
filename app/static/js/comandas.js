/* Trappi Comandas: pantalla de pedidos para la PC del local */
(function () {
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k, d) { try { const v = localStorage.getItem('comandas_' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('comandas_' + k, JSON.stringify(v)); } catch (e) {} },
  };
  const opts = { sound: store.get('sound', true), print: store.get('print', false), notify: store.get('notify', false) };
  let seen = new Set(store.get('seen', [])); // pedidos ya avisados (no se repite la notificacion al recargar)
  let pending = [], stamp = null, mutedUntil = 0, audio = null, ticks = 0, online = true;

  function toast(msg) { const t = $('toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 3500); }

  // ---- sonido: alarma de dos tonos, generada (no depende de archivos) ----
  function ring() {
    if (!audio) return;
    if (audio.state === 'suspended') audio.resume();
    [[880, 0], [1175, .2], [880, .4], [1175, .6]].forEach(([f, t]) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.type = 'square'; o.frequency.value = f; g.gain.value = .35;
      o.connect(g); g.connect(audio.destination);
      o.start(audio.currentTime + t); o.stop(audio.currentTime + t + .17);
    });
    if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
  }

  // ---- notificaciones del sistema (Windows / Mac / Android) ----
  let swReg = null;
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/admin/comandas/sw.js', { scope: '/admin/comandas' }).then(r => { swReg = r; }).catch(() => {});
  function notify(ids, summary) {
    if (!opts.notify || !('Notification' in window) || Notification.permission !== 'granted') return;
    const title = ids.length === 1 ? 'Nuevo pedido #' + ids[0] : ids.length + ' pedidos nuevos';
    const options = { body: summary, tag: 'trappi-' + ids.join('-'), requireInteraction: true, icon: '/static/icons/comandas-192.png', renotify: true };
    try { swReg ? swReg.showNotification(title, options) : new Notification(title, options); } catch (e) {}
  }

  // ---- tablero ----
  function readBoard() {
    const data = $('board-data');
    pending = data && data.dataset.pending ? data.dataset.pending.split(',').map(Number) : [];
    const fresh = pending.filter(id => !seen.has(id));
    if (fresh.length) {
      fresh.forEach(id => seen.add(id));
      store.set('seen', [...seen].slice(-200));
      notify(fresh, data.dataset.summary);
      if (Date.now() > mutedUntil) ring();
    }
    const alert = $('alert');
    alert.hidden = !pending.length;
    $('alert-text').textContent = pending.length === 1 ? '🔔 1 pedido nuevo' : '🔔 ' + pending.length + ' pedidos nuevos';
    updateTimers();
    document.title = (pending.length ? '(' + pending.length + ') ' : '') + 'Comandas — Trappi';
  }

  // Cronometro de cada tarjeta: verde hasta la mitad del tiempo estimado, ambar hasta el limite, rojo despues
  function updateTimers() {
    const now = Date.now();
    document.querySelectorAll('.k-card[data-created]').forEach(card => {
      const mins = Math.max(0, Math.floor((now - Date.parse(card.dataset.created)) / 60000));
      const limit = Number(card.dataset.limit) || 30;
      const b = card.querySelector('.k-timer b'); if (b) b.textContent = mins;
      card.classList.toggle('t-warn', mins >= limit / 2 && mins < limit);
      card.classList.toggle('t-late', mins >= limit);
    });
    const clock = $('clock'); if (clock) clock.textContent = new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
  }
  setInterval(updateTimers, 15000);

  function refresh() {
    return fetch('/admin/comandas/board', { credentials: 'same-origin', cache: 'no-store' }).then(r => {
      if (r.status === 401) { location.reload(); return null; } // sesion vencida: vuelve al login y luego a esta pantalla
      return r.ok ? r.text() : null;
    }).then(html => { if (html !== null && html !== undefined) { $('board').innerHTML = html; readBoard(); } }).catch(() => {});
  }

  function setOnline(ok) {
    if (ok === online) return;
    online = ok; $('live').classList.toggle('off', !ok); $('live').textContent = ok ? 'En vivo' : 'Sin conexión, reintentando…';
  }

  function poll() {
    ticks++;
    fetch('/admin/orders/pending', { credentials: 'same-origin', cache: 'no-store' }).then(r => {
      if (r.status === 401) { location.reload(); return null; }
      return r.ok ? r.json() : Promise.reject();
    }).then(d => {
      if (!d) return;
      setOnline(true);
      // refresca ante cualquier cambio, y cada ~30 s para que avancen los minutos de espera
      if (d.stamp !== stamp || ticks % 3 === 0) refresh();
      stamp = d.stamp;
    }).catch(() => setOnline(false));
    if (pending.length && opts.sound && Date.now() > mutedUntil) ring(); // suena hasta que lo acepten
  }

  // Un Worker marca el ritmo: los timers de una ventana minimizada se frenan, los de un Worker no.
  function startTicker() {
    try {
      const w = new Worker(URL.createObjectURL(new Blob(['setInterval(() => postMessage(0), 10000)'], { type: 'text/javascript' })));
      w.onmessage = poll;
    } catch (e) { setInterval(poll, 10000); }
  }

  // ---- impresion del ticket ----
  function printTicket(id) {
    const frame = $('print-frame');
    frame.onload = () => { try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch (e) { window.open('/admin/comandas/ticket/' + id + '?print=1'); } };
    frame.src = '/admin/comandas/ticket/' + id + '?t=' + Date.now();
  }

  // ---- acciones de las tarjetas ----
  document.addEventListener('submit', (e) => {
    const form = e.target.closest('form.js-status'); if (!form) return;
    e.preventDefault();
    if (form.dataset.confirm && !confirm(form.dataset.confirm)) return;
    const btn = form.querySelector('button'); btn.disabled = true;
    fetch(form.action, { method: 'POST', body: new FormData(form), credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
      .then(r => r.json().catch(() => ({ ok: false })))
      .then(d => {
        if (!d.ok) toast(d.error || 'No se pudo actualizar el pedido.');
        else if (form.dataset.status === 'CONFIRMADO' && opts.print) printTicket(form.dataset.order);
        return refresh();
      })
      .catch(() => { toast('Sin conexión. Probá de nuevo.'); btn.disabled = false; });
  });
  document.addEventListener('click', (e) => {
    const p = e.target.closest('[data-print]'); if (p) printTicket(p.dataset.print);
  });

  // ---- ajustes ----
  const bind = (id, key, onChange) => { const el = $(id); el.checked = opts[key]; el.addEventListener('change', () => { opts[key] = el.checked; store.set(key, el.checked); onChange && onChange(el); }); };
  bind('opt-sound', 'sound');
  bind('opt-print', 'print', (el) => { if (el.checked) toast('Para imprimir sin ventana, mirá «Cómo instalar e imprimir».'); });
  bind('opt-notify', 'notify', (el) => {
    if (!el.checked || !('Notification' in window)) return;
    Notification.requestPermission().then(p => { if (p !== 'granted') { el.checked = opts.notify = false; store.set('notify', false); toast('El navegador bloqueó los avisos. Habilitalos desde el candado de la barra de direcciones.'); } });
  });
  $('settings-btn').addEventListener('click', () => { const s = $('settings'); s.hidden = !s.hidden; $('settings-btn').setAttribute('aria-expanded', String(!s.hidden)); });
  $('test-sound').addEventListener('click', () => { if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)(); ring(); });
  $('mute').addEventListener('click', () => { mutedUntil = Date.now() + 120000; toast('Alarma silenciada por 2 minutos.'); });
  const help = () => { $('ayuda').hidden = location.hash !== '#ayuda'; if (!$('ayuda').hidden) $('ayuda').scrollIntoView(); };
  addEventListener('hashchange', help); help();

  // ---- instalar como app ----
  let installEvent = null;
  addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); installEvent = e; $('install').hidden = false; });
  $('install').addEventListener('click', () => { if (!installEvent) return; installEvent.prompt(); installEvent.userChoice.finally(() => { installEvent = null; $('install').hidden = true; }); });
  addEventListener('appinstalled', () => { $('install').hidden = true; toast('¡Listo! Trappi Comandas quedó instalada en esta PC.'); });

  // ---- pantalla siempre encendida (tablets) ----
  let lock = null;
  const keepAwake = () => { if ('wakeLock' in navigator && document.visibilityState === 'visible') navigator.wakeLock.request('screen').then(l => { lock = l; }).catch(() => {}); };
  document.addEventListener('visibilitychange', () => { if (!lock || lock.released) keepAwake(); });

  // ---- abrir / cerrar el local sin recargar la pantalla ----
  document.addEventListener('submit', (e) => {
    const form = e.target.closest('form.js-store'); if (!form) return;
    e.preventDefault();
    fetch(form.action, { method: 'POST', body: new FormData(form), credentials: 'same-origin' })
      .then(() => fetch('/admin/comandas', { credentials: 'same-origin', cache: 'no-store' })).then(r => r.text())
      .then(html => { const box = new DOMParser().parseFromString(html, 'text/html').getElementById('store-box'); if (box) $('store-box').innerHTML = box.innerHTML; })
      .catch(() => toast('Sin conexión. Probá de nuevo.'));
  });

  // ---- arranque: los navegadores exigen un clic para permitir sonido ----
  let started = false;
  function start() {
    if (started) return; started = true;
    $('start').hidden = true;
    keepAwake();
    seen = new Set([...seen].filter(id => pending.includes(id))); // olvida los que ya no estan pendientes
    readBoard();
    if (pending.length && opts.sound) ring();
    poll(); startTicker();
  }
  $('start-btn').addEventListener('click', () => { if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)(); audio.resume(); start(); });
  readBoard();
  // Si el navegador ya permite sonido sin clic (comun en la app instalada), arranca solo
  try {
    audio = new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === 'running') start();
  } catch (e) { audio = null; }
})();
