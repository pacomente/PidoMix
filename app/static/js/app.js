/* Trappi — carrito y checkout */
async function api(url, options = {}) {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, credentials: 'same-origin', ...options });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.message || d.error || 'Ocurrió un error'), { data: d, status: r.status });
  return d;
}
const money = (n) => '$' + Number(n || 0).toLocaleString('es-AR', { maximumFractionDigits: 0 });
// Los nombres de productos y extras los cargan los locales: siempre escapar antes de usar innerHTML
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

// Reemplazo de confirm() nativo: mas confiable en mobile, con el estilo de Trappi
function askConfirm(message, okLabel) {
  return new Promise(resolve => {
    const back = document.createElement('div'); back.className = 'modal-back';
    const box = document.createElement('div'); box.className = 'box modal-box confirm-box';
    box.innerHTML = '<p>' + message + '</p><div class="confirm-actions"><button class="btn secondary" id="confirm-no">Cancelar</button><button class="btn" id="confirm-yes">' + (okLabel || 'Confirmar') + '</button></div>';
    back.appendChild(box); document.body.appendChild(back);
    const done = (v) => { back.remove(); resolve(v); };
    box.querySelector('#confirm-yes').addEventListener('click', () => done(true));
    box.querySelector('#confirm-no').addEventListener('click', () => done(false));
    back.addEventListener('click', (e) => { if (e.target === back) done(false); });
  });
}
const svgIcon = (name) => '<svg class="i" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
const post = (url, body) => api(url, { method: 'POST', body: JSON.stringify(body || {}) });

let cartToken = 0;
let optimisticCount = null; // cuando no es null, el badge se mueve al toque sin esperar al servidor

function bumpCountOptimistic(delta) {
  const badgeEl = document.getElementById('cart-count');
  const current = optimisticCount !== null ? optimisticCount : Number(badgeEl ? badgeEl.textContent : 0) || 0;
  optimisticCount = Math.max(0, current + delta);
  if (badgeEl) badgeEl.textContent = optimisticCount;
  const bar = document.getElementById('cart-bar');
  if (bar && optimisticCount > 0) bar.hidden = false;
}
function renderCart(c, token) {
  if (token !== undefined && token !== cartToken) return; // respuesta vieja que llego tarde: se ignora
  optimisticCount = null; // la respuesta real del servidor ya llego: deja de "adivinar" y manda esto
  const n = c.count || 0;
  const badge = document.getElementById('cart-count'); if (badge) badge.textContent = n;
  const bar = document.getElementById('cart-bar');
  if (bar) { bar.hidden = n === 0; document.getElementById('cart-bar-n').textContent = 'Ver mi pedido (' + n + ')'; document.getElementById('cart-bar-total').textContent = money(c.subtotal); }
  const lines = document.getElementById('cart-lines');
  if (lines) {
    if (!n) { lines.innerHTML = '<div class="cart-empty">' + svgIcon('bag') + '<span>Agregá productos para empezar tu pedido.</span></div>'; return; }
    lines.innerHTML = c.items.map(i => `<div class="cl"><span>${esc(i.name)}${i.modifiers_text ? '<small class="cl-mod">' + esc(i.modifiers_text) + '</small>' : ''}</span><span class="step"><button data-key="${esc(i.line_key)}" data-q="${i.quantity - 1}" aria-label="Quitar uno">−</button><b>${i.quantity}</b><button data-key="${esc(i.line_key)}" data-q="${i.quantity + 1}" aria-label="Agregar uno">+</button></span></div>`).join('')
      + `<div class="tot"><span>Subtotal</span><span>${money(c.subtotal)}</span></div><a class="btn block" href="/checkout">Continuar</a>`;
    lines.querySelectorAll('button[data-key]').forEach(b => b.addEventListener('click', async () => {
      const t = ++cartToken;
      try { renderCart(await post('/api/cart/update', { line_key: b.dataset.key, quantity: Number(b.dataset.q) }), t); } catch (e) { alert(e.message); }
    }));
  }
}

