// Recorrido guiado del panel del local: la primera vez que entra (o con ?recorrido=1) muestra dónde está cada cosa.
// Solo resalta elementos del menú lateral; no cambia nada. "Ya lo vi" se recuerda en este navegador.
(function () {
  var KEY = 'trappi_tour_v1';
  var forced = new URLSearchParams(location.search).has('recorrido');
  var seen = false;
  try { seen = localStorage.getItem(KEY) === '1'; } catch (e) {}
  if (seen && !forced) return;

  var STEPS = [
    { sel: null, title: '¡Hola! Te mostramos el panel 👋', text: 'En 1 minuto vas a saber dónde está cada cosa. Podés salir cuando quieras y volver a verlo desde «Cómo funciona».' },
    { sel: 'a[href="/admin/stores"]', title: 'Tu local', text: 'Logo, dirección en el mapa, horarios y días cerrados. Es lo primero para dejar listo.' },
    { sel: 'a[href="/admin/products"]', title: 'Tu menú', text: 'Cargá productos de a uno, armá las secciones o subí todo junto desde una planilla de Excel.' },
    { sel: 'a[href="/admin/comandas"]', title: 'Modo comandas', text: 'Dejalo abierto en la PC o tablet del local: ahí suenan los pedidos nuevos y los aceptás con un toque.' },
    { sel: 'a[href="/admin/orders"]', title: 'Pedidos', text: 'El historial completo: cada pedido con su estado, el cliente y cómo pagó.' },
    { sel: 'a[href="/admin/pagos"]', title: 'Pagos y liquidaciones', text: 'Conectá Mercado Pago y mirá cuánto vendiste, cuánto es de Trappi y cuánto te toca.' },
    { sel: 'a[href="/admin/customers"]', title: 'Clientes', text: 'Cupones, reseñas para responder y reclamos. Lo que hace que vuelvan.' },
    { sel: 'a[href="/admin/reports"]', title: 'Reportes', text: 'Ventas, lo más vendido y tus horas pico. Los lunes te llega el resumen por mail.' },
    { sel: '.help-btn', title: '¿Dudas? Tocá Ayuda', text: 'En cada pantalla, «Ayuda» te explica cómo funciona esa parte. ¡Listo, a vender! 🚀' },
  ];

  var narrow = function () { return window.matchMedia('(max-width: 900px)').matches; };
  var box = document.createElement('div'), ring = document.createElement('div'), shade = document.createElement('div');
  shade.className = 'tour-shade'; ring.className = 'tour-ring'; box.className = 'tour-box';
  box.setAttribute('role', 'dialog'); box.setAttribute('aria-live', 'polite');
  var i = 0;

  function done() {
    try { localStorage.setItem(KEY, '1'); } catch (e) {}
    [shade, ring, box].forEach(function (n) { n.remove(); });
    document.body.classList.remove('sidebar-open');
    document.removeEventListener('keydown', onKey);
    if (forced) history.replaceState(null, '', location.pathname);
  }
  function target(step) {
    if (!step.sel) return null;
    return document.querySelector(step.sel);
  }
  function show() {
    var step = STEPS[i], el = target(step);
    var inSidebar = el && el.closest('.admin-sidebar');
    document.body.classList.toggle('sidebar-open', !!(inSidebar && narrow()));
    box.innerHTML = '';
    var h = document.createElement('b'); h.textContent = step.title;
    var p = document.createElement('p'); p.textContent = step.text;
    var foot = document.createElement('div'); foot.className = 'tour-foot';
    var count = document.createElement('span'); count.className = 'muted-small'; count.textContent = (i + 1) + ' de ' + STEPS.length;
    var skip = document.createElement('button'); skip.type = 'button'; skip.className = 'btn small secondary'; skip.textContent = i === STEPS.length - 1 ? 'Cerrar' : 'Saltear';
    var next = document.createElement('button'); next.type = 'button'; next.className = 'btn small'; next.textContent = i === STEPS.length - 1 ? '¡Listo!' : 'Siguiente';
    skip.onclick = done;
    next.onclick = function () { if (i < STEPS.length - 1) { i++; show(); } else done(); };
    foot.append(count, skip, next); box.append(h, p, foot);
    // en el celular el menú lateral entra deslizándose: se mide cuando terminó de abrir
    setTimeout(function () { place(el); next.focus({ preventScroll: true }); }, inSidebar && narrow() ? 320 : 0);
  }
  function place(el) {
    if (!el) {
      ring.style.display = 'none'; shade.classList.add('on');
      box.style.left = '50%'; box.style.top = '30%'; box.style.transform = 'translateX(-50%)';
      return;
    }
    el.scrollIntoView({ block: 'nearest' });
    var r = el.getBoundingClientRect();
    shade.classList.remove('on');
    ring.style.display = 'block';
    ring.style.left = (r.left - 6) + 'px'; ring.style.top = (r.top - 6) + 'px';
    ring.style.width = (r.width + 12) + 'px'; ring.style.height = (r.height + 12) + 'px';
    box.style.transform = 'none';
    var w = Math.min(320, window.innerWidth - 32), h = box.offsetHeight, left = r.right + 16, top = r.top - 8;
    if (left + w > window.innerWidth - 16) {  // no entra al costado: va abajo del elemento, o arriba si no hay lugar
      left = Math.max(16, Math.min(r.left, window.innerWidth - w - 16));
      top = r.bottom + 14 + h <= window.innerHeight - 16 ? r.bottom + 14 : r.top - h - 14;
    }
    box.style.left = left + 'px'; box.style.top = Math.max(16, Math.min(top, window.innerHeight - h - 16)) + 'px';
  }
  function onKey(e) { if (e.key === 'Escape') done(); }
  window.addEventListener('resize', function () { if (box.isConnected) place(target(STEPS[i])); });
  document.addEventListener('keydown', onKey);
  document.body.append(shade, ring, box);
  show();
})();
