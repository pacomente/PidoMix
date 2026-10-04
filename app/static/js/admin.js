/* Trappi — mejoras del panel: etiquetas visibles, carga de imágenes, edición en línea
   y formularios de alta plegables. Sin JS el panel funciona igual (solo se ve más simple). */
(function () {
  // Nombres de campo que aparecen sin placeholder (por ejemplo en los formularios de edición)
  const KNOWN = {
    name: 'Nombre', slug: 'Dirección web (slug)', description: 'Descripción', price: 'Precio', previous_price: 'Precio anterior',
    stock: 'Stock', display_order: 'Orden en el menú', store_id: 'Tienda', category_id: 'Categoría', section_id: 'Sección del menú',
    phone: 'Teléfono', whatsapp: 'WhatsApp', address: 'Dirección', store_category_id: 'Rubro', delivery_cost: 'Costo de envío',
    minimum_order: 'Pedido mínimo', estimated_minutes: 'Minutos estimados de entrega', title: 'Título', subtitle: 'Subtítulo',
    button_text: 'Texto del botón', link: 'Link', code: 'Código', discount_type: 'Tipo de descuento', discount_value: 'Valor',
    min_order: 'Pedido mínimo', max_uses: 'Usos máximos', expires_at: 'Vence', email: 'Email', password: 'Contraseña',
    role: 'Rol', owner_email: 'Email del local', owner_password: 'Contraseña del local',
    max_select: 'Máximo a elegir', price_extra: 'Precio extra', current: 'Contraseña actual', new: 'Nueva contraseña', confirm: 'Repetir nueva contraseña',
  };
  const SKIP = new Set(['hidden', 'checkbox', 'radio', 'file', 'submit', 'button', 'time']);

  // Prioridad: etiqueta explicita, placeholder, lo aprendido del formulario de alta de la misma pagina
  // (asi «Editar» usa los mismos nombres), el texto de la opcion vacia y por ultimo nombres conocidos.
  function labelFor(el, learned) {
    if (el.dataset.label) return [el.dataset.label, 'data'];
    if (el.placeholder) return [el.placeholder, 'placeholder'];
    if (learned[el.name]) return [learned[el.name], 'learned'];
    if (el.tagName === 'SELECT' && el.options[0] && el.options[0].value === '') return [el.options[0].text, 'option'];
    return [KNOWN[el.name] || '', 'known'];
  }

  // 1) etiqueta visible arriba de cada campo
  function addLabels(root) {
    const learned = {};
    root.querySelectorAll('form[method=post] .panel-body, form.panel-body[method=post]').forEach(scope => {
      scope.querySelectorAll('input, select, textarea').forEach(el => {
        if (SKIP.has(el.type) || el.closest('label') || el.closest('.no-label') || !el.name) return;
        const [text, source] = labelFor(el, learned);
        if (!text) return;
        learned[el.name] = learned[el.name] || text;
        const label = document.createElement('label');
        label.className = 'field' + (el.tagName === 'TEXTAREA' ? ' wide' : '');
        const span = document.createElement('span');
        span.textContent = text.replace(/\s*\(opcional\)$/i, '');
        if (/\(opcional\)$/i.test(text) || (!el.required && el.tagName !== 'SELECT')) span.insertAdjacentHTML('beforeend', ' <em>opcional</em>');
        el.replaceWith(label); label.append(span, el);
        if (el.placeholder === text) el.placeholder = '';
        if (source === 'option') el.options[0].text = 'Elegí una opción';
        // una sola opcion posible (por ejemplo, la tienda del local): se elige sola y no se muestra
        const real = el.tagName === 'SELECT' ? [...el.options].filter(o => o.value !== '') : [];
        if (el.name === 'store_id' && real.length === 1) { el.value = real[0].value; label.hidden = true; }
      });
    });
  }

  // 2) carga de imágenes: botón propio + vista previa
  function enhanceFiles(root) {
    root.querySelectorAll('input[type=file]').forEach(input => {
      if (input.closest('.file-drop')) return;
      const drop = document.createElement('label');
      drop.className = 'file-drop';
      const nameHint = { logo: 'Logo del local', cover: 'Foto de portada' }[input.name] || 'Imagen';
      drop.innerHTML = '<img alt="" hidden><span class="file-text"><b>' + nameHint + '</b><small>Tocá para elegir una foto · JPG, PNG, WEBP o HEIC de hasta 10 MB (se optimiza sola)</small></span><span class="btn small secondary">Elegir foto</span>';
      input.replaceWith(drop); drop.prepend(input);
      input.addEventListener('change', () => {
        const file = input.files && input.files[0];
        const img = drop.querySelector('img');
        if (!file) { img.hidden = true; return; }
        drop.querySelector('small').textContent = file.name + ' · ' + Math.round(file.size / 1024) + ' KB' + (file.size > 10 * 1024 * 1024 ? ' — supera los 10 MB' : '');
        drop.classList.toggle('too-big', file.size > 5 * 1024 * 1024);
        img.src = URL.createObjectURL(file); img.hidden = false;
      });
    });
  }

  // 3) "Editar" dentro de la fila, en lugar de una fila suelta "Editar ⌄"
  function enhanceEditRows(root) {
    root.querySelectorAll('details.edit-row').forEach(details => {
      const row = details.closest('tr'), prev = row && row.previousElementSibling;
      const actions = prev && prev.querySelector('.row-actions');
      if (!actions || actions.querySelector('.js-edit')) return;
      details.classList.add('js-enhanced'); row.classList.add('edit-host');
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'btn small secondary js-edit'; btn.textContent = 'Editar';
      btn.setAttribute('aria-expanded', 'false');
      btn.addEventListener('click', () => {
        details.open = !details.open;
        btn.textContent = details.open ? 'Cerrar' : 'Editar'; btn.setAttribute('aria-expanded', String(details.open));
        row.classList.toggle('is-open', details.open); prev.classList.toggle('is-editing', details.open);
        if (details.open) { const first = details.querySelector('input:not([type=hidden]), select, textarea'); if (first) first.focus({ preventScroll: true }); }
      });
      actions.prepend(btn);
    });
  }

  // 4) formularios "Nuevo…" plegados detrás de un botón (abiertos si no hay nada cargado o hubo un error)
  function collapseCreatePanels(root) {
    root.querySelectorAll('.panel').forEach(panel => {
      const h2 = panel.querySelector(':scope > .panel-header h2');
      const body = panel.querySelector(':scope > form, :scope > .panel-body');
      if (!h2 || !body || !/^Nuev[oa]\b/.test(h2.textContent.trim()) || panel.dataset.keepOpen !== undefined) return;
      const empty = document.querySelector('.empty-row, .empty-state');
      const open = !!empty || new URLSearchParams(location.search).has('error');
      panel.classList.add('create-panel'); panel.classList.toggle('is-open', open);
      const header = panel.querySelector(':scope > .panel-header');
      const btn = document.createElement('button');
      btn.type = 'button'; btn.className = 'create-toggle';
      btn.innerHTML = '<svg class="i" aria-hidden="true"><use href="#i-plus"/></svg><span></span>';
      btn.querySelector('span').textContent = h2.textContent.trim();
      btn.setAttribute('aria-expanded', String(open));
      btn.addEventListener('click', () => {
        const now = !panel.classList.contains('is-open');
        panel.classList.toggle('is-open', now); btn.setAttribute('aria-expanded', String(now));
        if (now) { const f = body.querySelector('input:not([type=hidden]), select, textarea'); if (f) f.focus(); }
      });
      header.replaceChildren(btn);
    });
  }

  addLabels(document); enhanceFiles(document); enhanceEditRows(document); collapseCreatePanels(document);
})();
