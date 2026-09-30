/* Trappi — carrito y checkout */
async function api(url, options = {}) {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, credentials: 'same-origin', ...options });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(d.message || d.error || 'Ocurrió un error'), { data: d, status: r.status });
  return d;
}
const money = (n) => '$' + Number(n || 0).toLocaleString('es-AR', { maximumFractionDigits: 0 });
const post = (url, body) => api(url, { method: 'POST', body: JSON.stringify(body || {}) });

function renderCart(c) {
  const n = c.count || 0;
  const badge = document.getElementById('cart-count'); if (badge) badge.textContent = n;
  const bar = document.getElementById('cart-bar');
  if (bar) { bar.hidden = n === 0; document.getElementById('cart-bar-n').textContent = 'Ver mi pedido · ' + n + (n === 1 ? ' producto' : ' productos'); document.getElementById('cart-bar-total').textContent = money(c.subtotal); }
  const lines = document.getElementById('cart-lines');
  if (lines) {
    if (!n) { lines.innerHTML = '<p style="color:var(--muted)">Agregá productos para empezar tu pedido.</p>'; return; }
    lines.innerHTML = c.items.map(i => `<div class="cl"><span>${i.name}${i.modifiers_text ? '<small class="cl-mod">' + i.modifiers_text + '</small>' : ''}</span><span class="step"><button data-key="${i.line_key}" data-q="${i.quantity - 1}" aria-label="Quitar uno">−</button><b>${i.quantity}</b><button data-key="${i.line_key}" data-q="${i.quantity + 1}" aria-label="Agregar uno">+</button></span></div>`).join('')
      + `<div class="tot"><span>Subtotal</span><span>${money(c.subtotal)}</span></div><a class="btn block" href="/checkout">Ir a pagar</a>`;
    lines.querySelectorAll('button[data-key]').forEach(b => b.addEventListener('click', async () => {
      try { renderCart(await post('/api/cart/update', { line_key: b.dataset.key, quantity: Number(b.dataset.q) })); } catch (e) { alert(e.message); }
    }));
  }
}

async function addToCart(btn, modifiers) {
  const pid = Number(btn.dataset.product);
  const flash = () => { const t = btn.textContent; btn.textContent = '✓'; setTimeout(() => btn.textContent = t, 900); };
  try { renderCart(await post('/api/cart/add', { product_id: pid, quantity: 1, modifiers: modifiers || [] })); flash(); }
  catch (e) {
    if (e.data && e.data.code === 'DIFFERENT_STORE' && confirm('Tu pedido tiene productos de otro comercio. ¿Querés vaciarlo y empezar uno nuevo?')) {
      await post('/api/cart/clear'); renderCart(await post('/api/cart/add', { product_id: pid, quantity: 1, modifiers: modifiers || [] })); flash();
    } else alert(e.message);
  }
}

// Panel de personalizacion para productos con modificadores (agregos, elegir bebida, etc.)
function openCustomize(pid) {
  fetch('/api/products/' + pid + '/modifiers').then(r => r.json()).then(data => {
    if (!data.groups || !data.groups.length) return;
    const back = document.createElement('div'); back.className = 'modal-back';
    const box = document.createElement('div'); box.className = 'box modal-box';
    box.innerHTML = '<h2>' + data.name + '</h2>' + data.groups.map(g => {
      const type = g.max_select === 1 ? 'radio' : 'checkbox';
      return '<div class="mgroup"><b>' + g.name + (g.required ? ' <small>(obligatorio)</small>' : ' <small>(opcional)</small>') + '</b>' +
        g.options.map(o => '<label class="mopt"><input type="' + type + '" name="g' + g.id + '" value="' + o.id + '" data-price="' + o.price_extra + '"><span>' + o.name + (o.price_extra > 0 ? ' (+$' + o.price_extra.toFixed(0) + ')' : '') + '</span></label>').join('') +
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
      try { renderCart(await post('/api/cart/add', { product_id: pid, quantity: 1, modifiers })); back.remove(); }
      catch (e) {
        if (e.data && e.data.code === 'DIFFERENT_STORE' && confirm('Tu pedido tiene productos de otro comercio. ¿Querés vaciarlo y empezar uno nuevo?')) {
          await post('/api/cart/clear'); renderCart(await post('/api/cart/add', { product_id: pid, quantity: 1, modifiers })); back.remove();
        } else alert(e.message);
      }
    });
  }).catch(() => {});
}
document.querySelectorAll('.add').forEach(b => b.addEventListener('click', () => {
  if (b.dataset.modifiers === '1') openCustomize(Number(b.dataset.product)); else addToCart(b);
}));

if (document.getElementById('cart-bar') || document.getElementById('cart-lines')) api('/api/cart').then(renderCart).catch(() => {});

document.querySelectorAll('.cart-update').forEach(b => b.addEventListener('click', async () => {
  try { await post('/api/cart/update', { line_key: b.dataset.key, quantity: Number(b.dataset.quantity) }); location.reload(); } catch (e) { alert(e.message); }
}));
document.getElementById('clear-cart')?.addEventListener('click', async () => { if (confirm('¿Vaciar el pedido?')) { await post('/api/cart/clear'); location.reload(); } });

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
    if (totalEl) totalEl.textContent = money(sub + (delivery ? ship : 0) - discount);
  };
  document.querySelectorAll('input[name=delivery_method]').forEach(r => r.addEventListener('change', apply)); apply();
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