// Agrega al carrito con respuesta optimista; si el carrito es de otro local, ofrece vaciarlo.
async function addProduct(pid, modifiers) {
  const body = { product_id: pid, quantity: 1, modifiers: modifiers || [] };
  bumpCountOptimistic(1); // se ve al instante, no espera la respuesta del servidor
  const t = ++cartToken;
  try { renderCart(await post('/api/cart/add', body), t); }
  catch (e) {
    optimisticCount = null;
    const otherStore = e.data && e.data.code === 'DIFFERENT_STORE';
    try {
      if (otherStore && await askConfirm('Tu pedido tiene productos de otro comercio. ¿Querés vaciarlo y empezar uno nuevo?', 'Vaciar y agregar')) {
        await post('/api/cart/clear'); bumpCountOptimistic(1);
        const t2 = ++cartToken; renderCart(await post('/api/cart/add', body), t2);
      } else {
        const t3 = ++cartToken; renderCart(await api('/api/cart'), t3);
        if (!otherStore) alert(e.message);
      }
    } catch (e2) { alert(e2.message); }
  }
}

function addToCart(btn) {
  if (!btn.dataset.html) btn.dataset.html = btn.innerHTML;
  btn.innerHTML = svgIcon('check'); clearTimeout(btn._t); btn._t = setTimeout(() => { btn.innerHTML = btn.dataset.html; }, 900);
  addProduct(Number(btn.dataset.product));
}

// Panel de personalizacion para productos con modificadores (agregos, elegir bebida, etc.)
function openCustomize(pid) {
  fetch('/api/products/' + pid + '/modifiers').then(r => r.json()).then(data => {
    if (!data.groups || !data.groups.length) return;
    const back = document.createElement('div'); back.className = 'modal-back';
    const box = document.createElement('div'); box.className = 'box modal-box';
    box.innerHTML = '<h2>' + esc(data.name) + '</h2>' + data.groups.map(g => {
      const type = g.max_select === 1 ? 'radio' : 'checkbox';
      return '<div class="mgroup"><b>' + esc(g.name) + (g.required ? ' <small>(obligatorio)</small>' : ' <small>(opcional)</small>') + '</b>' +
        g.options.map(o => '<label class="mopt"><input type="' + type + '" name="g' + g.id + '" value="' + o.id + '" data-price="' + o.price_extra + '"><span>' + esc(o.name) + (o.price_extra > 0 ? ' (+$' + o.price_extra.toFixed(0) + ')' : '') + '</span></label>').join('') +
        '</div>';
    }).join('') + '<button class="btn block" id="modal-add">Agregar — $<span id="modal-total">' + data.base_price.toFixed(0) + '</span></button>';
    back.appendChild(box); document.body.appendChild(back);
    const total = () => {
      let t = data.base_price;
      box.querySelectorAll('input:checked').forEach(i => t += Number(i.dataset.price || 0));
      box.querySelector('#modal-total').textContent = t.toFixed(0);
    };
    box.addEventListener('change', total);
    back.addEventListener('click', (e) => { if (e.target === back) back.remove(); });
    box.querySelector('#modal-add').addEventListener('click', async () => {
      const missing = data.groups.find(g => g.required && !box.querySelector('input[name=g' + g.id + ']:checked'));
      if (missing) { alert('Elegí una opción en "' + missing.name + '".'); return; }
      const modifiers = Array.from(box.querySelectorAll('input:checked')).map(i => Number(i.value));
      back.remove();
      addProduct(pid, modifiers);
    });
  }).catch(() => {});
}
document.querySelectorAll('.add').forEach(b => b.addEventListener('click', () => {
  if (b.dataset.modifiers === '1') openCustomize(Number(b.dataset.product)); else addToCart(b);
}));

