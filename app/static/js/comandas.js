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

  // ---- sonido: trappi-pedido-cocina.mp3; si no carga, una alarma de dos tonos generada ----
  let bell = null, bellLoading = null; // el sonido ya decodificado
  function loadBell() {
    if (!audio) return Promise.resolve(null);
    if (bell || bellLoading) return bellLoading || Promise.resolve(bell);
    bellLoading = fetch('/static/sounds/trappi-pedido-cocina.mp3').then(r => r.ok ? r.arrayBuffer() : Promise.reject())
      .then(b => new Promise((ok, err) => audio.decodeAudioData(b, ok, err))).then(buf => { bell = buf; return buf; })
      .catch(() => null).finally(() => { bellLoading = null; });
    return bellLoading;
  }
  function beep() {
    [[880, 0], [1175, .2], [880, .4], [1175, .6]].forEach(([f, t]) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.type = 'square'; o.frequency.value = f; g.gain.value = .35;
      o.connect(g); g.connect(audio.destination);
      o.start(audio.currentTime + t); o.stop(audio.currentTime + t + .17);
    });
  }
  function playBell() {
    const src = audio.createBufferSource();
    src.buffer = bell; src.connect(audio.destination); src.start();
  }
  function ring() {
    if (!audio) return;
    if (audio.state === 'suspended') audio.resume();
    if (bell) playBell();
    else loadBell().then(buf => (buf ? playBell() : beep())); // si no carga el mp3, la alarma generada
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
    }).then(html => { if (html !== null && html !== undefined) { $('board').innerHTML = html; readBoard(); markChats(); } }).catch(() => {});
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
    const c = e.target.closest('[data-chat]'); if (c) openChat(c.dataset.chat, c.dataset.courier);
    if (e.target.closest('[data-chat-close]')) closeChat();
  });

  // ---- chat con el cadete (con fotos) ----
  const csrf = () => (document.querySelector('meta[name=csrf-token]') || {}).content || '';
  const seenChat = (id) => store.get('chat_' + id, 0);
  let chat = { id: null, last: 0, timer: null };
  const warned = {};
  function markChats() {  // punto rojo en las tarjetas con mensajes nuevos del cadete (y un aviso la primera vez)
    document.querySelectorAll('[data-chat]').forEach(b => {
      const id = b.dataset.chat, last = Number(b.dataset.last || 0), dot = b.querySelector('.k-dot');
      const unread = last > seenChat(id) && chat.id !== id;
      if (dot) dot.hidden = !unread;
      if (unread && warned[id] !== last) { warned[id] = last; toast('💬 Mensaje nuevo del cadete · pedido #' + id); if (opts.sound && audio) beep(); }
    });
  }
  function addMsg(m) {
    const box = $('chat-msgs'), d = document.createElement('div');
    d.className = 'm ' + (m.sender === 'store' ? 'me' : m.sender === 'system' ? 'sys' : '');
    if (m.photo) { const a = document.createElement('a'); a.href = m.photo; a.target = '_blank'; const i = document.createElement('img'); i.src = m.photo; i.alt = 'Foto'; a.appendChild(i); d.appendChild(a); }
    if (m.text) { const t = document.createElement('span'); t.textContent = m.text; d.appendChild(t); }
    const s = document.createElement('small'); s.textContent = new Date(m.at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' }); d.appendChild(s);
    box.appendChild(d); box.scrollTop = box.scrollHeight;
    chat.last = Math.max(chat.last, m.id);
    store.set('chat_' + chat.id, chat.last);
  }
  function loadChat() {
    if (!chat.id) return;
    fetch('/admin/orders/' + chat.id + '/chat?thread=local&after=' + chat.last, { credentials: 'same-origin' }).then(r => r.json()).then(d => {
      if (!d.ok) return;
      d.messages.forEach(addMsg);
      $('chat-form').hidden = !d.can_write; $('chat-closed').hidden = d.can_write;
      markChats();
    }).catch(() => {});
  }
  function openChat(id, courier) {
    chat = { id, last: 0, timer: null };
    $('chat-msgs').textContent = '';
    $('chat-title').textContent = 'Chat con ' + (courier || 'el cadete') + ' · pedido #' + id;
    $('chat-dlg').showModal();
    loadChat(); chat.timer = setInterval(loadChat, 5000);
  }
  function closeChat() { clearInterval(chat.timer); chat = { id: null, last: 0, timer: null }; $('chat-dlg').close(); markChats(); }
  $('chat-dlg').addEventListener('close', () => { if (chat.id) closeChat(); });
  function sendChat(fd) {
    fd.append('csrf_token', csrf());
    return fetch('/admin/orders/' + chat.id + '/chat', { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf() } })
      .then(r => r.json()).then(d => { if (d.ok) addMsg(d.message); else toast(d.error || 'No se pudo mandar.'); })
      .catch(() => toast('Sin conexión. Probá de nuevo.'));
  }
  $('chat-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const input = $('chat-text'), text = input.value.trim(); if (!text) return;
    const fd = new FormData(); fd.append('text', text); input.value = '';
    sendChat(fd);
  });
  $('chat-photo').addEventListener('change', function () {
    const f = this.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('photo', f); sendChat(fd); this.value = '';
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
  $('test-sound').addEventListener('click', () => { if (!audio) { audio = new (window.AudioContext || window.webkitAudioContext)(); loadBell(); } ring(); });
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
    const fd = new FormData(form);
    if (e.submitter && e.submitter.name) fd.set(e.submitter.name, e.submitter.value); // el boton tocado (Normal, +15, +30, Pausar)
    fetch(form.action, { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(() => fetch('/admin/comandas', { credentials: 'same-origin', cache: 'no-store' })).then(r => r.text())
      .then(html => { const box = new DOMParser().parseFromString(html, 'text/html').getElementById('store-box'); if (box) $('store-box').innerHTML = box.innerHTML; })
      .catch(() => toast('Sin conexión. Probá de nuevo.'));
  });

  // ---- avisos al celular del dueño (Web Push): llegan aunque esta pantalla este cerrada ----
  const pushBox = $('push-box');
  if (pushBox) {
    const b64 = (s) => { const p = '='.repeat((4 - s.length % 4) % 4); const raw = atob((s + p).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(raw, c => c.charCodeAt(0)); };
    const post = (url, data) => fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() }, body: JSON.stringify(data) }).then(r => r.json());
    const label = () => { const ua = navigator.userAgent; const dev = /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iPhone' : /Windows/.test(ua) ? 'PC Windows' : /Mac/.test(ua) ? 'Mac' : 'Dispositivo'; const br = /Edg\//.test(ua) ? 'Edge' : /Firefox/.test(ua) ? 'Firefox' : /Chrome/.test(ua) ? 'Chrome' : /Safari/.test(ua) ? 'Safari' : ''; return (dev + ' ' + br).trim(); };
    let pushKey = null, pushSub = null;
    const state = (text) => { $('push-state').textContent = text; };
    const render = (info) => {
      const on = !!(pushSub && info.subscribed);
      $('push-btn').hidden = false;
      $('push-btn').textContent = on ? 'Desactivar en este dispositivo' : '🔔 Avisarme en este dispositivo';
      $('push-btn').className = 'c-btn small ' + (on ? 'ghost' : 'accept');
      $('push-opts').hidden = !info.devices;
      pushBox.querySelectorAll('[data-alert]').forEach(el => { el.checked = !!info.alerts[el.dataset.alert]; });
      state(on ? 'Activado en este dispositivo' + (info.devices > 1 ? ' y en ' + (info.devices - 1) + ' más' : '') + '. Elegí qué avisos querés.' + (info.whatsapp ? ' También llegan por WhatsApp al número del local.' : '')
        : info.devices ? 'Ya está activado en ' + info.devices + ' dispositivo' + (info.devices > 1 ? 's' : '') + '. Podés sumar este también.' : $('push-state').textContent);
    };
    const refresh = () => fetch('/admin/comandas/push/key?endpoint=' + encodeURIComponent(pushSub ? pushSub.endpoint : ''), { credentials: 'same-origin', cache: 'no-store' })
      .then(r => r.json()).then(info => { if (info.ok) { pushKey = info.key; render(info); } }).catch(() => {});
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      state('Este navegador no permite notificaciones. En Android usá Chrome; en iPhone agregá Comandas a la pantalla de inicio.');
    } else {
      navigator.serviceWorker.ready.then(reg => reg.pushManager.getSubscription()).then(s => { pushSub = s; refresh(); });
      $('push-btn').addEventListener('click', () => {
        const btn = $('push-btn'); btn.disabled = true;
        navigator.serviceWorker.ready.then(reg => {
          if (pushSub) return pushSub.unsubscribe().then(() => post('/admin/comandas/push/unsubscribe', { endpoint: pushSub.endpoint })).then(() => { pushSub = null; toast('Avisos desactivados en este dispositivo.'); });
          return Notification.requestPermission().then(p => {
            if (p !== 'granted') throw new Error('El navegador bloqueó los avisos. Habilitalos desde el candado de la barra de direcciones.');
            return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(pushKey) });
          }).then(s => post('/admin/comandas/push/subscribe', Object.assign(s.toJSON(), { label: label() })).then(r => {
            if (!r.ok) { s.unsubscribe(); throw new Error(r.error || 'No se pudo activar.'); }
            pushSub = s; toast('¡Listo! Te llegó una notificación de prueba.');
          }));
        }).catch(err => toast(err.message || 'No se pudo activar. Probá de nuevo.')).finally(() => { btn.disabled = false; refresh(); });
      });
      pushBox.addEventListener('change', (e) => {
        const el = e.target.closest('[data-alert]'); if (!el) return;
        post('/admin/comandas/push/alerts', { [el.dataset.alert]: el.checked }).then(r => { if (r.ok) toast('Guardado.'); }).catch(() => toast('Sin conexión. Probá de nuevo.'));
      });
    }
  }

  // ---- agotados: un toque marca el producto sin stock (y otro lo vuelve a habilitar) ----
  const stockDlg = $('stock-dlg');
  const loadStock = (req) => req.then(r => { if (!r.ok) throw r; return r.text(); })
    .then(html => { $('stock-list').innerHTML = html; }).catch(() => toast('No se pudo cargar el menú. Probá de nuevo.'));
  document.addEventListener('click', (e) => {
    if (e.target.closest('#stock-btn')) { $('stock-list').innerHTML = '<p class="c-stock-help">Cargando…</p>'; stockDlg.showModal(); loadStock(fetch('/admin/comandas/stock', { credentials: 'same-origin', cache: 'no-store' })); return; }
    if (e.target.closest('[data-stock-close]')) { stockDlg.close(); return; }
    const btn = e.target.closest('[data-stock]'); if (!btn) return;
    btn.disabled = true;
    loadStock(fetch('/admin/comandas/stock/' + btn.dataset.stock, { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf() } }));
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
  $('start-btn').addEventListener('click', () => { if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)(); audio.resume(); loadBell(); start(); });
  readBoard();
  // Si el navegador ya permite sonido sin clic (comun en la app instalada), arranca solo
  try {
    audio = new (window.AudioContext || window.webkitAudioContext)();
    loadBell();
    if (audio.state === 'running') start();
  } catch (e) { audio = null; }
})();
