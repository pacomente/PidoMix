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
    lines.innerHTML = c.items.map(i => `<div class="cl"><span>${i.name}</span><span class="step"><button data-pid="${i.product_id}" data-q="${i.quantity - 1}" aria-label="Quitar uno">−</button><b>${i.quantity}</b><button data-pid="${i.product_id}" data-q="${i.quantity + 1}" aria-label="Agregar uno">+</button></span></div>`).join('')
      + `<div class="tot"><span>Subtotal</span><span>${money(c.subtotal)}</span></div><a class="btn block" href="/checkout">Ir a pagar</a>`;
    lines.querySelectorAll('button[data-pid]').forEach(b => b.addEventListener('click', async () => {
      try { renderCart(await post('/api/cart/update', { product_id: Number(b.dataset.pid), quantity: Number(b.dataset.q) })); } catch (e) { alert(e.message); }
    }));
  }
}

async function addToCart(btn) {
  const pid = Number(btn.dataset.product);
  const flash = () => { const t = btn.textContent; btn.textContent = '✓'; setTimeout(() => btn.textContent = t, 900); };
  try { renderCart(await post('/api/cart/add', { product_id: pid, quantity: 1 })); flash(); }
  catch (e) {
    if (e.data && e.data.code === 'DIFFERENT_STORE' && confirm('Tu pedido tiene productos de otro comercio. ¿Querés vaciarlo y empezar uno nuevo?')) {
      await post('/api/cart/clear'); renderCart(await post('/api/cart/add', { product_id: pid, quantity: 1 })); flash();
    } else alert(e.message);
  }
}
document.querySelectorAll('.add').forEach(b => b.addEventListener('click', () => addToCart(b)));

if (document.getElementById('cart-bar') || document.getElementById('cart-lines')) api('/api/cart').then(renderCart).catch(() => {});

document.querySelectorAll('.cart-update').forEach(b => b.addEventListener('click', async () => {
  try { await post('/api/cart/update', { product_id: Number(b.dataset.product), quantity: Number(b.dataset.quantity) }); location.reload(); } catch (e) { alert(e.message); }
}));
document.getElementById('clear-cart')?.addEventListener('click', async () => { if (confirm('¿Vaciar el pedido?')) { await post('/api/cart/clear'); location.reload(); } });

// checkout: mostrar/ocultar dirección y recalcular total según la modalidad
const shipEl = document.getElementById('shipping-value');
if (shipEl) {
  const sub = Number(document.querySelector('[data-subtotal]')?.dataset.subtotal || 0), ship = Number(shipEl.dataset.shipping || 0);
  const address = document.getElementById('address');
  const apply = () => {
    const delivery = document.querySelector('input[name=delivery_method]:checked')?.value === 'delivery';
    if (address) { address.required = delivery; address.disabled = !delivery; address.style.opacity = delivery ? 1 : .5; }
    shipEl.textContent = money(delivery ? ship : 0);
    document.getElementById('total-value').textContent = money(sub + (delivery ? ship : 0));
  };
  document.querySelectorAll('input[name=delivery_method]').forEach(r => r.addEventListener('change', apply)); apply();
}
