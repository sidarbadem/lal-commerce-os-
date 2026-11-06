// =====================================================================
// SİPARİŞLER — Sipariş listesi, arama, durum filtresi, sayfalama
// Faz 7.1: dashboard.js'ten ayrıştırıldı, yalnızca bu sayfada yüklenir.
// shell.js'teki ortak yardımcılara bağımlıdır.
// =====================================================================
(function () {
  if (!document.getElementById('orders-table-wrap')) return; // bu sayfada değiliz

  let currentPage = 1;
  const PAGE_SIZE = 50;
  const ORDER_COLUMN_COUNT = 10; // ▸, Ürün·Tarih, Kanal, Durum, Satış, Komisyon, Kargo, Maliyet, Net Kâr, Marj
  // 02.11.2026: kâr filtresi + sıralama SUNUCUDA (sayfalamadan önce) yapılıyor.
  let profitFilter = '';
  let sortKey = 'date';
  let sortDir = 'desc';

  function marketplaceBadge(marketplace) {
    // Faz 8.4: eskiden burada legacy .mp-badge/.mp-trendyol/.mp-hepsiburada
    // (ham hex renkli, legacy.css) kullanılıyordu — ama components.css'te
    // aynı işi gören, token'lara bağlı .lal-badge-mp-trendyol/hepsiburada
    // zaten Faz 2'den beri tanımlıydı ve hiç kullanılmıyordu. İki paralel
    // sistem oluşmuştu; burada LDL'nin kendi component'ine geçildi.
    const key = (marketplace || '').toLowerCase();
    if (key === 'trendyol') return '<span class="lal-badge lal-badge-mp-trendyol">Trendyol</span>';
    if (key === 'hepsiburada') return '<span class="lal-badge lal-badge-mp-hepsiburada">Hepsiburada</span>';
    const manualLabels = { softhydra: 'softhydra.com', n11: 'n11', amazon: 'Amazon' };
    if (manualLabels[key]) return `<span class="lal-badge lal-badge-soon">${manualLabels[key]}</span>`;
    return `<span class="lal-badge lal-badge-soon">${marketplace || '—'}</span>`;
  }

  function statusPill(status) {
    // Pazaryeri ham durumları Türkçe etiket + tek renk ailesine çevrilir;
    // ham değer title'da kalır (destekle konuşurken lazım olabilir).
    const map = {
      Created: ['pill-new', 'Yeni'],
      Open: ['pill-new', 'Yeni'],
      AwaitingPackage: ['pill-new', 'Paket bekliyor'],
      Picking: ['pill-prep', 'Hazırlanıyor'],
      Invoiced: ['pill-prep', 'Faturalandı'],
      Packaged: ['pill-prep', 'Paketlendi'],
      ReadyToShip: ['pill-prep', 'Kargoya hazır'],
      Shipped: ['pill-transit', 'Kargoda'],
      InTransit: ['pill-transit', 'Yolda'],
      AtCollectionPoint: ['pill-transit', 'Teslim noktasında'],
      Delivered: ['pill-delivered', 'Teslim edildi'],
      'Teslim Edildi': ['pill-delivered', 'Teslim edildi'],
      UnDelivered: ['pill-cancelled', 'Teslim edilemedi'],
      Cancelled: ['pill-cancelled', 'İptal'],
      CancelledByCustomer: ['pill-cancelled', 'Müşteri iptali'],
      CancelledBySeller: ['pill-cancelled', 'Satıcı iptali'],
      UnSupplied: ['pill-cancelled', 'Karşılanamadı'],
      ClaimCreated: ['pill-claim', 'İade talebi'],
      Returned: ['pill-claim', 'İade'],
    };
    const [cls, label] = map[status] || ['pill-other', status || '—'];
    return `<span class="pill ${cls}" title="${escHtml(status || '')}">${label}</span>`;
  }

  // DÜZELTME (09.08.2026): sipariş bazlı Net Kâr hücresi.
  // - netProfit null ise (ör. ürün maliyeti tanımlı değil) '—' gösterilir,
  //   sessizce 0 gibi davranıp yanıltmaz (bkz. order_routes.py profitMissingCost).
  // - profitEstimated true ise (gerçek settlement henüz oluşmamış, tahmini
  //   komisyonla hesaplanmış) rakamın yanına '~' ön eki ve bir tooltip eklenir —
  //   dashboard'daki "tahmini komisyonla hesaplandı" uyarısıyla tutarlı.
  // - cargoEstimated true ise (27.09.2026, Sidar onayıyla): kargo faturası
  //   henüz Trendyol/HB'den gelmemiş, finance_engine.py'nin SKU bazlı geçmiş
  //   ortalamasıyla (ya da hiç geçmiş yoksa sabit tahminle) hesaplanmış demektir
  //   — bu da '~' ön ekini tetikler. profitEstimated VE cargoEstimated aynı anda
  //   true olabilir; tooltip ikisini de tek tek belirtir.
  function estimateReasons(o) {
    const reasons = [];
    if (o.isManual) return reasons;
    if (o.profitEstimated) {
      reasons.push('Finans API\'de henüz gerçek settlement kaydı yok, satır fiyatı ve tahmini komisyon oranıyla hesaplandı.');
    }
    if (o.cargoEstimated) {
      reasons.push('Kargo faturası henüz senkron olmadı, bu ürünün (veya genel) geçmiş ortalama kargo bedeliyle tahmin edildi — fatura gelince otomatik güncellenir.');
    }
    return reasons;
  }

  function netProfitCell(o) {
    if (o.netProfit === null || o.netProfit === undefined) {
      return '<span class="op-missing" title="Bu sipariş için ürün maliyeti tanımlı değil, kâr hesaplanamıyor.">maliyet yok</span>';
    }
    const cls = o.netProfit > 0 ? 'pos' : (o.netProfit < 0 ? 'neg' : '');
    if (o.isManual) {
      return `<span class="op-profit ${cls}" title="Manuel sipariş: satış − alış maliyeti − komisyon − kargo">${fmtTL2(o.netProfit)}</span>`;
    }
    const reasons = estimateReasons(o);
    const est = reasons.length ? ' is-est' : '';
    const title = reasons.length ? `Tahmini: ${reasons.join(' ')}` : 'Gerçek: Finans API settlement kaydına ve gerçek kargo faturasına göre hesaplandı.';
    return `<span class="op-profit ${cls}${est}" title="${escHtml(title)}">${fmtTL2(o.netProfit)}</span>`;
  }

  function marginPill(m) {
    if (m === null || m === undefined) return '<span class="op-margin none">—</span>';
    const cls = m >= 25 ? 'good' : (m >= 10 ? 'mid' : 'bad');
    return `<span class="op-margin ${cls}">%${Number(m).toLocaleString('tr-TR', { maximumFractionDigits: 1 })}</span>`;
  }

  const fmtTL0 = (n) => n === null || n === undefined ? '—' : '₺' + Number(n).toLocaleString('tr-TR', { maximumFractionDigits: 0 });
  const pctOf = (part, whole) => (whole > 0 && part != null) ? Math.abs(part) / whole * 100 : null;
  const fmtPct = (p) => p === null ? '' : '%' + p.toLocaleString('tr-TR', { maximumFractionDigits: 1 });

  function costCell(v, est) {
    if (v === null || v === undefined) return '<span class="op-cost">—</span>';
    if (!v) return '<span class="op-cost">₺0</span>';
    return `<span class="op-cost${est ? ' is-est' : ''}"${est ? ' title="Tahmini"' : ''}>−${fmtTL2(Math.abs(v))}</span>`;
  }

  // Ürün görseli SADECE Trendyol'dan senkronize ediliyor ("Ürün Ayarları"
  // sayfasındaki manuel senkron butonu — otomatik/periyodik bir görsel
  // senkronu yok). Aynı SKU Hepsiburada'da da satılıyorsa backend
  // (/api/orders) aynı görseli otomatik eşleştiriyor; hiç senkron
  // edilmemiş bir SKU için imageUrl null gelir. Boş bırakmak yerine
  // her zaman açık bir placeholder gösteriyoruz — sessizce veri
  // uydurmamak/gizlememek için. Sipariş listesinin ana satırında,
  // siparişteki ilk görseli bulunan ürün gösterilir (çoğu sipariş tek
  // kalemli; birden fazla kalem varsa ilk kalemin görseli temsilen kullanılır).
  function orderThumb(lines) {
    const withImage = (lines || []).find(ln => ln.imageUrl);
    if (!withImage) {
      return '<div class="op-thumb" title="Görsel yok (bu SKU için Trendyol\'dan senkronize edilmiş bir ürün görseli bulunamadı)">—</div>';
    }
    const alt = escHtml(withImage.productName || '');
    return `<img class="op-thumb" src="${escHtml(withImage.imageUrl)}" alt="${alt}" loading="lazy" onerror="this.outerHTML='<div class=&quot;op-thumb&quot; title=&quot;Görsel yüklenemedi&quot;>—</div>';">`;
  }

  function productCell(o) {
    const lines = o.lines || [];
    const first = lines[0];
    const qty = lines.reduce((a, ln) => a + (Number(ln.quantity) || 0), 0);
    let name = first ? (first.productName || first.merchantSku || '—') : '—';
    const extra = lines.length > 1 ? ` <span class="op-sub" style="display:inline">+${lines.length - 1} ürün</span>` : '';
    const qtyTxt = qty > 1 ? ` ×${qty}` : '';
    return `<div class="op-product">${orderThumb(lines)}<div class="op-product-text">
      <span class="op-product-name" title="${escHtml(name)}">${escHtml(name)}${qtyTxt}${extra}</span>
      <span class="op-product-meta">${fmtDateTime(o.orderDate)} · ${escHtml(o.orderNumber) || '—'}</span>
    </div></div>`;
  }

  // Satır açılınca: ciro → giderler → net kâr şelalesi (bar uzunluğu ciroya oranla).
  function renderWaterfall(o) {
    const rev = o.revenue;
    if (rev === null || rev === undefined) {
      return '<div class="op-wf-note" style="color:var(--lal-text-muted)">Bu sipariş için kâr dökümü yok (iptal / henüz finans verisi oluşmamış olabilir).</div>';
    }
    const commission = (o.commission || 0) + (o.serviceFee || 0);
    const rows = [
      ['Satış (KDV hariç)', rev, 'c-profit', false, false],
      ['Komisyon' + (o.serviceFee ? ' + hizmet' : ''), -commission, 'c-comm', o.profitEstimated, false],
      ['Kargo', -(o.cargo || 0), 'c-cargo', o.cargoEstimated, false],
      ['Ürün maliyeti', o.cogs === null ? null : -(o.cogs || 0), 'c-cogs', false, false],
    ];
    if (Math.abs(o.other || 0) >= 0.05) rows.push(['İade / düzeltme', o.other, 'c-other', false, false]);
    const body = rows.map(([lbl, v, c, est]) => {
      const w = v === null ? 0 : Math.min(100, pctOf(v, rev) || 0);
      const amt = v === null ? '<span class="op-missing">maliyet yok</span>'
        : `<span class="${est ? 'is-est' : ''}">${v < 0 ? '−' : ''}${fmtTL2(Math.abs(v))}</span>`;
      return `<div class="op-wf-row"><span class="lbl">${lbl}</span><span class="bar"><i class="${c}" style="width:${w}%;${c === 'c-profit' ? 'opacity:.35' : ''}"></i></span><span class="amt">${amt}</span><span class="pct">${v === null || c === 'c-profit' ? '' : fmtPct(pctOf(v, rev))}</span></div>`;
    }).join('');
    const np = o.netProfit;
    const npCls = np === null ? '' : (np >= 0 ? 'pos' : 'neg');
    const total = `<div class="op-wf-row total"><span class="lbl">Net kâr</span><span class="bar"><i class="c-profit" style="width:${np === null ? 0 : Math.min(100, Math.max(0, pctOf(np, rev) || 0))}%;${np < 0 ? 'background:var(--lal-red)' : ''}"></i></span><span class="amt op-profit ${npCls}">${np === null ? '—' : fmtTL2(np)}</span><span class="pct">${marginPill(o.margin)}</span></div>`;
    const reasons = estimateReasons(o);
    const note = reasons.length ? `<div class="op-wf-note"><span class="is-est">Tahmini</span> ${escHtml(reasons.join(' '))}</div>` : '';
    return `<h4>Kâr dökümü</h4><div class="op-wf">${body}${total}</div>${note}`;
  }

  function renderDetail(o) {
    const meta = `<div class="op-meta">
      <span>Müşteri <b>${escHtml(o.customer) || '—'}</b></span>
      ${o.isManual ? '' : `<span>Kargo <b>${escHtml(o.cargoProvider) || '—'}</b></span>`}
      <span>Tahsil edilen (KDV dahil) <b>${fmtTL2(o.netAmount)}</b></span>
    </div>`;
    const right = o.isManual ? renderManualDetail(o) : renderOrderLines(o.lines);
    return `<div class="op-detail"><div>${renderWaterfall(o)}</div><div>${meta}<h4>Ürünler</h4>${right}</div></div>`;
  }

  function renderOrderLines(lines) {
    if (!lines || !lines.length) return '<div style="color:var(--text-muted); font-size:12.5px;">Satır detayı yok.</div>';
    return `
      <table class="op-lines">
        <thead><tr><th>SKU</th><th>Ürün</th><th class="num">Adet</th><th class="num">Birim Fiyat</th><th class="num">Komisyon %</th></tr></thead>
        <tbody>
          ${lines.map(ln => `
            <tr>
              <td>${escHtml(ln.merchantSku) || '—'}</td>
              <td>${escHtml(ln.productName) || '—'}</td>
              <td class="num">${ln.quantity ?? '—'}</td>
              <td class="num">${fmtTL2(ln.lineUnitPrice)}</td>
              <td class="num">${ln.commissionRate ?? '—'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  function renderOrders(orders) {
    const tbody = document.getElementById('orders-tbody');
    if (!orders.length) {
      const msg = profitFilter ? 'Bu filtreye uyan sipariş yok.' : 'Bu aralıkta sipariş bulunamadı.';
      tbody.innerHTML = emptyStateRow(ORDER_COLUMN_COUNT, msg);
      return;
    }
    tbody.innerHTML = orders.map((o, i) => {
      const hasRev = o.revenue !== null && o.revenue !== undefined;
      const sale = hasRev
        ? `${fmtTL2(o.revenue)}<span class="op-sub">KDV dahil ${fmtTL2(o.netAmount)}</span>`
        : `${fmtTL2(o.netAmount)}<span class="op-sub">KDV dahil</span>`;
      const comm = hasRev ? (o.commission || 0) + (o.serviceFee || 0) : null;
      return `
      <tr class="order-row" data-idx="${i}" tabindex="0" aria-expanded="false">
        <td class="op-caret">▸</td>
        <td>${productCell(o)}</td>
        <td>${marketplaceBadge(o.marketplace)}</td>
        <td>${statusPill(o.status)}</td>
        <td class="num">${sale}</td>
        <td class="num op-col-cost">${costCell(comm, o.profitEstimated)}</td>
        <td class="num op-col-cost">${costCell(hasRev ? o.cargo : null, o.cargoEstimated)}</td>
        <td class="num op-col-cost">${costCell(hasRev ? o.cogs : null, false)}</td>
        <td class="num">${netProfitCell(o)}</td>
        <td class="num">${marginPill(o.margin)}</td>
      </tr>
      <tr class="detail-row" id="detail-${i}">
        <td colspan="${ORDER_COLUMN_COUNT}">${renderDetail(o)}</td>
      </tr>`;
    }).join('');

    tbody.querySelectorAll('tr.order-row').forEach(row => {
      const toggle = () => {
        const detail = document.getElementById(`detail-${row.dataset.idx}`);
        const open = detail.classList.toggle('open');
        row.classList.toggle('is-open', open);
        row.setAttribute('aria-expanded', String(open));
        row.querySelector('.op-caret').textContent = open ? '▾' : '▸';
      };
      row.addEventListener('click', toggle);
      row.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
    });
  }

  function renderSummary(sm) {
    const box = document.getElementById('op-summary');
    if (!box) return;
    if (!sm) { box.hidden = true; return; }
    box.hidden = false;
    const rev = sm.revenue || 0;
    const comm = (sm.commission || 0) + (sm.serviceFee || 0);
    const kpi = (label, val, sub, extra = '') =>
      `<div class="op-kpi${extra}"><span>${label}</span><b${extra.includes('hero') ? ` class="${sm.netProfit >= 0 ? 'pos' : 'neg'}"` : ''}>${val}</b><small>${sub}</small></div>`;
    document.getElementById('op-kpis').innerHTML = [
      kpi('Ciro (KDV hariç)', fmtTL0(rev), `${sm.orderCount} sipariş`),
      kpi('Komisyon + Hizmet', '−' + fmtTL0(comm), fmtPct(pctOf(comm, rev)) + ' ciro'),
      kpi('Kargo', '−' + fmtTL0(sm.cargo), fmtPct(pctOf(sm.cargo, rev)) + ' ciro'),
      kpi('Ürün Maliyeti', '−' + fmtTL0(sm.cogs), fmtPct(pctOf(sm.cogs, rev)) + ' ciro'),
      kpi('Net Kâr', fmtTL0(sm.netProfit), sm.margin === null ? '—' : `marj ${fmtPct(sm.margin)}`, ' op-kpi-hero'),
    ].join('');

    const other = -(sm.other || 0); // pozitif = gider
    const parts = [
      ['c-cogs', 'Ürün maliyeti', sm.cogs],
      ['c-comm', 'Komisyon + hizmet', comm],
      ['c-cargo', 'Kargo', sm.cargo],
      ['c-other', 'İade / düzeltme', other > 0 ? other : 0],
      ['c-profit', 'Net kâr', Math.max(0, sm.netProfit || 0)],
    ].filter(p => p[2] > 0);
    const sum = parts.reduce((a, p) => a + p[2], 0) || 1;
    document.getElementById('op-split').innerHTML = parts.map(([c, , v]) => `<i class="${c}" style="flex-grow:${v / sum}"></i>`).join('');
    document.getElementById('op-split-legend').innerHTML = parts.map(([c, l, v]) =>
      `<span><i class="${c}"></i>${l} <b>${fmtPct(v / sum * 100)}</b></span>`).join('');

    const notes = [];
    if (sm.missingCostCount) notes.push(`${sm.missingCostCount} siparişin ürün maliyeti tanımlı değil, toplama katılmadı`);
    if (sm.estimatedCount) notes.push(`${sm.estimatedCount} sipariş tahmini komisyon/kargo içeriyor`);
    if (other < 0) notes.push(`iade/düzeltme etkisi +${fmtTL0(-other)}`);
    document.getElementById('op-summary-note').textContent = notes.length ? notes.join(' · ') + '.' : '';
    const setChip = (id, n) => { const el = document.getElementById(id); if (el) el.textContent = n ? n : ''; };
    setChip('chip-loss', sm.lossCount);
    setChip('chip-missing', sm.missingCostCount);
  }

  function escHtml(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function renderManualDetail(o) {
    const rows = (o.items || []).map(it => `
      <tr>
        <td>${escHtml(it.sku)}</td>
        <td>${escHtml(it.productName) || '—'}</td>
        <td>${it.quantity}</td>
        <td>${fmtTL2(it.unitPrice)}</td>
        <td>${fmtTL2(it.unitCost)}</td>
      </tr>`).join('');
    const note = o.notes ? `<div class="manual-detail-note">Not: ${escHtml(o.notes)}</div>` : '';
    return `
      <table class="op-lines">
        <thead><tr><th>SKU</th><th>Ürün</th><th>Adet</th><th>Birim Satış</th><th>Birim Maliyet</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="manual-detail-sums">
        <span>Satış: <b>${fmtTL2(o.saleTotal)}</b></span>
        <span>Maliyet: <b>${fmtTL2(o.cogsTotal)}</b></span>
        <span>Komisyon: <b>${fmtTL2(o.commission)}</b></span>
        <span>Kargo: <b>${fmtTL2(o.cargoCost)}</b></span>
        <span>Net kâr: <b>${fmtTL2(o.netProfit)}</b></span>
      </div>
      ${note}
      <div class="manual-detail-actions">
        <button class="lal-btn lal-btn-secondary" type="button" data-manual-edit="${o.manualId}">Düzenle</button>
        <button class="lal-btn lal-btn-secondary" type="button" data-manual-delete="${o.manualId}">Sil</button>
      </div>`;
  }

  function renderPagination(total, page, pageSize) {
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const el = document.getElementById('pagination');
    if (total <= pageSize) { el.classList.add('is-hidden'); return; }
    el.classList.remove('is-hidden');
    document.getElementById('page-info').textContent = `Sayfa ${page} / ${totalPages}`;
    document.getElementById('prev-btn').disabled = page <= 1;
    document.getElementById('next-btn').disabled = page >= totalPages;
  }

  async function loadOrders(page) {
    currentPage = page || 1;
    // Faz 8.1: "Yükleniyor…" düz metni yerine tabloyu görünür tutup içine
    // gerçek satırların şekline yakın iskelet (skeleton) satırlar koyuyoruz.
    safeDisplay('orders-loading', 'none');
    safeDisplay('orders-table-wrap', 'block');
    document.getElementById('orders-tbody').innerHTML = skeletonTableRows(ORDER_COLUMN_COUNT, 6, [2, 28, 8, 8, 10, 9, 8, 9, 10, 6]);
    document.getElementById('pagination').classList.add('is-hidden');
    hideError();

    const status = document.getElementById('status-select').value;
    const q = document.getElementById('search-input').value.trim();
    const params = new URLSearchParams();
    rangeQueryParam().split('&').forEach(p => { const [k, v] = p.split('='); params.set(k, v); });
    params.set('page', currentPage);
    params.set('page_size', PAGE_SIZE);
    if (status) params.set('status', status);
    if (q) params.set('q', q);
    const mpSel = document.getElementById('marketplace-select');
    if (mpSel && mpSel.value) params.set('marketplace', mpSel.value);
    if (profitFilter) params.set('profit_filter', profitFilter);
    if (sortKey !== 'date' || sortDir !== 'desc') { params.set('sort', sortKey); params.set('dir', sortDir); }

    try {
      const res = await fetch(`/api/orders?${params.toString()}`);
      const data = await res.json();
      if (data.error) {
        showError(data.error);
        document.getElementById('orders-tbody').innerHTML = errorStateRow(ORDER_COLUMN_COUNT, data.error);
        return;
      }
      renderSummary(data.summary);
      renderOrders(data.orders);
      document.getElementById('result-note').textContent = `${data.start_date} — ${data.end_date} arası, toplam ${data.total} sipariş bulundu.`;
      renderPagination(data.total, data.page, data.page_size);
    } catch (e) {
      showError('Beklenmeyen bir hata oluştu: ' + e.message);
      document.getElementById('orders-tbody').innerHTML = errorStateRow(ORDER_COLUMN_COUNT, e.message);
    }
  }

  onExist('prev-btn', 'click', () => { if (currentPage > 1) loadOrders(currentPage - 1); });
  onExist('next-btn', 'click', () => loadOrders(currentPage + 1));
  onExist('status-select', 'change', () => loadOrders(1));
  onExist('marketplace-select', 'change', () => loadOrders(1));
  onExist('export-btn', 'click', () => {
    const status = document.getElementById('status-select').value;
    const q = document.getElementById('search-input').value.trim();
    const params = new URLSearchParams();
    params.set('full_history', 'true');
    if (status) params.set('status', status);
    if (q) params.set('q', q);
    window.location.href = `/api/orders/export?${params.toString()}`;
  });

  document.querySelectorAll('#op-chips .op-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      profitFilter = btn.dataset.filter || '';
      document.querySelectorAll('#op-chips .op-chip').forEach(b => b.classList.toggle('is-active', b === btn));
      loadOrders(1);
    });
  });

  function paintSort() {
    document.querySelectorAll('.op-sort').forEach(b => {
      if (b.dataset.sort === sortKey) b.dataset.dir = sortDir; else delete b.dataset.dir;
    });
  }
  document.querySelectorAll('.op-sort').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.sort;
      if (sortKey === key) sortDir = sortDir === 'desc' ? 'asc' : 'desc';
      else { sortKey = key; sortDir = 'desc'; }
      paintSort();
      loadOrders(1);
    });
  });
  paintSort();

  let searchTimeout;
  onExist('search-input', 'input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => loadOrders(1), 400);
  });

  // ---------- Başlangıç ----------
  loadOrders(1);
  document.addEventListener('lal:data-refresh', () => loadOrders(1));
})();
