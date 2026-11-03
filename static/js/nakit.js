// static/js/nakit.js — Nakit sayfası (Faz 1 / Aşama 2). Backend: blueprints/cash_routes.py,
// supplier_routes.py (/api/tedarikciler/<id>/...). shell.js'teki fmtTL / esc kullanılır.
(function () {
  const WATALINA_ID = 4;
  const tl2 = (n) => (n === null || n === undefined) ? '—' : (Number(n) < 0 ? '−₺' : '₺') + Math.abs(Number(n)).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const dTR = (iso) => iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4) : '—';
  const pct = (r) => r === null || r === undefined ? '—' : '%' + (r * 100).toFixed(1).replace('.', ',');
  const $ = (id) => document.getElementById(id);
  const msg = (t, err) => { const el = $('nk-msg'); el.textContent = t; el.classList.remove('is-hidden'); el.style.color = err ? 'var(--lal-red)' : 'var(--lal-green)'; setTimeout(() => el.classList.add('is-hidden'), 4000); };
  async function api(url, body) {
    const res = await fetch(url, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined);
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || res.statusText);
    return data;
  }
  const stat = (label, value, warn) => `<div class="nk-stat${warn ? ' is-warn' : ''}"><span>${esc(label)}</span><strong>${value}</strong></div>`;

  // sekmeler
  document.querySelectorAll('#nakit-tabs .lal-tab').forEach(tab => tab.addEventListener('click', () => {
    document.querySelectorAll('#nakit-tabs .lal-tab').forEach(t => t.classList.remove('is-active'));
    document.querySelectorAll('.lal-tab-panel').forEach(p => p.classList.remove('is-active'));
    tab.classList.add('is-active');
    $(tab.dataset.tab).classList.add('is-active');
  }));

  // ---------------- 13 hafta
  async function loadForecast() {
    const only = $('nk-only-certain').checked;
    let f;
    try { f = await api('/api/nakit/akis' + (only ? '?yalnizca_kesin=1' : '')); }
    catch (e) { $('nk-akis-note').textContent = 'Hesaplanamadı: ' + e.message; return; }
    const below = f.haftalar.filter(w => w.rezervAlti);
    const minW = f.haftalar.reduce((a, w) => (w.bakiye < a.bakiye ? w : a), f.haftalar[0]);
    $('nk-akis-note').textContent = `${dTR(f.haftalar[0].baslangic)} – ${dTR(f.haftalar[f.haftalar.length - 1].bitis)}. Başlangıç = serbest nakit (borca ayrılmış ${tl2(f.borcaAyrilmis)} hariç).`;
    $('nk-summary').innerHTML = stat('Başlangıç (serbest nakit)', tl2(f.baslangicBakiyesi))
      + stat('Minimum nakit rezervi', tl2(f.rezerv))
      + stat('En düşük bakiye', `${tl2(minW.bakiye)} <small>(${minW.hafta}. hafta)</small>`, minW.bakiye < f.rezerv)
      + stat('Rezerv altı hafta', String(below.length), below.length > 0)
      + stat('13. hafta sonu', tl2(f.haftalar[f.haftalar.length - 1].bakiye), f.haftalar[f.haftalar.length - 1].rezervAlti);
    const body = $('nk-weeks');
    body.innerHTML = f.haftalar.map(w => `
      <tr class="nk-week${w.rezervAlti ? ' is-below' : ''}" data-w="${w.hafta}">
        <td>${w.hafta}. hafta<small>${dTR(w.baslangic)} – ${dTR(w.bitis)}</small></td>
        <td>${tl2(w.giris)}${w.girisTahmini ? `<small class="nk-est">${tl2(w.girisTahmini)} tahmini</small>` : ''}</td>
        <td>${tl2(w.cikis)}${w.cikisTahmini ? `<small class="nk-est">${tl2(w.cikisTahmini)} tahmini</small>` : ''}</td>
        <td>${tl2(w.net)}</td>
        <td class="nk-bal">${tl2(w.bakiye)}</td>
      </tr>
      <tr class="nk-detail" data-d="${w.hafta}" hidden><td colspan="5"><ul>${w.kalemler.map(i => `
        <li class="${i.tahmini ? 'is-est' : ''}">${dTR(i.tarih)} · ${i.yon === 'giris' ? '+' : '−'}${tl2(i.tutar)} · ${esc(i.kalem)}${i.tahmini ? '<span class="nk-tag">tahmini</span>' : ''}${i.aciklama ? ` <small>${esc(i.aciklama)}</small>` : ''}</li>`).join('') || '<li>Kalem yok</li>'}</ul></td></tr>`).join('');
    body.querySelectorAll('tr.nk-week').forEach(tr => tr.addEventListener('click', () => {
      const d = body.querySelector(`tr[data-d="${tr.dataset.w}"]`); d.hidden = !d.hidden;
    }));
    const g = f.girdiler || {};
    const mp = (o, fmt) => Object.entries(o || {}).map(([k, v]) => `${k}: ${fmt(v)}`).join(' · ') || '—';
    $('nk-inputs').innerHTML = `<dl>
      <dt>Haftalık satış tahmini</dt><dd>${mp(g.weeklySales, tl2)} (son 8 haftanın %90'ı, KDV dahil)</dd>
      <dt>Hakediş / satış oranı</dt><dd>${mp(g.payoutRatio, pct)} (son 3 ay)</dd>
      <dt>Sipariş → ödeme gecikmesi</dt><dd>${mp(g.lagDays, v => v + ' gün')}</dd>
      <dt>Watalina maliyet / satış</dt><dd>${pct(g.cogsRatio)} (son 3 ay, KDV dahil)</dd>
      <dt>TY reklam kesintisi</dt><dd>${tl2((g.tyAdsDaily || 0) * 7)} / hafta</dd>
      <dt>TY kargo/platform kesintisi</dt><dd>${tl2((g.tyOtherDeductionsDaily || 0) * 7)} / hafta</dd>
      <dt>Gecikmiş tahmini (dahil değil)</dt><dd>${tl2(f.gecikmisTahminiHaricTutulan)}</dd></dl>`;
  }
  $('nk-only-certain').addEventListener('change', loadForecast);

  // ---------------- hesaplar
  const turLabel = { banka: 'Banka', odeme_altyapisi: 'Ödeme altyapısı', altin: 'Altın', kasa: 'Kasa' };
  async function loadAccounts() {
    const d = await api('/api/nakit/hesaplar');
    $('nk-free-cash').textContent = tl2(d.serbestNakit);
    $('nk-accounts').innerHTML = d.items.map(a => `<tr>
      <td><strong>${esc(a.ad)}</strong>${a.borca_ayrilmis ? '<small>borca ayrılmış</small>' : ''}</td>
      <td>${turLabel[a.tur] || a.tur}</td>
      <td>${tl2(a.bakiye)}${a.tur === 'altin' && a.altin_adet ? `<small>${a.altin_adet} × ${tl2(a.birim_fiyat)}${a.birim_maliyet ? ' · maliyet ' + tl2(a.birim_maliyet) : ''}</small>` : ''}</td>
      <td>${dTR(a.bakiye_tarihi)}</td>
      <td class="nk-wrap">${esc(a.notlar || '')}</td>
      <td><div class="nk-inline">${a.tur === 'altin'
        ? `<input type="number" step="0.01" placeholder="adet" data-f="altin_adet"><input type="number" step="0.01" placeholder="birim fiyat" data-f="birim_fiyat">`
        : `<input type="number" step="0.01" placeholder="bakiye" data-f="bakiye">`}
        <button class="lal-btn" data-acc="${a.id}">Kaydet</button></div></td></tr>`).join('');
    $('nk-accounts').querySelectorAll('button[data-acc]').forEach(b => b.addEventListener('click', async () => {
      const vals = {}; b.parentElement.querySelectorAll('input').forEach(i => { if (i.value !== '') vals[i.dataset.f] = Number(i.value); });
      try { await api(`/api/nakit/hesaplar/${b.dataset.acc}/bakiye`, vals); msg('Bakiye kaydedildi'); loadAccounts(); loadForecast(); }
      catch (e) { msg(e.message, true); }
    }));
  }
  async function loadReserve() {
    const d = await api('/api/finance-settings');
    $('nk-reserve').value = d.settings.min_cash_reserve || 0;
  }
  $('nk-reserve').addEventListener('change', async () => {
    try { await api('/api/finance-settings', { min_cash_reserve: Number($('nk-reserve').value) }); msg('Rezerv kaydedildi'); loadForecast(); }
    catch (e) { msg(e.message, true); }
  });

  // ---------------- kartlar
  async function loadCards() {
    const d = await api('/api/nakit/kartlar');
    $('nk-cards').innerHTML = d.items.map(c => `<div class="panel">
      <div class="panel-header-row"><h2>${esc(c.ad)}</h2>${c.uyari ? '<span class="nk-tag" style="background:var(--lal-red-dim);color:var(--lal-red)">%80 üstü</span>' : ''}</div>
      <div class="nk-card-meter${c.uyari ? ' is-warn' : ''}"><i style="width:${Math.min(100, (c.dolulukOrani || 0) * 100).toFixed(1)}%"></i></div>
      <div class="nk-summary">${stat('Kullanılan', tl2(c.kullanilan), c.uyari)}${stat('Limit', tl2(c.limit_tutar))}${stat('Kullanılabilir', tl2(c.kullanilabilir))}${stat('Doluluk', pct(c.dolulukOrani), c.uyari)}</div>
      <p class="panel-note">Hesap kesimi her ayın ${c.kesim_gunu}'i, son ödeme ${c.son_odeme_gunu}'i. ${c.guncel_borc !== null ? `Güncel borç ${dTR(c.guncel_borc_tarihi)} itibarıyla girildi.` : 'Güncel borç girilmedi; ödenmemiş ekstre + kalan taksit kullanılıyor.'}</p>
      <div class="nk-inline lal-mb-4"><input type="number" step="0.01" placeholder="güncel borç" data-debt="${c.id}"><button class="lal-btn" data-debt-save="${c.id}">Güncel borcu kaydet</button></div>
      <h3>Ödenmemiş ekstreler</h3>
      <div class="table-scroll"><table class="nk-table"><tbody>${c.odenmemisEkstreler.map(s => `<tr><td>${esc(s.donem)}</td><td>${tl2(s.tutar)}</td><td>son ödeme ${dTR(s.son_odeme_tarihi)}</td><td><button class="lal-btn" data-st="${s.id}">Ödendi</button></td></tr>`).join('') || '<tr><td>Yok</td></tr>'}</tbody></table></div>
      <h3 class="lal-mt-3">Taksitler</h3>
      <div class="table-scroll"><table class="nk-table"><tbody>${c.taksitPlanlari.map(p => `<tr><td class="nk-wrap">${esc(p.aciklama)}${p.sku ? `<small>${esc(p.sku)}</small>` : ''}</td><td>${tl2(p.taksit_tutari)} × ${p.kalan_taksit}/${p.toplam_taksit}</td><td>kalan ${tl2(p.kalanTutar)}</td><td>sıradaki ${dTR(p.sonrakiTarih)}</td><td><button class="lal-btn" data-inst="${p.id}">Taksit ödendi</button></td></tr>`).join('') || '<tr><td>Yok</td></tr>'}</tbody></table></div>
      <h3 class="lal-mt-3">Yeni ekstre</h3>
      <div class="nk-inline"><input type="month" data-sd="${c.id}"><input type="number" step="0.01" placeholder="tutar" data-sa="${c.id}"><input type="date" data-sdue="${c.id}"><button class="lal-btn" data-sadd="${c.id}">Ekle</button></div>
    </div>`).join('');
    const box = $('nk-cards');
    const after = () => { loadCards(); loadForecast(); };
    box.querySelectorAll('[data-debt-save]').forEach(b => b.addEventListener('click', async () => {
      const v = box.querySelector(`[data-debt="${b.dataset.debtSave}"]`).value;
      try { await api(`/api/nakit/kartlar/${b.dataset.debtSave}/borc`, { guncel_borc: Number(v) }); msg('Kaydedildi'); after(); } catch (e) { msg(e.message, true); }
    }));
    box.querySelectorAll('[data-st]').forEach(b => b.addEventListener('click', async () => {
      try { await api(`/api/nakit/ekstre/${b.dataset.st}/odendi`, {}); msg('Ekstre ödendi'); after(); } catch (e) { msg(e.message, true); }
    }));
    box.querySelectorAll('[data-inst]').forEach(b => b.addEventListener('click', async () => {
      try { await api(`/api/nakit/taksit/${b.dataset.inst}/odendi`, {}); msg('Taksit ödendi'); after(); } catch (e) { msg(e.message, true); }
    }));
    box.querySelectorAll('[data-sadd]').forEach(b => b.addEventListener('click', async () => {
      const id = b.dataset.sadd;
      try {
        await api(`/api/nakit/kartlar/${id}/ekstre`, { donem: box.querySelector(`[data-sd="${id}"]`).value, tutar: Number(box.querySelector(`[data-sa="${id}"]`).value), son_odeme_tarihi: box.querySelector(`[data-sdue="${id}"]`).value });
        msg('Ekstre eklendi'); after();
      } catch (e) { msg(e.message, true); }
    }));
  }

  // ---------------- Watalina
  const tipLabel = { acilis: 'Açılış', alis: 'Alış', iade: 'İptal/iade', odeme: 'Ödeme', duzeltme: 'Düzeltme', satis: 'Alış' };
  async function loadSupplier() {
    const d = await api(`/api/tedarikciler/${WATALINA_ID}/ozet`);
    const v = d.vade;
    $('nk-sup-buckets').innerHTML = stat('Cari bakiye', tl2(d.bakiye)) + stat('Vadesi geçmiş', tl2(v.vadesiGecmis), v.vadesiGecmis > 0)
      + stat('Bu ay', tl2(v.buAy)) + stat('Gelecek ay', tl2(v.gelecekAy)) + stat('Sonrası', tl2(v.sonrasi));
    $('nk-sup-rec').innerHTML = d.mutabakat.map(r => `<tr>
      <td>${r.ay}</td><td>${tl2(r.sistem)}</td>
      <td><div class="nk-inline"><input type="number" step="0.01" value="${r.fatura ?? ''}" data-inv="${r.ay}"><button class="lal-btn" data-inv-save="${r.ay}">Kaydet</button></div></td>
      <td>${r.fark === null ? '—' : tl2(r.fark)}</td>
      <td><div class="nk-inline"><input type="date" data-due="${r.ay}"><button class="lal-btn" data-due-save="${r.ay}">Vadeyi değiştir</button></div></td></tr>`).join('') || '<tr><td colspan="5">Henüz otomatik alış yok.</td></tr>';
    $('nk-sup-moves').innerHTML = d.hareketler.map(m => `<tr>
      <td>${dTR(m.islem_tarihi || (m.tarih || '').slice(0, 10))}</td><td>${tipLabel[m.tip] || m.tip}</td>
      <td>${m.tip === 'odeme' ? '−' : ''}${tl2(m.tutar)}</td>
      <td>${m.tip === 'odeme' ? '—' : `<div class="nk-inline"><input type="date" value="${m.vade_tarihi || ''}" data-mv="${m.id}"></div>`}</td>
      <td class="nk-wrap">${esc(m.aciklama || '')}</td></tr>`).join('');
    const box = $('nk-tedarikci');
    box.querySelectorAll('[data-inv-save]').forEach(b => b.addEventListener('click', async () => {
      try { await api(`/api/tedarikciler/${WATALINA_ID}/fatura`, { ay: b.dataset.invSave, tutar: Number(box.querySelector(`[data-inv="${b.dataset.invSave}"]`).value) }); msg('Fatura kaydedildi'); loadSupplier(); }
      catch (e) { msg(e.message, true); }
    }));
    box.querySelectorAll('[data-due-save]').forEach(b => b.addEventListener('click', async () => {
      try { await api(`/api/tedarikciler/${WATALINA_ID}/ay-vade`, { ay: b.dataset.dueSave, vade_tarihi: box.querySelector(`[data-due="${b.dataset.dueSave}"]`).value }); msg('Vade güncellendi'); loadSupplier(); loadForecast(); }
      catch (e) { msg(e.message, true); }
    }));
    box.querySelectorAll('[data-mv]').forEach(i => i.addEventListener('change', async () => {
      try { await api(`/api/tedarikciler/hareket/${i.dataset.mv}/vade`, { vade_tarihi: i.value }); msg('Vade güncellendi'); loadSupplier(); loadForecast(); }
      catch (e) { msg(e.message, true); }
    }));
  }
  $('nk-pay-date').value = new Date().toISOString().slice(0, 10);
  $('nk-pay-add').addEventListener('click', async () => {
    try {
      await api(`/api/tedarikciler/${WATALINA_ID}/odeme`, { tarih: $('nk-pay-date').value, tutar: Number($('nk-pay-amount').value), aciklama: $('nk-pay-note').value });
      msg('Ödeme eklendi'); $('nk-pay-amount').value = ''; loadSupplier(); loadForecast();
    } catch (e) { msg(e.message, true); }
  });

  // ---------------- planlı ödemeler
  const catLabel = { vergi_sgk: 'Vergi / SGK', borc_aile: 'Aile borcu', kart: 'Kart', tedarikci: 'Tedarikçi', sahsi_cekis: 'Şahsi çekiş', diger: 'Diğer' };
  async function loadScheduled() {
    const d = await api('/api/nakit/planli');
    $('nk-scheduled').innerHTML = d.items.map(p => {
      const next = p.siradakiler[0];
      return `<tr><td class="nk-wrap"><strong>${esc(p.aciklama)}</strong></td><td>${catLabel[p.kategori] || p.kategori}</td><td>${tl2(p.tutar)}</td>
        <td>${p.tekrar === 'aylik' ? (p.ay_sonu ? 'Aylık, ay sonu' : `Aylık, ${Number(p.baslangic_tarihi.slice(8, 10))}'i`) : 'Tek sefer'}${p.bitis_tarihi ? `<small>bitiş ${dTR(p.bitis_tarihi)}</small>` : ''}</td>
        <td>${next ? dTR(next.tarih) + (next.tarih !== next.plan ? `<small>planlanan ${dTR(next.plan)}</small>` : '') : '—'}</td>
        <td class="nk-wrap"><small>${esc(p.notlar || '')}</small></td>
        <td>${next ? `<div class="nk-inline"><button class="lal-btn" data-paid="${p.id}" data-plan="${next.plan}">Ödendi</button><input type="date" data-post="${p.id}"><button class="lal-btn" data-post-save="${p.id}" data-plan="${next.plan}">Ertele</button></div>` : ''}</td></tr>`;
    }).join('') || '<tr><td colspan="7">Planlı ödeme yok.</td></tr>';
    const box = $('nk-scheduled');
    box.querySelectorAll('[data-paid]').forEach(b => b.addEventListener('click', async () => {
      try { await api(`/api/nakit/planli/${b.dataset.paid}/olay`, { plan_tarihi: b.dataset.plan, durum: 'odendi' }); msg('Ödendi işaretlendi'); loadScheduled(); loadForecast(); }
      catch (e) { msg(e.message, true); }
    }));
    box.querySelectorAll('[data-post-save]').forEach(b => b.addEventListener('click', async () => {
      const v = box.querySelector(`[data-post="${b.dataset.postSave}"]`).value;
      try { await api(`/api/nakit/planli/${b.dataset.postSave}/olay`, { plan_tarihi: b.dataset.plan, durum: 'ertelendi', yeni_tarih: v }); msg('Ertelendi'); loadScheduled(); loadForecast(); }
      catch (e) { msg(e.message, true); }
    }));
  }
  $('nk-sp-add').addEventListener('click', async () => {
    try {
      await api('/api/nakit/planli', { aciklama: $('nk-sp-desc').value, kategori: $('nk-sp-cat').value, tutar: Number($('nk-sp-amount').value), baslangic_tarihi: $('nk-sp-date').value, tekrar: $('nk-sp-rep').value, bitis_tarihi: $('nk-sp-end').value || null });
      msg('Planlı ödeme eklendi'); loadScheduled(); loadForecast();
    } catch (e) { msg(e.message, true); }
  });

  loadForecast(); loadAccounts(); loadReserve(); loadCards(); loadSupplier(); loadScheduled();
})();
