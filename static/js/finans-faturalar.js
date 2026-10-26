(function () {
  const tbody = document.getElementById('inv-tbody');
  if (!tbody) return;
  const $ = id => document.getElementById(id);
  const money = value => new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY' }).format(Number(value || 0));
  const escapeHtml = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const now = new Date();
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  $('inv-month').value = currentMonth;
  $('inv-date').value = now.toISOString().slice(0, 10);

  function showMessage(id, message, error) {
    const el = $(id);
    el.textContent = message || '';
    el.classList.toggle('is-hidden', !message);
    el.classList.toggle('is-error', !!error);
  }

  async function load() {
    tbody.innerHTML = '<tr><td colspan="5">Yükleniyor…</td></tr>';
    const response = await fetch(`/api/invoice-planning?month=${encodeURIComponent($('inv-month').value)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Fatura ihtiyacı yüklenemedi.');
    $('inv-target').value = Number(data.target_profit || 0).toFixed(2);
    const warning = data.warning || '';
    showMessage('inv-warning', warning, false);
    if (warning) $('inv-warning').classList.add('is-warning');
    else $('inv-warning').classList.remove('is-warning');
    const invoices = data.invoices || [];
    tbody.innerHTML = invoices.length ? invoices.map(item => `<tr>
      <td>${escapeHtml(item.invoice_date)}</td><td>${escapeHtml(item.description)}</td>
      <td>${money(item.amount_ex_vat)}</td><td>${money(item.vat_amount)}</td>
      <td><button class="lal-btn inv-delete" data-id="${Number(item.id)}">Sil</button></td></tr>`).join('')
      : '<tr><td colspan="5">Bu ay için fatura kaydı yok.</td></tr>';
    $('inv-summary').innerHTML = `<p><strong>Faaliyet kârı:</strong> ${money(data.operating_profit)}</p>
      <p><strong>Girilen faturalar (KDV hariç):</strong> ${money(data.invoice_total_ex_vat)}</p>
      <p><strong>Hedef kâr:</strong> ${money(data.target_profit)}</p>
      <p><strong>Kalan fatura ihtiyacı:</strong> ${money(data.remaining_invoice_need)}</p>
      <p class="panel-note">Kâr durumu: ${escapeHtml(data.profit_status || 'Tahmini')}</p>`;
    tbody.querySelectorAll('.inv-delete').forEach(button => button.addEventListener('click', async () => {
      if (!window.confirm('Bu fatura kaydı silinsin mi?')) return;
      const response = await fetch(`/api/invoices/${button.dataset.id}`, { method: 'DELETE' });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Fatura silinemedi.');
      await load();
    }));
  }

  $('inv-month').addEventListener('change', () => load().catch(error => showMessage('inv-msg', error.message, true)));
  $('inv-date').addEventListener('change', () => {
    const selected = $('inv-date').value.slice(0, 7);
    if (selected && selected !== $('inv-month').value) {
      $('inv-month').value = selected;
      load().catch(error => showMessage('inv-msg', error.message, true));
    }
  });
  $('inv-target-save').addEventListener('click', async () => {
    try {
      const response = await fetch('/api/invoice-target', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ month: $('inv-month').value, target_profit: $('inv-target').value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Hedef kaydedilemedi.');
      showMessage('inv-msg', 'Hedef kâr kaydedildi.', false);
      await load();
    } catch (error) { showMessage('inv-msg', error.message, true); }
  });
  $('inv-submit').addEventListener('click', async () => {
    try {
      const response = await fetch('/api/invoices', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: $('inv-date').value, description: $('inv-description').value,
          amount_ex_vat: $('inv-amount').value, vat_amount: $('inv-vat').value })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Fatura kaydedilemedi.');
      $('inv-description').value = '';
      $('inv-amount').value = '';
      $('inv-vat').value = '';
      showMessage('inv-msg', 'Fatura kaydedildi.', false);
      await load();
    } catch (error) { showMessage('inv-msg', error.message, true); }
  });
  load().catch(error => showMessage('inv-msg', error.message, true));
})();