// Menu en 3D: el plato girando y "Ver en tu mesa" (realidad aumentada con la camara, sin instalar nada).
// El visor (model-viewer, copiado en /static/vendor) se baja recien cuando alguien toca "3D".
let viewer3d = null;
function open3d(b) {
  viewer3d = viewer3d || import('/static/vendor/model-viewer/model-viewer.min.js');
  const back = document.createElement('div'); back.className = 'modal-back';
  const box = document.createElement('div'); box.className = 'box modal-box m3d-box';
  const ios = b.dataset.arIos ? ' ios-src="' + esc(b.dataset.arIos) + '"' : '';
  box.innerHTML = '<div class="m3d-head"><h2>' + esc(b.dataset.arName) + '</h2><button type="button" class="m3d-close" aria-label="Cerrar">✕</button></div>' +
    '<model-viewer class="m3d-view" src="' + esc(b.dataset.ar) + '"' + ios + ' alt="' + esc(b.dataset.arName) + ' en 3D" camera-controls auto-rotate' +
    ' shadow-intensity="1" ar ar-modes="webxr scene-viewer quick-look" ar-placement="floor" touch-action="pan-y">' +
    '<button slot="ar-button" hidden></button><div slot="progress-bar"></div></model-viewer>' +
    '<p class="m3d-hint">Cargando el plato en 3D…</p>' +
    '<button type="button" class="btn block secondary m3d-ar" hidden>📱 Ver en tu mesa</button>' +
    (b.dataset.can === '1' ? '<button type="button" class="btn block m3d-add">Agregar al pedido · ' + esc(b.dataset.arPrice) + '</button>' : '');
  back.appendChild(box); document.body.appendChild(back);
  const close = () => back.remove();
  back.addEventListener('click', (e) => { if (e.target === back) close(); });
  box.querySelector('.m3d-close').addEventListener('click', close);
  const mv = box.querySelector('model-viewer'), hint = box.querySelector('.m3d-hint'), ar = box.querySelector('.m3d-ar');
  viewer3d.then(() => {
    mv.addEventListener('load', () => {
      if (mv.canActivateAR) { ar.hidden = false; hint.textContent = 'Giralo con el dedo, o tocá "Ver en tu mesa" y apuntá la cámara a la mesa.'; }
      else hint.textContent = 'Giralo con el mouse o el dedo. Para verlo sobre tu mesa, abrí esta página desde el celular.';
    });
    mv.addEventListener('error', () => { hint.textContent = 'No se pudo abrir el 3D de este plato.'; });
  }).catch(() => { hint.textContent = 'Tu navegador no puede mostrar el 3D.'; });
  ar.addEventListener('click', () => mv.activateAR());
  const add = box.querySelector('.m3d-add');
  if (add) add.addEventListener('click', () => {
    close();
    if (b.dataset.modifiers === '1') openCustomize(Number(b.dataset.product)); else addProduct(Number(b.dataset.product));
  });
}
document.querySelectorAll('.m3d-btn').forEach(b => b.addEventListener('click', () => open3d(b)));

if (document.getElementById('cart-bar') || document.getElementById('cart-lines')) { const t0 = cartToken; api('/api/cart').then(c => renderCart(c, t0)).catch(() => {}); }

document.querySelectorAll('.cart-update').forEach(b => b.addEventListener('click', async () => {
  try { await post('/api/cart/update', { line_key: b.dataset.key, quantity: Number(b.dataset.quantity) }); location.reload(); } catch (e) { alert(e.message); }
}));
document.getElementById('clear-cart')?.addEventListener('click', async () => { if (await askConfirm('¿Vaciar el pedido?', 'Vaciar')) { await post('/api/cart/clear'); location.reload(); } });

