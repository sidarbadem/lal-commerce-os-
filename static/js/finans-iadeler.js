(function () {
  const tbody = document.getElementById('ret-tbody');
  if (!tbody) return;
  const escapeHtml = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const labels = { sellable: 'Satılabilir', damaged: 'Hasarlı', lost: 'Kayıp' };
  const monthInput = document.getElementById('ret-month');
  const now = new Date();
  monthInput.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

  async function loadReturns() {
    tbody.innerHTML = '<tr><td colspan="7">Yükleniyor…</td></tr>';
    const response = await fetch(`/api/returns?month=${encodeURIComponent(monthInput.value)}`);
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || 'İadeler yüklenemedi.');
    if (!(data.items || []).length) {
      tbody.innerHTML = '<tr><td colspan="7">Bu ay için iade kaydı yok.</td></tr>';
      return;
    }
    tbody.innerHTML = data.items.map(item => {
      const date = new Date(Number(item.transaction_date)).toLocaleDateString('tr-TR');
      return `<tr>
        <td>${escapeHtml(date)}</td><td>${escapeHtml(item.marketplace)}</td>
        <td>${escapeHtml(item.order_number || '—')}</td><td>${escapeHtml(item.barcode || '—')}</td>
        <td>${fmtTL(item.amount)}</td>
        <td title="${escapeHtml(item.match_reason || item.match_method || '')}">${escapeHtml(item.match_status || '—')}${item.match_reason ? `: ${escapeHtml(item.match_reason)}` : ''}</td>
        <td><select class="ret-condition" data-marketplace="${escapeHtml(item.marketplace)}" data-id="${escapeHtml(item.id)}">
          ${Object.entries(labels).map(([key, label]) => `<option value="${key}" ${item.condition === key ? 'selected' : ''}>${label}</option>`).join('')}
        </select></td>
      </tr>`;
    }).join('');
    tbody.querySelectorAll('.ret-condition').forEach(select => select.addEventListener('change', async () => {
      select.disabled = true;
      try {
        const response = await fetch('/api/returns', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ marketplace: select.dataset.marketplace, settlement_id: select.dataset.id, condition: select.value })
        });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || 'Durum kaydedilemedi.');
      } catch (error) {
        alert('İade durumu kaydedilemedi: ' + error.message);
        await loadReturns();
      } finally {
        select.disabled = false;
      }
    }));
  }

  document.getElementById('ret-refresh').addEventListener('click', () => loadReturns().catch(e => {
    tbody.innerHTML = `<tr><td colspan="7">${escapeHtml(e.message)}</td></tr>`;
  }));
  loadReturns().catch(e => { tbody.innerHTML = `<tr><td colspan="7">${escapeHtml(e.message)}</td></tr>`; });
})();
