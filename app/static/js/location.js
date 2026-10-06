/* Trappi — ubicación del cliente: GPS, búsqueda de dirección o tocar el mapa.
   Leaflet se carga recién cuando se abre el selector. */
(function () {
  const VENDOR = '/static/vendor/leaflet/';
  const root = document.documentElement;
  const DEFAULT = (root.dataset.mapCenter || '-38.7183,-62.2663').split(',').map(Number);
  let leaflet = null;

  function loadLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    if (leaflet) return leaflet;
    leaflet = new Promise((resolve, reject) => {
      const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = VENDOR + 'leaflet.css'; document.head.appendChild(css);
      const js = document.createElement('script'); js.src = VENDOR + 'leaflet.js'; js.onload = () => resolve(window.L); js.onerror = reject; document.head.appendChild(js);
    });
    return leaflet;
  }
  window.trappiLoadLeaflet = loadLeaflet;

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  // Nominatim (OpenStreetMap): búsquedas solo al apretar "Buscar", nunca mientras se escribe (política de uso)
  // proveedores configurables desde el panel (Configuración → Mapas)
  const NOMINATIM = (root.dataset.geocoder || 'https://nominatim.openstreetmap.org/').replace(/\/?$/, '/');
  const TILES = root.dataset.tiles || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const TILES_ATTR = root.dataset.tilesAttr || '&copy; OpenStreetMap';
  function shortLabel(a) {
    if (!a) return '';
    const road = a.road || a.pedestrian || a.footway || a.neighbourhood || a.suburb || '';
    return [road && (road + (a.house_number ? ' ' + a.house_number : '')), a.city || a.town || a.village || ''].filter(Boolean).join(', ');
  }

  function openPicker(opts = {}) {
    const current = (() => { try { return JSON.parse(root.dataset.loc || 'null'); } catch (e) { return null; } })();
    const back = document.createElement('div'); back.className = 'modal-back loc-modal';
    back.innerHTML = `
      <div class="box modal-box loc-box" role="dialog" aria-modal="true" aria-labelledby="loc-title">
        <button class="loc-close" type="button" aria-label="Cerrar">×</button>
        <h2 id="loc-title">¿Dónde recibís tu pedido?</h2>
        <p class="loc-sub">Así te mostramos qué comercios llegan hasta vos y cuánto sale el envío.</p>
        <button class="btn block loc-gps" type="button">Usar mi ubicación actual</button>
        <form class="loc-search"><input name="q" placeholder="O buscá tu dirección: calle y número, ciudad" aria-label="Buscar dirección" autocomplete="street-address"><button class="btn secondary small">Buscar</button></form>
        <ul class="loc-results" hidden></ul>
        <div class="loc-map" aria-label="Mapa: tocá para marcar tu ubicación"></div>
        <p class="loc-hint">Tocá el mapa o mové el pin hasta tu puerta.</p>
        <label class="loc-label">Nombre o dirección <input name="label" maxlength="120" placeholder="Ej: Casa, Av. Alem 1250"></label>
        <div class="loc-actions">${current ? '<button type="button" class="link-btn loc-clear">Borrar mi ubicación</button>' : '<span></span>'}<button class="btn loc-save" type="button" disabled>Confirmar ubicación</button></div>
      </div>`;
    document.body.appendChild(back);
    const box = back.querySelector('.loc-box'), save = box.querySelector('.loc-save'), labelInput = box.querySelector('[name=label]');
    const close = () => back.remove();
    back.addEventListener('click', e => { if (e.target === back) close(); });
    box.querySelector('.loc-close').addEventListener('click', close);
    document.addEventListener('keydown', function onKey(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } });
    if (current) labelInput.value = current.label || '';

    let map, marker, point = current ? [current.lat, current.lng] : null, reverseTimer;
    const setPoint = (lat, lng, label, zoom) => {
      point = [lat, lng]; save.disabled = false;
      if (map) {
        if (!marker) { marker = window.L.marker(point, { draggable: true }).addTo(map); marker.on('dragend', () => { const p = marker.getLatLng(); setPoint(p.lat, p.lng); }); }
        marker.setLatLng(point); map.setView(point, zoom || Math.max(map.getZoom(), 16));
      }
      if (label) labelInput.value = label;
      else { clearTimeout(reverseTimer); reverseTimer = setTimeout(() => reverse(lat, lng), 600); }
    };
    function reverse(lat, lng) {
      fetch(NOMINATIM + 'reverse?format=jsonv2&addressdetails=1&zoom=18&lat=' + lat + '&lon=' + lng, { headers: { 'Accept-Language': 'es' } })
        .then(r => r.json()).then(d => { const l = shortLabel(d.address); if (l) labelInput.value = l; }).catch(() => {});
    }

    loadLeaflet().then(L => {
      map = L.map(box.querySelector('.loc-map'), { zoomControl: true }).setView(point || opts.center || DEFAULT, point ? 16 : 13);
      L.tileLayer(TILES, { maxZoom: 19, attribution: TILES_ATTR }).addTo(map);
      if (opts.store) L.circleMarker(opts.store, { radius: 7, color: '#6C2BD9', fillOpacity: .9 }).addTo(map).bindTooltip('El local');
      if (point) setPoint(point[0], point[1], labelInput.value || ' ');
      map.on('click', e => setPoint(e.latlng.lat, e.latlng.lng));
      setTimeout(() => map.invalidateSize(), 50);
    }).catch(() => { box.querySelector('.loc-map').innerHTML = '<p class="loc-error">No se pudo cargar el mapa. Usá el GPS o buscá tu dirección.</p>'; });

    box.querySelector('.loc-gps').addEventListener('click', e => {
      const btn = e.currentTarget;
      if (!navigator.geolocation) { btn.textContent = 'Tu navegador no permite usar la ubicación'; return; }
      btn.disabled = true; btn.textContent = 'Buscando tu ubicación…';
      navigator.geolocation.getCurrentPosition(pos => {
        btn.disabled = false; btn.textContent = 'Usar mi ubicación actual';
        setPoint(pos.coords.latitude, pos.coords.longitude, null, 17);
      }, () => { btn.disabled = false; btn.textContent = 'No pudimos acceder al GPS: buscá tu dirección'; }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 });
    });

    box.querySelector('.loc-search').addEventListener('submit', e => {
      e.preventDefault();
      const q = e.currentTarget.q.value.trim(), list = box.querySelector('.loc-results');
      if (q.length < 3) return;
      list.hidden = false; list.innerHTML = '<li class="muted">Buscando…</li>';
      fetch(NOMINATIM + 'search?format=jsonv2&addressdetails=1&limit=5&countrycodes=ar&q=' + encodeURIComponent(q), { headers: { 'Accept-Language': 'es' } })
        .then(r => r.json()).then(rows => {
          if (!rows.length) { list.innerHTML = '<li class="muted">No encontramos esa dirección. Probá agregando la ciudad, o tocá el mapa.</li>'; return; }
          list.innerHTML = rows.map((r, i) => `<li><button type="button" data-i="${i}">${esc(shortLabel(r.address) || r.display_name)}<small>${esc(r.display_name)}</small></button></li>`).join('');
          list.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
            const r = rows[Number(b.dataset.i)]; list.hidden = true;
            setPoint(Number(r.lat), Number(r.lon), shortLabel(r.address) || r.display_name.split(',').slice(0, 2).join(','), 17);
          }));
        }).catch(() => { list.innerHTML = '<li class="muted">No se pudo buscar ahora. Tocá el mapa para marcar tu ubicación.</li>'; });
    });

    save.addEventListener('click', () => {
      if (!point) return;
      save.disabled = true; save.textContent = 'Guardando…';
      fetch('/api/ubicacion', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lat: point[0], lng: point[1], label: labelInput.value }) })
        .then(r => r.ok ? location.reload() : Promise.reject())
        .catch(() => { save.disabled = false; save.textContent = 'Confirmar ubicación'; });
    });
    const clear = box.querySelector('.loc-clear');
    if (clear) clear.addEventListener('click', () => fetch('/api/ubicacion', { method: 'DELETE', credentials: 'same-origin' }).then(() => location.reload()));
  }
  window.trappiPickLocation = openPicker;

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-loc-open]'); if (!t) return;
    e.preventDefault();
    const store = t.dataset.store ? t.dataset.store.split(',').map(Number) : null;
    openPicker({ store, center: store || undefined });
  });
})();