// checkout: mostrar/ocultar dirección y recalcular total según la modalidad
const shipEl = document.getElementById('shipping-value');
if (shipEl) {
  const totalEl = document.getElementById('total-value');
  const sub = Number(document.querySelector('[data-subtotal]')?.dataset.subtotal || 0), ship = Number(shipEl.dataset.shipping || 0), discount = Number(totalEl?.dataset.discount || 0);
  const address = document.getElementById('address');
  const apply = () => {
    const delivery = document.querySelector('input[name=delivery_method]:checked')?.value === 'delivery';
    if (address) { address.required = delivery; address.disabled = !delivery; address.style.opacity = delivery ? 1 : .5; }
    shipEl.textContent = money(delivery ? ship : 0);
    // puntos Trappi: el descuento lo calculó el servidor (con envío o retirando); al confirmar lo vuelve a validar
    const pts = document.getElementById('use-points');
    const ptsOff = pts && pts.checked ? Number(delivery ? pts.dataset.delivery : pts.dataset.pickup) || 0 : 0;
    if (pts) {
      const n = Number(delivery ? pts.dataset.deliveryPoints : pts.dataset.pickupPoints) || 0;
      document.getElementById('points-n').textContent = n;
      document.getElementById('points-off').textContent = money(Number(delivery ? pts.dataset.delivery : pts.dataset.pickup) || 0);
      const line = document.getElementById('points-line');
      if (line) { line.hidden = !ptsOff; document.getElementById('points-line-value').textContent = '-' + money(ptsOff); }
    }
    const vch = document.getElementById('use-voucher');
    const vOff = vch && vch.checked ? Number(delivery ? vch.dataset.delivery : vch.dataset.pickup) || 0 : 0;
    if (vch) {
      document.getElementById('voucher-off').textContent = money(Number(delivery ? vch.dataset.delivery : vch.dataset.pickup) || 0);
      const vl = document.getElementById('voucher-line');
      if (vl) { vl.hidden = !vOff; document.getElementById('voucher-line-value').textContent = '-' + money(vOff); }
    }
    const grand = money(sub + (delivery ? ship : 0) - discount - ptsOff - vOff);
    if (totalEl) totalEl.textContent = grand;
    const confirmTotal = document.getElementById('confirm-total'); if (confirmTotal) confirmTotal.textContent = grand;
  };
  document.querySelectorAll('input[name=delivery_method]').forEach(r => r.addEventListener('change', apply));
  document.getElementById('use-points')?.addEventListener('change', apply);
  document.getElementById('use-voucher')?.addEventListener('change', apply); apply();
}

// checkout: efectivo pide "con cuánto pagás", transferencia muestra los datos del local
const payCash = document.getElementById('pay-cash');
if (payCash) {
  const payTransfer = document.getElementById('pay-transfer');
  const applyPay = () => {
    const transfer = document.querySelector('input[name=payment_method]:checked')?.value === 'transferencia';
    const method = document.querySelector('input[name=payment_method]:checked')?.value;
    payCash.style.display = method === 'efectivo' ? '' : 'none'; if (payTransfer) payTransfer.hidden = !transfer;
    const payOnline = document.getElementById('pay-online'); if (payOnline) payOnline.hidden = method !== 'mercadopago';
    const payTotal = document.getElementById('pay-total'), totalEl = document.getElementById('total-value');
    if (payTotal && totalEl) payTotal.textContent = totalEl.textContent;
  };
  document.querySelectorAll('input[name=payment_method], input[name=delivery_method]').forEach(r => r.addEventListener('change', applyPay)); applyPay();
}

/* ---- v3: avisos, autocompletado, buscador de menú, pestañas activas ---- */
function toast(msg) { const t = document.getElementById('toast'); if (!t) return alert(msg); t.textContent = msg; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 3200); }
window.alert = toast; // los errores del carrito se muestran como aviso en vez de ventana

const form = document.getElementById('checkout-form');
if (form) {
  const KEY = 'trappi_customer', fields = ['first_name', 'last_name', 'phone', 'address', 'reference'];
  try { const saved = JSON.parse(localStorage.getItem(KEY) || '{}'); fields.forEach(f => { const el = form.elements[f]; if (el && !el.value && saved[f]) el.value = saved[f]; }); } catch (e) {}
  form.addEventListener('submit', () => { const data = {}; fields.forEach(f => { if (form.elements[f]) data[f] = form.elements[f].value; }); try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) {} });
}

