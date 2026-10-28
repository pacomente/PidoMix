// Trappi en la web: instalarla en el celular y avisos del pedido (notificaciones web, gratis).
(function () {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {});
  var standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  var KEY = 'trappi-install-hidden';
  var hidden = function () { try { return Number(localStorage.getItem(KEY) || 0) > Date.now(); } catch (e) { return false; } };
  var hide = function (days) { try { localStorage.setItem(KEY, String(Date.now() + days * 864e5)); } catch (e) {} };

  function banner(text, button, onClick) {
    if (standalone || hidden() || document.getElementById('install-bar')) return;
    var bar = document.createElement('div');
    bar.id = 'install-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Instalar Trappi');
    bar.style.cssText = 'position:fixed;left:12px;right:12px;bottom:calc(76px + env(safe-area-inset-bottom));z-index:60;background:#1E1433;color:#fff;' +
      'border-radius:16px;padding:12px 14px;display:flex;gap:10px;align-items:center;box-shadow:0 10px 30px rgba(30,20,51,.35);max-width:520px;margin:0 auto;font-size:14px';
    bar.innerHTML = '<img src="/static/icons/trappi-192.png" alt="" width="36" height="36" style="border-radius:9px">' +
      '<span style="flex:1;line-height:1.3">' + text + '</span>' +
      (button ? '<button type="button" data-go style="background:#6C2BD9;color:#fff;border:0;border-radius:10px;padding:9px 12px;font-weight:700">' + button + '</button>' : '') +
      '<button type="button" data-x aria-label="Cerrar" style="background:none;border:0;color:#fff;font-size:20px;padding:4px 6px">×</button>';
    document.body.appendChild(bar);
    bar.querySelector('[data-x]').onclick = function () { hide(14); bar.remove(); };
    var go = bar.querySelector('[data-go]');
    if (go) go.onclick = function () { onClick(); bar.remove(); };
  }

  // Android y compu (Chrome, Edge): el navegador avisa que se puede instalar
  var prompt = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    prompt = e;
    setTimeout(function () {
      banner('<b>Instalá Trappi</b><br>Abrí más rápido y recibí los avisos de tus pedidos.', 'Instalar', function () {
        prompt.prompt();
        prompt.userChoice.then(function (r) { if (r.outcome !== 'accepted') hide(30); });
      });
    }, 4000);
  });
  window.addEventListener('appinstalled', function () { hide(3650); });
  // iPhone (Safari): no hay botón de instalar, se explica cómo
  var ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !/crios|fxios/i.test(navigator.userAgent);
  if (ios && !standalone) {
    setTimeout(function () { banner('<b>Agregá Trappi a tu pantalla de inicio</b><br>Tocá <b>Compartir</b> ⬆️ y después <b>Agregar a inicio</b>.', null, null); }, 6000);
  }

  // "Avisarme" en el seguimiento del pedido
  var btn = document.getElementById('push-order');
  if (!btn) return;
  if (!('PushManager' in window) || !('Notification' in window)) {
    btn.closest('[data-push-box]').hidden = !ios;  // en iPhone funciona solo con Trappi agregado a inicio
    if (ios) { btn.disabled = true; btn.textContent = 'Agregá Trappi a inicio para recibir avisos'; }
    return;
  }
  var b64 = function (s) { s = s.replace(/-/g, '+').replace(/_/g, '/'); var raw = atob(s + '='.repeat((4 - s.length % 4) % 4)); return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); }); };
  var msg = document.getElementById('push-order-msg');
  btn.onclick = function () {
    btn.disabled = true;
    Notification.requestPermission().then(function (perm) {
      if (perm !== 'granted') throw new Error('Para recibir avisos, permití las notificaciones de Trappi en el navegador.');
      return Promise.all([navigator.serviceWorker.ready, fetch('/push/clave').then(function (r) { return r.json(); })]);
    }).then(function (res) {
      return res[0].pushManager.getSubscription().then(function (s) {
        return s || res[0].pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(res[1].key) });
      });
    }).then(function (sub) {
      return fetch('/pedido/' + btn.dataset.order + '/avisos', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ t: btn.dataset.t, subscription: sub.toJSON() }) }).then(function (r) { return r.json(); });
    }).then(function (j) {
      if (!j.ok) throw new Error(j.error || 'No se pudo activar.');
      btn.textContent = '✓ Te avisamos en este celular';
    }).catch(function (err) { btn.disabled = false; if (msg) msg.textContent = err.message; });
  };
})();
