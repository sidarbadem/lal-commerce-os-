// =====================================================================
// MANUEL SIPARIS: Siparisler sayfasinda form (ekle/duzenle/sil)
// API: /api/manual-orders (blueprints/manual_order_routes.py)
// Kayit sonrasi siparisler.js'in dinledigi 'lal:data-refresh' olayi tetiklenir.
// =====================================================================
(function () {
  const dlg = document.getElementById('manual-order-dialog');
  if (!dlg) return;
  const $ = id => document.getElementById(id);
  const skuCache = {};
  let editingId = null;
  let skuTimer;

  const tl = n => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' }).format(n || 0);
  const num = v => { const n = parseFloat(String(v == null ? '' : v).trim().replace(',', '.')); return Number.isFinite(n) ? n : 0; };
  const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const toLocalInput = ms => {
    const d = new Date(ms == null ? Date.now() : ms);
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  };

  function itemRows() { return Array.from($('mo-items').querySelectorAll('.manual-item-row')); }

  function refreshRowCost(row) {
    const c = row.dataset.cost;
    const hasSku = row.querySelector('.mi-sku').value.trim() !== '';
    row.querySelector('.mi-cost').textContent = (c !== undefined && c !== '') ? 'Maliyet ' + tl(Number(c)) : (hasSku ? 'Maliyet yok' : '');
  }

  function addItemRow(item) {
    const row = document.createElement('div');
    row.className = 'manual-item-row';
    row.innerHTML =
      '<input class="mi-sku" list="mo-sku-list" placeholder="SKU veya ürün adı" autocomplete="off">' +
      '<input class="mi-qty" type="number" min="1" step="1" value="1">' +
      '<input class="mi-price" type="text" inputmode="decimal" placeholder="Birim fiyat (KDV dahil)">' +
      '<span class="mi-cost"></span>' +
      '<button type="button" class="lal-btn lal-btn-secondary mi-del" title="Satırı sil">✕</button>';
    if (item) {
      row.querySelector('.mi-sku').value = item.sku || '';
      row.querySelector('.mi-qty').value = item.quantity || 1;
      row.querySelector('.mi-price').value = item.unitPrice != null ? item.unitPrice : '';
      row.dataset.cost = item.unitCost != null ? item.unitCost : '';
    }
    $('mo-items').appendChild(row);
    refreshRowCost(row);
    return row;
  }

  async function lookupSkus(q) {
    if (!q || q.length < 2) return;
    try {
      const res = await fetch('/api/manual-orders/skus?q=' + encodeURIComponent(q));
      const data = await res.json();
      const list = data.skus || [];
      list.forEach(s => { skuCache[s.sku] = s; });
      $('mo-sku-list').innerHTML = list.map(s => '<option value="' + esc(s.sku) + '">' + esc(s.productName || '') + '</option>').join('');
    } catch (e) { /* arama hatasi formu bozmasin */ }
  }

  function applySku(row) {
    const info = skuCache[row.querySelector('.mi-sku').value.trim()];
    if (!info) return;
    row.dataset.cost = info.costInclVat != null ? info.costInclVat : '';
    const price = row.querySelector('.mi-price');
    if (!price.value.trim() && info.salePriceInclVat != null) price.value = info.salePriceInclVat;
    refreshRowCost(row);
    updatePreview();
  }

  function readItems() {
    return itemRows().map(r => {
      const c = r.dataset.cost;
      return {
        sku: r.querySelector('.mi-sku').value.trim(),
        quantity: Math.max(1, Math.floor(num(r.querySelector('.mi-qty').value)) || 1),
        priceRaw: r.querySelector('.mi-price').value.trim(),
        price: num(r.querySelector('.mi-price').value),
        cost: (c === undefined || c === '') ? null : Number(c),
      };
    });
  }

  function updatePreview() {
    const items = readItems();
    const sale = items.reduce((a, i) => a + i.quantity * i.price, 0);
    const missing = items.some(i => i.sku && i.cost === null);
    const cogs = items.reduce((a, i) => a + i.quantity * (i.cost || 0), 0);
    const commRaw = num($('mo-comm').value);
    const comm = $('mo-comm-mode').value === 'pct' ? sale * commRaw / 100 : commRaw;
    const cargo = num($('mo-cargo').value);
    const net = sale - cogs - comm - cargo;
    $('mo-p-sale').textContent = tl(sale);
    $('mo-p-cogs').textContent = missing ? 'eksik' : tl(cogs);
    $('mo-p-comm').textContent = tl(comm);
    $('mo-p-cargo').textContent = tl(cargo);
    const netEl = $('mo-p-net');
    netEl.textContent = missing ? '—' : tl(net);
    netEl.className = missing ? '' : (net > 0 ? 'lal-profit-pos' : (net < 0 ? 'lal-profit-neg' : ''));
  }

  function resetForm() {
    $('mo-channel').value = 'softhydra';
    $('mo-date').value = toLocalInput(Date.now());
    $('mo-ref').value = '';
    $('mo-customer').value = '';
    $('mo-status').value = 'Delivered';
    $('mo-notes').value = '';
    $('mo-comm').value = '';
    $('mo-comm-mode').value = 'tl';
    $('mo-cargo').value = '';
    $('mo-error').textContent = '';
    $('mo-items').innerHTML = '';
  }

  function openNew() {
    editingId = null;
    resetForm();
    $('mo-title').textContent = 'Manuel sipariş ekle';
    addItemRow();
    updatePreview();
    dlg.showModal();
  }

  async function openEdit(id) {
    try {
      const res = await fetch('/api/manual-orders/' + id);
      const o = await res.json();
      if (!res.ok) { alert(o.error || 'Sipariş okunamadı.'); return; }
      editingId = id;
      resetForm();
      $('mo-title').textContent = 'Manuel siparişi düzenle';
      $('mo-channel').value = o.marketplace;
      $('mo-date').value = toLocalInput(o.orderDate);
      $('mo-ref').value = o.orderRef || '';
      $('mo-customer').value = o.customer || '';
      $('mo-status').value = o.status;
      $('mo-notes').value = o.notes || '';
      $('mo-comm').value = o.commission || '';
      $('mo-cargo').value = o.cargoCost || '';
      (o.items || []).forEach(addItemRow);
      if (!(o.items || []).length) addItemRow();
      updatePreview();
      dlg.showModal();
    } catch (e) { alert('Beklenmeyen hata: ' + e.message); }
  }

  async function save() {
    const err = $('mo-error');
    err.textContent = '';
    const items = readItems();
    if (!items.length || items.some(i => !i.sku)) { err.textContent = 'Her satır için bir SKU seçin.'; return; }
    const payload = {
      channel: $('mo-channel').value,
      order_date: $('mo-date').value,
      order_ref: $('mo-ref').value,
      customer: $('mo-customer').value,
      status: $('mo-status').value,
      notes: $('mo-notes').value,
      cargo_cost: $('mo-cargo').value,
      items: items.map(i => ({ sku: i.sku, quantity: i.quantity, unit_price: i.priceRaw })),
    };
    if ($('mo-comm-mode').value === 'pct') payload.commission_rate = $('mo-comm').value;
    else payload.commission = $('mo-comm').value;

    const btn = $('mo-save');
    btn.disabled = true;
    try {
      const res = await fetch(editingId ? '/api/manual-orders/' + editingId : '/api/manual-orders', {
        method: editingId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) { err.textContent = data.error || 'Kaydedilemedi.'; return; }
      dlg.close();
      document.dispatchEvent(new CustomEvent('lal:data-refresh'));
    } catch (e) {
      err.textContent = 'Beklenmeyen hata: ' + e.message;
    } finally {
      btn.disabled = false;
    }
  }

  async function remove(id) {
    if (!confirm('Bu manuel sipariş silinsin mi?')) return;
    try {
      const res = await fetch('/api/manual-orders/' + id, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) { alert(data.error || 'Silinemedi.'); return; }
      document.dispatchEvent(new CustomEvent('lal:data-refresh'));
    } catch (e) { alert('Beklenmeyen hata: ' + e.message); }
  }

  $('mo-add-item').addEventListener('click', () => { addItemRow(); });
  $('mo-cancel').addEventListener('click', () => dlg.close());
  $('mo-save').addEventListener('click', save);
  ['mo-comm', 'mo-comm-mode', 'mo-cargo'].forEach(id => {
    $(id).addEventListener('input', updatePreview);
    $(id).addEventListener('change', updatePreview);
  });

  const itemsEl = $('mo-items');
  itemsEl.addEventListener('input', e => {
    const row = e.target.closest('.manual-item-row');
    if (!row) return;
    if (e.target.classList.contains('mi-sku')) {
      row.dataset.cost = '';
      applySku(row);
      clearTimeout(skuTimer);
      const q = e.target.value.trim();
      skuTimer = setTimeout(() => lookupSkus(q), 250);
    }
    refreshRowCost(row);
    updatePreview();
  });
  itemsEl.addEventListener('change', e => {
    const row = e.target.closest('.manual-item-row');
    if (row && e.target.classList.contains('mi-sku')) applySku(row);
  });
  itemsEl.addEventListener('click', e => {
    const del = e.target.closest('.mi-del');
    if (!del) return;
    del.closest('.manual-item-row').remove();
    if (!itemRows().length) addItemRow();
    updatePreview();
  });

  document.addEventListener('click', e => {
    if (e.target.closest('#manual-add-btn')) { openNew(); return; }
    const ed = e.target.closest('[data-manual-edit]');
    if (ed) { openEdit(ed.dataset.manualEdit); return; }
    const del = e.target.closest('[data-manual-delete]');
    if (del) remove(del.dataset.manualDelete);
  });
})();