const search = document.getElementById('menu-search');
if (search) search.addEventListener('input', () => {
  const q = search.value.trim().toLowerCase();
  document.querySelectorAll('.mrow').forEach(r => { r.hidden = q && !r.textContent.toLowerCase().includes(q); });
  document.querySelectorAll('.msec').forEach(s => { s.hidden = ![...s.querySelectorAll('.mrow')].some(r => !r.hidden); });
});

const tabLinks = [...document.querySelectorAll('.tabs a')];
if (tabLinks.length && 'IntersectionObserver' in window) {
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) tabLinks.forEach(a => a.classList.toggle('on', a.getAttribute('href') === '#' + e.target.id)); }), { rootMargin: '-140px 0px -65% 0px' });
  document.querySelectorAll('.msec').forEach(s => io.observe(s));
}

// calificacion: texto que acompaña a las estrellas elegidas
const starsHint = document.getElementById('stars-hint');
if (starsHint) {
  const words = { 1: 'Malo', 2: 'Regular', 3: 'Bueno', 4: 'Muy bueno', 5: '¡Excelente!' };
  document.querySelectorAll('.stars input').forEach(i => i.addEventListener('change', () => { starsHint.textContent = i.value + ' de 5 · ' + words[i.value]; }));
}

// checkout: "Los que pidieron esto también llevaron"
document.querySelectorAll('.js-together').forEach(b => b.addEventListener('click', async () => {
  b.disabled = true;
  try { await post('/api/cart/add', { product_id: Number(b.dataset.product), quantity: 1, modifiers: [] }); location.reload(); }
  catch (e) { b.disabled = false; alert(e.message); }
}));

// checkout: direcciones guardadas (Casa, Trabajo...). Si tiene el punto del mapa, el servidor recalcula el envio:
// se recarga, pero todo lo que escribio y donde estaba en la pantalla quedan igual.
const KEEP = 'trappi-checkout-keep';
function keepCheckout(f) {
  const data = {};
  [...f.elements].forEach(el => {
    if (!el.name || el.type === 'hidden' || el.type === 'submit') return;
    if (el.type === 'radio' || el.type === 'checkbox') { if (el.checked) data[el.name + ':' + el.value] = true; }
    else data[el.name] = el.value;
  });
  try { sessionStorage.setItem(KEEP, JSON.stringify({ data, y: scrollY, at: Date.now() })); } catch (e) { /* sin sessionStorage */ }
}
document.querySelectorAll('.addr-chip[data-address]').forEach(b => b.addEventListener('click', async () => {
  const f = document.getElementById('checkout-form'); if (!f) return;
  f.address.value = b.dataset.address; f.reference.value = b.dataset.reference || '';
  document.querySelectorAll('.addr-chip').forEach(x => x.classList.toggle('on', x === b));
  if (!b.dataset.lat) return;
  b.disabled = true; toast('Calculando el envío a ' + b.dataset.address + '…');
  try {
    await post('/api/ubicacion', { lat: Number(b.dataset.lat), lng: Number(b.dataset.lng), label: b.dataset.address });
    keepCheckout(f); location.reload();
  } catch (e) { b.disabled = false; /* queda la direccion escrita: el envio se calcula al confirmar */ }
}));
try {
  const keep = JSON.parse(sessionStorage.getItem(KEEP) || 'null'); sessionStorage.removeItem(KEEP);
  const f = document.getElementById('checkout-form');
  if (keep && f && Date.now() - keep.at < 60000) {
    [...f.elements].forEach(el => {
      if (!el.name || el.type === 'hidden') return;
      if (el.type === 'radio' || el.type === 'checkbox') { if (!el.disabled && (el.name + ':' + el.value) in keep.data) { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); } }
      else if (el.name in keep.data) el.value = keep.data[el.name];
    });
    document.querySelectorAll('.addr-chip[data-address]').forEach(x => x.classList.toggle('on', x.dataset.address === f.address.value));
    scrollTo(0, keep.y);
  }
} catch (e) { /* sin sessionStorage */ }
