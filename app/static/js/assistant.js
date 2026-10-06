/* Trappi AI en la web: el estado de la charla lo guarda esta pestaña (firmado por el servidor). */
(function () {
  const chat = document.getElementById('ai-chat'), form = document.getElementById('ai-form'), input = document.getElementById('ai-input');
  if (!chat || !form) return;
  const KEY = 'trappi-ai-state';
  let state = null;
  try { state = sessionStorage.getItem(KEY); } catch (e) { state = null; }
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (s) => esc(s).replace(/\*([^*\n]+)\*/g, '<b>$1</b>').replace(/\n/g, '<br>');
  const money = (n) => '$' + Number(n || 0).toLocaleString('es-AR', { maximumFractionDigits: 0 });

  function add(role, html) {
    const el = document.createElement('div');
    el.className = 'ai-msg ' + role;
    el.innerHTML = '<div class="ai-bubble">' + html + '</div>';
    chat.appendChild(el);
    el.scrollIntoView({ block: 'end', behavior: 'smooth' });
    return el;
  }

  function card(c) {
    if (c.type === 'store') {
      const s = c.store, cov = s.coverage || {};
      const meta = [s.rating ? '⭐ ' + String(s.rating).replace('.', ',') + ' (' + s.rating_count + ')' : 'Sin reseñas',
        cov.distance_km != null ? '📍 ' + String(cov.distance_km.toFixed(1)).replace('.', ',') + ' km' : null,
        '🚴 ' + (cov.eta_min ? cov.eta_min + '–' + cov.eta_max : s.eta_min + '–' + s.eta_max) + ' min',
        s.is_open ? null : '🔒 ' + (s.open_text || 'Cerrado')].filter(Boolean).join(' · ');
      return '<a class="ai-card" href="/tienda/' + encodeURIComponent(s.slug) + '"><b>' + esc(s.emoji) + ' ' + esc(s.name) + '</b><small>' + esc(meta) + '</small></a>';
    }
    const p = c.product;
    return '<a class="ai-card" href="/tienda/' + encodeURIComponent(p.store.slug) + '"><b>' + esc(p.emoji) + ' ' + esc(p.name) + '</b><small>' + money(p.price)
      + (p.previous_price ? ' <s>' + money(p.previous_price) + '</s>' : '') + ' · ' + esc(p.store.name) + (p.sold_out ? ' · Agotado' : '') + '</small></a>';
  }

  async function send(text) {
    add('me', esc(text));
    const hints = document.getElementById('ai-hints'); if (hints) hints.hidden = true;
    const wait = add('bot', '<span class="ai-typing">Buscando en Trappi…</span>');
    input.value = ''; input.disabled = true;
    try {
      const r = await fetch('/api/ai/chat', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text, state }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) { wait.querySelector('.ai-bubble').innerHTML = esc(d.error || 'No pude responder. Probá de nuevo.'); return; }
      state = d.state;
      try { sessionStorage.setItem(KEY, state); } catch (e) { /* sin almacenamiento: la charla dura mientras la página esté abierta */ }
      wait.querySelector('.ai-bubble').innerHTML = fmt(d.reply) + (d.cards && d.cards.length ? '<div class="ai-cards">' + d.cards.map(card).join('') + '</div>' : '');
      if (d.cart_changed) {
        fetch('/api/cart', { credentials: 'same-origin' }).then(x => x.json()).then(c => { if (typeof renderCart === 'function') renderCart(c); }).catch(() => {});
        wait.querySelector('.ai-bubble').insertAdjacentHTML('beforeend', '<a class="btn small ai-go" href="/checkout">Ver mi pedido</a>');
      }
    } catch (e) {
      wait.querySelector('.ai-bubble').textContent = 'Sin conexión. Probá de nuevo.';
    } finally {
      input.disabled = false; input.focus();
    }
  }

  form.addEventListener('submit', (e) => { e.preventDefault(); const t = input.value.trim(); if (t) send(t); });
  document.querySelectorAll('[data-hint]').forEach(b => b.addEventListener('click', () => send(b.dataset.hint)));
})();
