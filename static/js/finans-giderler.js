// =====================================================================
// FİNANS — Sabit Giderler formu ve tablosu
// Faz 7.1: dashboard.js'ten ayrıştırıldı, yalnızca Finans sayfasında yüklenir.
// shell.js'teki ortak yardımcılara bağımlıdır.
// =====================================================================
(function () {
  if (!document.getElementById('fe-tbody')) return; // bu sayfada değiliz

  const ICON_CHECK_SM = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;width:13px;height:13px;"><polyline points="20 6 9 17 4 12"/></svg>';

  function fmtMonthLabel(month) {
    const [y, mo] = month.split('-');
    return new Date(y, mo - 1, 1).toLocaleDateString('tr-TR', { month: 'long', year: 'numeric' });
  }

  function renderFixedExpensesTable(items) {
    const tbody = document.getElementById('fe-tbody');
    if (!items.length) {
      tbody.innerHTML = emptyStateRow(6, 'Henüz sabit gider girilmemiş.');
      return;
    }
    tbody.innerHTML = items.map(it => `
      <tr>
        <td>${fmtMonthLabel(it.month)}</td>
        <td>${it.label}</td>
        <td>${fmtTL(it.amount)}</td>
        <td>${it.vat_amount == null ? '—' : fmtTL(it.vat_amount)}</td>
        <td style="color:var(--text-muted);">${it.note || ''}</td>
        <td><button class="inline-save-btn fe-delete" data-id="${it.id}" style="background:none; color:var(--red); border-color:var(--red);">Sil</button></td>
      </tr>
    `).join('');

    tbody.querySelectorAll('.fe-delete').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('Bu sabit gider kalemini silmek istediğine emin misin?')) return;
        btn.disabled = true; btn.textContent = '…';
        try {
          await fetch(`/api/fixed-expenses/${btn.dataset.id}`, { method: 'DELETE' });
          await loadFixedExpenses();
          // Aylık Kâr Trendi grafiği bu sayfada değil (Gösterge Paneli'nde);
          // orada açıksa bir sonraki ziyarette güncel veriyle yeniden çekilir.
        } catch (e) {
          showError('Sabit gider silinemedi: ' + e.message);
          btn.disabled = false; btn.textContent = 'Sil';
        }
      });
    });
  }

  async function loadFixedExpenses() {
    safeDisplay('fe-loading', 'none');
    safeDisplay('fe-table-wrap', 'block');
      document.getElementById('fe-tbody').innerHTML = skeletonTableRows(6, 3, [14, 18, 14, 12, 26, 10]);
    try {
      const res = await fetch('/api/fixed-expenses');
      const data = await res.json();
      if (data.error) {
        showError(data.error);
        document.getElementById('fe-tbody').innerHTML = errorStateRow(6, data.error);
        return;
      }
      renderFixedExpensesTable(data.items || []);
    } catch (e) {
      showError('Sabit giderler alınamadı: ' + e.message);
      document.getElementById('fe-tbody').innerHTML = errorStateRow(6, e.message);
    }
  }

  onExist('fe-submit', 'click', async () => {
    const month = document.getElementById('fe-month').value;
    const label = document.getElementById('fe-label').value.trim();
    const amount = document.getElementById('fe-amount').value;
    const vatAmount = document.getElementById('fe-vat-amount').value;
    const note = document.getElementById('fe-note').value.trim();
    const msgEl = document.getElementById('fe-form-msg');

    if (!month || !label || !amount) {
      msgEl.classList.remove('is-hidden');
      msgEl.style.color = 'var(--red)';
      msgEl.textContent = 'Ay, kalem ve tutar alanları zorunlu.';
      return;
    }

    try {
      const res = await fetch('/api/fixed-expenses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ month, label, amount: parseFloat(amount), vat_amount: vatAmount === '' ? null : parseFloat(vatAmount), note: note || undefined }),
      });
      const data = await res.json();
      msgEl.classList.remove('is-hidden');
      if (data.error) {
        msgEl.style.color = 'var(--red)';
        msgEl.textContent = data.error;
      } else {
        msgEl.style.color = 'var(--green)';
        msgEl.innerHTML = `${ICON_CHECK_SM}<span style="vertical-align:middle; margin-left:5px;">"${label}" kaydedildi.</span>`;
        document.getElementById('fe-label').value = '';
        document.getElementById('fe-amount').value = '';
        document.getElementById('fe-vat-amount').value = '';
        document.getElementById('fe-note').value = '';
        await loadFixedExpenses();
      }
    } catch (e) {
      msgEl.classList.remove('is-hidden');
      msgEl.style.color = 'var(--red)';
      msgEl.textContent = 'Kaydetme hatası: ' + e.message;
    }
  });

  // Ay seçiciye varsayılan olarak içinde bulunulan ayı koy.
  (function setDefaultFeMonth() {
    const feMonth = document.getElementById('fe-month');
    if (!feMonth) return;
    const now = new Date();
    feMonth.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  })();

  const vatLabels = { sale: 'Satış', cost: 'Ürün maliyeti', commission: 'Komisyon', service: 'Hizmet bedeli', cargo: 'Kargo', advertising: 'Reklam', manual_expense: 'Elle gider' };
  const vatRateOptions = (rate) => [0, 0.1, 0.2].map(v => `<option value="${v}" ${Number(rate) === v ? 'selected' : ''}>%${Math.round(v * 100)}</option>`).join('');
  async function saveVatRow(row) {
    const res = await fetch('/api/vat-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(row) });
    const data = await res.json(); if (data.error) throw new Error(data.error);
  }
  async function loadVatSettings() {
    const res = await fetch('/api/vat-settings'); const data = await res.json();
    const body = document.getElementById('vat-settings-tbody'); if (!body) return;
    body.innerHTML = (data.items || []).map(it => `<tr><td>${vatLabels[it.setting_key] || it.setting_key}</td><td><select data-vat-key="${it.setting_key}" data-field="vat_included"><option value="1" ${it.vat_included ? 'selected' : ''}>Dâhil</option><option value="0" ${!it.vat_included ? 'selected' : ''}>Hariç</option></select></td><td><select data-vat-key="${it.setting_key}" data-field="vat_rate">${vatRateOptions(it.vat_rate)}</select></td></tr>`).join('');
    body.querySelectorAll('select').forEach(el => el.addEventListener('change', async () => {
      const row = body.querySelectorAll(`[data-vat-key="${el.dataset.vatKey}"]`);
      const values = Object.fromEntries([...row].map(x => [x.dataset.field, x.value]));
      try { await saveVatRow({ setting_key: el.dataset.vatKey, vat_included: values.vat_included === '1', vat_rate: Number(values.vat_rate) }); }
      catch (e) { showError('KDV ayarı kaydedilemedi: ' + e.message); }
    }));
  }
  const expenseGroups = [
    ['business', 'İşletme gideri'],
    ['tax', 'Prim (Bağ-Kur)'],
    ['income_tax_prepayment', 'Gelir vergisi ön ödemesi'],
    ['vat_cash', 'KDV ödemesi (nakit, kâr dışı)'],
  ];
  const expenseGroupOptions = (g) => expenseGroups.map(([k, l]) => `<option value="${k}" ${g === k ? 'selected' : ''}>${l}</option>`).join('');
  async function loadFinanceSettings() {
    const input = document.getElementById('income-tax-rate'); if (!input) return;
    const res = await fetch('/api/finance-settings'); const data = await res.json();
    input.value = Math.round((data.settings.income_tax_provision_rate || 0) * 1000) / 10;
    input.addEventListener('change', async () => {
      try {
        const r = await fetch('/api/finance-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ income_tax_provision_rate: Number(input.value) / 100 }) });
        const d = await r.json(); if (d.error) throw new Error(d.error);
      } catch (e) { showError('Karşılık oranı kaydedilemedi: ' + e.message); }
    });
  }
  async function loadExpenseTypes() {
    const res = await fetch('/api/expense-type-settings'); const data = await res.json();
    const body = document.getElementById('expense-types-tbody'); if (!body) return;
    body.innerHTML = (data.items || []).map(it => `<tr data-type-key="${it.type_key}"><td><strong>${it.display_name}</strong><br><small>${it.aliases || ''}</small></td><td><select data-field="group_name">${expenseGroupOptions(it.group_name)}</select></td><td><select data-field="vat_included"><option value="1" ${it.vat_included ? 'selected' : ''}>Dâhil</option><option value="0" ${!it.vat_included ? 'selected' : ''}>Hariç</option></select></td><td><select data-field="vat_rate">${vatRateOptions(it.vat_rate)}</select></td><td><input type="text" data-field="alias" placeholder="Yeni yazım (isteğe bağlı)"><button type="button" class="inline-save-btn expense-type-save">Kaydet</button></td></tr>`).join('');
    body.querySelectorAll('.expense-type-save').forEach(btn => btn.addEventListener('click', async () => {
      const tr = btn.closest('tr'); const vals = Object.fromEntries([...tr.querySelectorAll('[data-field]')].map(x => [x.dataset.field, x.value]));
      try { const r = await fetch('/api/expense-type-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type_key: tr.dataset.typeKey, group_name: vals.group_name, vat_included: vals.vat_included === '1', vat_rate: Number(vals.vat_rate), alias: vals.alias || undefined }) }); const d = await r.json(); if (d.error) throw new Error(d.error); await loadExpenseTypes(); }
      catch (e) { showError('Gider türü kaydedilemedi: ' + e.message); }
    }));
  }
  if (document.getElementById('vat-settings-tbody')) loadVatSettings();
  if (document.getElementById('expense-types-tbody')) loadExpenseTypes();
  loadFinanceSettings();

  // ---------- Başlangıç ----------
  loadFixedExpenses();
})();
