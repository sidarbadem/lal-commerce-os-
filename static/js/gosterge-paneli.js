// =====================================================================
// GÖSTERGE PANELİ — yalnızca bu sayfada yüklenir (Faz 7)
// =====================================================================
(function () {
  if (!document.getElementById('net-profit-hero')) return; // bu sayfada değiliz

  // ---------- KPI'lar + Sipariş Satırı Detayı ----------
  let firstLoadDone = false;
  let linesCache = [];
  let refreshGeneration = 0;
  const requestControllers = {};
  const LINES_THEAD_STANDARD = '<th>Tarih</th><th>Sipariş No</th><th>SKU</th><th>Ürün</th><th>Adet</th><th>Ciro</th><th>Komisyon</th><th>Hizmet Bedeli</th><th>Net Hakediş</th><th>Kargo</th><th>Maliyet</th><th>Kâr</th><th>Durum</th>';

  function startRequest(name) {
    if (requestControllers[name]) requestControllers[name].abort();
    const controller = new AbortController();
    requestControllers[name] = controller;
    return controller;
  }

  function isCurrentRequest(name, controller, generation) {
    return requestControllers[name] === controller && !controller.signal.aborted && generation === refreshGeneration;
  }

  function setVisible(id, visible) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('is-hidden', !visible);
  }

  const MP_NAMES = { all: 'Tüm pazaryerleri', trendyol: 'Trendyol', hepsiburada: 'Hepsiburada' };
  const pctOf = (v, base) => (base ? fmtPct(v / base) : '–');

  // Dönem başlığı: "Son 30 gün" + "3 Eki – 2 Kas 2026" (tarih filtresine göre).
  function renderPeriodHead() {
    const sel = document.getElementById('range-select');
    const val = sel ? sel.value : '30';
    const label = sel && sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].textContent : '';
    const fmt = (d, withYear) => d.toLocaleDateString('tr-TR', withYear ? { day: 'numeric', month: 'short', year: 'numeric' } : { day: 'numeric', month: 'short' });
    const end = new Date();
    let range;
    if (val === 'all') range = 'Tüm zamanlar';
    else if (val === 'today') range = fmt(end, true);
    else {
      const start = new Date(); start.setDate(start.getDate() - Number(val) + 1);
      range = `${fmt(start, start.getFullYear() !== end.getFullYear())} – ${fmt(end, true)}`;
    }
    safeText('da-period-label', `${label} · ${MP_NAMES[currentMarketplace] || currentMarketplace}`);
    safeText('da-period-range', range);
  }

  // Cirodan net kâra şelale. Kalemler finance_engine'in KDV hariç toplamları;
  // ara toplamlar (brüt kâr, katkı kârı, net kâr) motorun kendi rakamları
  // olduğundan şelale her zaman net kâra kapanır. Hesap dışı kalan kısımlar
  // (maliyeti girilmemiş ürünler vb.) ayrı satır olarak gösterilir.
  function renderWaterfall(t) {
    const el = document.getElementById('da-waterfall');
    if (!el) return;
    const rev = t.gross_revenue || 0;
    const tgp = t.true_gross_profit || 0;
    const cogs = t.cogs_total || 0;
    const gp = t.gross_profit || 0;
    const net = t.net_profit || 0;
    const rows = [];
    const step = (label, v, note) => { if (Math.abs(v) >= 1) rows.push({ kind: 'step', label, v: -v, note }); };
    const sub = (label, v) => rows.push({ kind: 'sub', label, v });

    rows.push({ kind: 'start', label: 'Ciro', v: rev });
    step('Ürün maliyeti', cogs);
    step('Maliyeti girilmemiş ürünlerin satışı', rev - cogs - tgp, 'Maliyet girilene kadar kâra katılmıyor');
    sub('Brüt kâr', tgp);
    step('Komisyon', t.commission || 0);
    step('Hizmet bedeli', t.service_fee || 0);
    step('Kargo', t.cargo_total || 0);
    step('Kâr hesabı dışında kalan satırlar', tgp - (t.commission || 0) - (t.service_fee || 0) - (t.cargo_total || 0) - gp, 'Kargo faturası veya maliyeti eksik satırlar');
    sub('Katkı kârı', gp);
    // Platform bedeli / erken ödeme API'de KDV dahil geliyor; şelale KDV hariç
    // olduğundan motorun kendi farkı (katkı kârı − net kâr) tek satırda.
    step('Dönemsel giderler', gp - net,
      'İade, reklam, platform bedeli, erken ödeme' + (t.return_amount ? ` · iade ${fmtTL(t.return_amount)}` : ''));
    rows.push({ kind: 'end', label: 'Net kâr', v: net });

    const max = Math.max(rev, 1);
    el.innerHTML = rows.map(r => {
      const w = Math.min(100, Math.abs(r.v) / max * 100);
      const neg = r.v < 0;
      const cls = r.kind === 'step' ? (neg ? 'is-cost' : 'is-gain') : 'is-total' + (r.kind === 'end' ? ' is-end' + (net < 0 ? ' is-loss' : '') : '');
      const amount = r.kind === 'step' ? (neg ? '−' : '+') + fmtTL(Math.abs(r.v)).replace('-', '') : fmtTL(r.v);
      return `<div class="da-wf-row ${cls}" role="row">
        <div class="da-wf-l" role="cell">${esc(r.label)}${r.note ? `<small>${esc(r.note)}</small>` : ''}</div>
        <div class="da-wf-bar" role="cell" aria-hidden="true"><i style="width:${w.toFixed(2)}%"></i></div>
        <div class="da-wf-v" role="cell">${amount}</div>
        <div class="da-wf-p" role="cell">${pctOf(Math.abs(r.v), rev)}</div>
      </div>`;
    }).join('');
    const foot = document.getElementById('da-wf-foot');
    if (foot) {
      foot.textContent = t.stoppage ? `Stopaj ${fmtTL(t.stoppage)} ayrıca kesildi; gelir vergisinden mahsup edildiği için kârdan düşülmez.` : '';
    }
  }

  function renderProfitSummary(t, dq) {
    renderPeriodHead();
    const rev = t.gross_revenue || 0;
    document.getElementById('stat-gross-revenue').textContent = fmtTL(t.gross_revenue);
    document.getElementById('stat-revenue').textContent = fmtTL(t.revenue);
    // Brüt Kâr = Ciro − sadece ürün maliyeti (true_gross_profit). t.gross_profit
    // komisyon/kargo sonrası "katkı kârı"dır; şelalede ayrı satır.
    document.getElementById('stat-gross-profit').textContent = fmtTL(t.true_gross_profit);
    safeText('stat-gross-profit-sub', `ciro − ürün maliyeti · ${pctOf(t.true_gross_profit || 0, rev)}`);
    const netEl = document.getElementById('stat-net-profit');
    netEl.textContent = fmtTL(t.net_profit);
    netEl.className = 'hero-stat-value ' + (t.net_profit >= 0 ? 'green' : 'red');
    document.getElementById('net-profit-hero').classList.toggle('negative', t.net_profit < 0);
    safeText('stat-net-profit-sub', `marj ${pctOf(t.net_profit || 0, rev)} · vergi ve prim öncesi`);
    const cargoHint = document.getElementById('stat-net-profit-cargo-hint');
    if (cargoHint) {
      const missingCargoCount = dq && dq.orders_missing_cargo_invoice;
      if (missingCargoCount) {
        cargoHint.title = `${missingCargoCount} siparişin kargo faturası henüz gelmedi — bu siparişlerde kargo ortalama maliyetle tahmin edildi, fatura gelince kesinleşir.`;
        cargoHint.classList.remove('is-hidden');
      } else {
        cargoHint.classList.add('is-hidden');
      }
    }
    document.getElementById('stat-return').textContent = fmtTL(t.return_amount);
    document.getElementById('stat-return-count').textContent = t.return_count ? `${fmtNum(t.return_count)} iade işlemi` : '';
    document.getElementById('stat-payment-order').textContent = fmtTL(t.payment_order_net);
    setVisible('stat-payment-order-card', !!t.payment_order_net);
    document.getElementById('stat-avg-margin').textContent = rev ? fmtPct(t.net_profit / rev) : '–';
    renderWaterfall(t);
  }

  function applyLinesFilter() {
    const onlyEstimated = document.getElementById('lines-estimated-only').checked;
    let rows = onlyEstimated ? linesCache.filter(l => l.estimated) : linesCache;
    rows = [...rows].sort((a, b) => {
      if (a.estimated !== b.estimated) return a.estimated ? -1 : 1;
      return (b.orderDate || 0) - (a.orderDate || 0);
    });

    document.getElementById('lines-body').innerHTML = rows.slice(0, 300).map(l => {
      let pill = l.claimPending ? '<span class="pill pill-missing" title="Hepsiburada\'da iade talebi açık; iade kesinleşirse kârdan düşülür.">İade talebi</span>'
        : l.estimated ? '<span class="pill pill-estimated">Tahmini</span>' : '<span class="pill pill-real">Gerçek</span>';
      if (l.missingCost) pill += ' <span class="pill pill-missing">Maliyet eksik</span>';
      return `
        <tr>
          <td>${l.orderDate ? new Date(l.orderDate).toLocaleDateString('tr-TR') : '—'}</td>
          <td>${esc(l.orderNumber || '')}</td>
          <td>${esc(l.sku || '–')}</td>
          <td>${esc(l.productName || '')}</td>
          <td>${fmtNum(l.quantity)}</td>
          <td>${fmtTL(l.grossRevenue)}</td>
          <td>${fmtTL(l.commission)}</td>
          <td>${fmtTL(l.serviceFee)}</td>
          <td>${fmtTL(l.netHakedis)}</td>
          <td>${fmtTL(l.cargo)}</td>
          <td>${l.cogs === null ? '–' : fmtTL(l.cogs)}</td>
          <td style="color:${(l.profit ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${l.profit === null ? '–' : fmtTL(l.profit)}</td>
          <td>${pill}</td>
        </tr>
      `;
    }).join('');

    if (onlyEstimated && !rows.length) {
      document.getElementById('lines-body').innerHTML = emptyStateRow(13, 'Şu an tahmini (settlement bekleyen) satır yok.');
    }
  }
  onExist('lines-estimated-only', 'change', applyLinesFilter);

  function renderLines(lines) {
    linesCache = lines;
    document.getElementById('lines-thead-row').innerHTML = LINES_THEAD_STANDARD;
    applyLinesFilter();
  }

  async function loadSummary(generation = refreshGeneration) {
    const controller = startRequest('summary');
    if (!firstLoadDone) { setVisible('summary-loading', true); setVisible('summary-content', false); }
    hideError();
    void loadTodayOrderCount(generation);
    try {
      const rangeParam = rangeQueryParam();
      const [summaryRes, orderCountRes] = await Promise.all([
        fetch(`/api/dashboard-summary?${rangeParam}`, { signal: controller.signal }),
        fetch(`/api/orders?${rangeParam}&page=1&page_size=1`, { signal: controller.signal }),
      ]);
      const summary = await summaryRes.json();
      if (!isCurrentRequest('summary', controller, generation)) return;
      try {
        const orderCountData = await orderCountRes.json();
        if (!isCurrentRequest('summary', controller, generation)) return;
        safeText('stat-orders', orderCountData.error ? '—' : fmtNum(orderCountData.total));
        if (!orderCountData.error && orderCountData.total && summary.totals) {
          const t = summary.totals;
          safeText('stat-orders-sub', `ort. sepet ${fmtTL((t.gross_revenue || 0) / orderCountData.total)} (KDV hariç)`);
          safeText('da-period-summary', `${fmtNum(orderCountData.total)} sipariş · ${fmtTL(t.gross_revenue)} ciro · ${fmtTL(t.net_profit)} net kâr (${t.gross_revenue ? fmtPct(t.net_profit / t.gross_revenue) : '–'})`);
        }
      } catch (e) {
        if (isCurrentRequest('summary', controller, generation)) safeText('stat-orders', '—');
      }
      if (summary.error) { showError(summary.error); setVisible('summary-loading', false); return; }
      renderProfitSummary(summary.totals, summary.data_quality);
      renderLines(summary.lines || summary.orders || []);
      loadMonthlyProfitChart(generation);
      setVisible('summary-loading', false);
      setVisible('summary-content', true);
      firstLoadDone = true;
    } catch (e) {
      if (!isCurrentRequest('summary', controller, generation) || e.name === 'AbortError') return;
      setVisible('summary-loading', false);
      showError('Beklenmeyen bir hata oluştu: ' + e.message);
    }
  }

  async function loadTodayOrderCount(generation = refreshGeneration) {
    const controller = startRequest('todayOrderCount');
    const el = document.getElementById('today-order-count');
    try {
      const res = await fetch('/api/today-order-count', { signal: controller.signal });
      const data = await res.json();
      if (!isCurrentRequest('todayOrderCount', controller, generation)) return;
      el.textContent = data.error ? '—' : fmtNum(data.count);
    } catch (e) {
      if (isCurrentRequest('todayOrderCount', controller, generation) && e.name !== 'AbortError') el.textContent = '—';
    }
  }

  // ---------- Aylık Kâr Trendi (2 görünüm: Trend Analizi / Finansal Özet) ----------
  // monthlyProfitChart    -> "Trend Analizi" (line, mevcut sadeleştirilmiş grafik)
  // monthlyProfitBarChart -> "Finansal Özet" (CFO tarzı gruplanmış sütun)
  // İkisi de AYNI monthlyProfitMonths verisini ve AYNI monthlyProfitMetrics()
  // renk/etiket tanımını kullanır — tek veri kaynağı, sadece görselleştirme
  // katmanı farklı.
  let monthlyProfitChart, monthlyProfitBarChart, monthlyProfitLoaded = false;
  let monthlyProfitView = 'cfo'; // 'cfo' (klasik sütun) | 'trend'
  let monthlyProfitMonths = [];
  const LAL_CHART_FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter', system-ui, sans-serif";
  const monthlyProfitTlFmt = new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 0 });

  // Net kâr = GERÇEK net kâr (realNetProfit): vergi, prim ve tüm giderler düşülmüş nihai rakam.
  function monthlyProfitRealNet(m) {
    if (m.realNetProfit === undefined || m.realNetProfit === null) {
      console.warn(
        `[LAL] Finansal Performans: "${m.month}" ayı için API yanıtında realNetProfit alanı yok — ` +
        `finance_engine.monthly_profit() / /api/monthly-profit kontrol edilmeli. ` +
        `Faaliyet kârı (netProfit) Net Kâr olarak KULLANILMIYOR, bu ay için 0 gösteriliyor.`,
        m
      );
      return 0;
    }
    // Devam eden ay: vergi/prim geçen gün oranında (backend realNetProfitAccrued).
    if (m.inProgress && m.realNetProfitAccrued !== undefined && m.realNetProfitAccrued !== null) return m.realNetProfitAccrued;
    return m.realNetProfit;
  }

  // LAL token'larını canlı okuyan yardımcı — hard-coded hex yerine tema neyse onu döner.
  function lalToken(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function lalRgb(color) {
    const c = String(color).trim();
    if (c[0] === '#') {
      const h = c.length === 4 ? c.slice(1).split('').map((x) => x + x).join('') : c.slice(1, 7);
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }
    const n = c.match(/[\d.]+/g) || [0, 0, 0];
    return [+n[0], +n[1], +n[2]];
  }

  function lalAlpha(color, alpha) {
    const [r, g, b] = lalRgb(color);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  // Finans grafiklerinin ORTAK renk paleti: [ciro, brüt kâr, net kâr]. Apple
  // mavi/turuncu/yeşil tonlarının sakin (az doygun) hâli — sistem renklerinin
  // tam doygunluğu (#007AFF vb.) uzun süre bakınca gözü yoruyordu. Sütun
  // grafik, trend çizgileri, legend ve gosterge-aylik-ek.js (kapsül/halkalar)
  // hepsi bunu kullanır; rengi değiştirmek için TEK yer burası.
  function lalFinancePalette() {
    return lalIsLightTheme()
      ? ['#6A97D9', '#E0A35F', '#74B78F']
      : ['#6A9BE0', '#E0AA6A', '#6DBB8E'];
  }
  window.lalFinancePalette = lalFinancePalette;

  function lalIsLightTheme() {
    const [r, g, b] = lalRgb(lalToken('--lal-surface'));
    return (r * 299 + g * 587 + b * 114) / 1000 > 150;
  }

  // Görsel hiyerarşi (sadeleştirilmiş): Ciro en ince/en nötr arka plan
  // referansı — Brüt Kâr ikincil — Net Kâr (= "gerçek net kâr", panelin tek
  // "net kâr" tanımı) tek ve en güçlü vurgu, altı dolgulu.
  //
  // NOT: Eskiden "Net Kâr" (dönemsel giderler düşülmüş ama sabit giderler
  // düşülmemiş ara metrik) ile "Gerçek Net Kâr" (+ sabit giderler de
  // düşülmüş nihai rakam) AYRI iki çizgi olarak gösteriliyordu — ikisi
  // görsel olarak neredeyse çakışıyordu ve grafiği okunaksız kılıyordu.
  // Artık sadece TEK bir "Net Kâr" çizgisi var ve bu, verideki
  // realNetProfit (gerçek net kâr) değeridir — panelde kullanıcıya
  // gösterilen "net kâr" HER ZAMAN sabit giderler dahil nihai rakamdır.
  //
  // NOT / TEŞHİS: --lal-accent bu tema sisteminde kırmızı/bordo bir tondur
  // (koyu #d64455, açık #a92639 — bkz. tokens.css),
  // bu yüzden pozitif olması beklenen Net Kâr için kullanılmıyor —
  // --lal-green kullanılıyor (LAL'in 3 semantik renginden biri).
  function monthlyProfitMetrics() {
    return [
      { key: 'revenue', label: 'Ciro', width: 1.75, dash: [], pointStyle: 'circle', fill: false, color: () => lalFinancePalette()[0] },
      { key: 'grossProfit', label: 'Brüt Kâr', width: 2, dash: [5, 4], pointStyle: 'circle', fill: false, color: () => lalFinancePalette()[1] },
      { key: 'netProfit', label: 'Net Kâr (vergi sonrası)', width: 2.75, dash: [], pointStyle: 'circle', fill: true, color: () => lalFinancePalette()[2] },
    ];
  }

  // Aktif noktada dikey rehber çizgi — sadece bu grafiğe özel plugin olarak
  // geçiliyor (Chart.register değil), diğer grafikleri etkilemez.
  const monthlyProfitGuidePlugin = {
    id: 'mpcGuide',
    afterDraw(chart) {
      const active = chart.tooltip && chart.tooltip._active;
      if (!active || !active.length) return;
      const x = active[0].element.x;
      const { top, bottom } = chart.chartArea;
      const ctx = chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.lineWidth = 1;
      ctx.strokeStyle = lalToken('--lal-border');
      ctx.setLineDash([3, 3]);
      ctx.stroke();
      ctx.restore();
    },
  };

  // 1000 TL üzeri değerleri "₺46,8B" (bin) gibi kısaltır — sütun üstü değer
  // etiketleri için kullanılır. Amaç: Ciro (~₺300B) yanında Net Kâr
  // (~₺30-50B) gibi küçük değerlerin de tam sayı ("₺46.765") yerine kısa
  // metinle ("₺46,8B") gösterilmesi, böylece bitişik sütunların etiketleri
  // birbirine çarpmasın. Eksende ve tooltip'te hâlâ tam TL tutarı (₺46.765)
  // gösteriliyor — bu sadece sütun üstü kısa etiket için.
  function monthlyProfitCompactTl(value) {
    const sign = value < 0 ? '-' : '';
    const abs = Math.abs(value);
    if (abs >= 10000) return `${sign}₺${Math.round(abs / 1000)}K`;
    if (abs >= 1000) return `${sign}₺${(abs / 1000).toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}K`;
    return monthlyProfitTlFmt.format(value);
  }

  // Sütun üstü değer etiketleri — SADECE Finansal Özet (CFO bar) grafiğinde.
  // Çakışma önleme: bir çubuğun piksel yüksekliği belirli bir eşiğin
  // altındaysa (örn. çok küçük bir ay/metrik) üstüne etiket YAZILMAZ —
  // hem görsel gürültüyü azaltır hem de bitişik minik çubukların
  // etiketlerinin üst üste binmesini engeller (tam tutar zaten hover
  // tooltip'inde mevcut). Etiket rengi --lal-text-main token'ından okunur
  // (her iki temada da en yüksek kontrastlı metin tonu, bkz. tokens.css).
  //
  // İSTİSNA — devam eden (şu anki) ay: bu her zaman en sağdaki bar'dır ve
  // sağında komşu bar olmadığı için çakışma riski yoktur. Ayın ilk
  // günlerinde kümülatif rakamlar henüz çok küçük olabileceğinden (bar
  // 14px eşiğinin altında kalır) bu eşik istisnasız uygulanırsa devam
  // eden ay için Ciro/Brüt Kâr/Net Kâr etiketleri tamamen kaybolur — veri
  // yokmuş gibi görünür. currentMonthIndex bu ay için eşiği by-pass eder.
  const MONTHLY_PROFIT_LABEL_MIN_PX = 16;
  function monthlyProfitValueLabelColor() {
    return lalToken('--lal-text-main');
  }
  const monthlyProfitBarValueLabels = {
    id: 'mpcBarValueLabels',
    afterDatasetsDraw(chart) {
      const ctx = chart.ctx;
      const zeroY = chart.scales.y.getPixelForValue(0);
      // Kısa etiket: ₺ işareti yok (eksende/tooltip'te var).
      const text = (v) => {
        const sign = v < 0 ? '-' : '';
        const abs = Math.abs(v);
        if (abs >= 10000) return `${sign}${Math.round(abs / 1000)}K`;
        if (abs >= 1000) return `${sign}${(abs / 1000).toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}K`;
        return `${sign}${Math.round(abs)}`;
      };
      const items = [];
      chart.data.datasets.forEach((ds, dsIndex) => {
        if (!chart.isDatasetVisible(dsIndex)) return;
        chart.getDatasetMeta(dsIndex).data.forEach((bar, i) => {
          const value = ds.data[i];
          if (!value) return;
          const isCurrentMonthBar = i === chart.currentMonthIndex;
          // Net Kâr (son seri, headline metrik) kısa çubuklarda da etiketli kalır; sadece
          // neredeyse sıfır olanlar atlanır. Etiketler çubuk genişliğine göre ölçüldüğü için çakışmaz.
          const minPx = dsIndex === chart.data.datasets.length - 1 ? 3 : MONTHLY_PROFIT_LABEL_MIN_PX;
          if (!isCurrentMonthBar && Math.abs(bar.y - zeroY) < minPx) return;
          items.push({ bar, value, t: text(value) });
        });
      });
      if (!items.length) return;
      // Çakışma önleme: etiket sütundan geniş olmasın. Önce 11.5 → 10.5 → 9.5px
      // dene; hiçbiri sığmazsa TÜM etiketler tutarlı biçimde dikey yazılır.
      const minBarW = Math.min(...items.map(it => it.bar.width || 0)) || 0;
      ctx.save();
      let size = null;
      for (const sz of [11.5, 10.5, 9.5]) {
        ctx.font = `600 ${sz}px ${LAL_CHART_FONT}`;
        if (Math.max(...items.map(it => ctx.measureText(it.t).width)) <= minBarW) { size = sz; break; }
      }
      const vertical = size === null;
      ctx.font = `600 ${vertical ? 11 : size}px ${LAL_CHART_FONT}`;
      ctx.fillStyle = monthlyProfitValueLabelColor();
      items.forEach(({ bar, value, t }) => {
        const isNeg = value < 0;
        if (vertical) {
          ctx.save();
          ctx.translate(bar.x, bar.y + (isNeg ? 6 : -6));
          ctx.rotate(-Math.PI / 2);
          ctx.textAlign = isNeg ? 'right' : 'left';
          ctx.textBaseline = 'middle';
          ctx.fillText(t, 0, 0);
          ctx.restore();
        } else {
          ctx.textAlign = 'center';
          ctx.textBaseline = isNeg ? 'top' : 'bottom';
          ctx.fillText(t, bar.x, bar.y + (isNeg ? 4 : -4));
        }
      });
      ctx.restore();
    },
  };

  function monthlyProfitTooltipEl(chart) {
    const wrap = chart.canvas.closest('.mpc-chart-wrap');
    let el = wrap.querySelector('.mpc-tooltip');
    if (!el) {
      el = document.createElement('div');
      el.className = 'mpc-tooltip';
      wrap.appendChild(el);
    }
    return el;
  }

  // Grafik üzerinde kalıcı rakam bırakmıyoruz (brief madde 8) — tüm ay
  // detayı sadece hover'da, mevcut LAL panel/kart stiliyle uyumlu bu HTML
  // tooltip içinde gösteriliyor.
  function monthlyProfitExternalTooltip(context) {
    const { chart, tooltip } = context;
    const el = monthlyProfitTooltipEl(chart);
    if (!tooltip || tooltip.opacity === 0 || !tooltip.dataPoints || !tooltip.dataPoints.length) {
      el.classList.remove('is-visible');
      return;
    }
    const idx = tooltip.dataPoints[0].dataIndex;
    const m = monthlyProfitMonths[idx];
    if (!m) { el.classList.remove('is-visible'); return; }

    const rev = m.revenue || 0;
    // FAZ 2: tooltip'teki "Brüt Kâr" satırı da gerçek tanıma geçti.
    const gross = m.trueGrossProfit || 0;
    const net = monthlyProfitRealNet(m);
    const pal = lalFinancePalette();
    const rows = [
      { label: 'Ciro', value: rev, color: pal[0], diamond: false },
      { label: 'Brüt Kâr', value: gross, color: pal[1], diamond: false },
      { label: 'Net Kâr', value: net, color: pal[2], diamond: false },
    ];
    const marginLine = (label, value) => rev
      ? `<div class="mpc-tooltip-margin"><span>${label}</span><span>%${((value / rev) * 100).toFixed(1).replace('.', ',')}</span></div>` : '';
    const liveNote = m.inProgress
      ? `<div class="mpc-tooltip-live">Devam ediyor · vergi/prim %${Math.round((m.elapsedRatio || 0) * 100)} oranında düşüldü (${monthlyProfitTlFmt.format(m.taxesAndPremiumsAccrued || 0)} / ${monthlyProfitTlFmt.format(m.taxesAndPremiums || 0)})</div>` : '';

    el.innerHTML = `
      <div class="mpc-tooltip-title">${chart.data.labels[idx]}</div>
      ${rows.map(r => `
        <div class="mpc-tooltip-row">
          <span class="mpc-tooltip-label"><span class="mpc-tooltip-dot${r.diamond ? ' is-diamond' : ''}" style="background:${r.color}"></span>${r.label}</span>
          <span class="mpc-tooltip-value">${monthlyProfitTlFmt.format(r.value)}</span>
        </div>`).join('')}
      <div class="mpc-tooltip-divider"></div>
      <div class="mpc-tooltip-margins">
        ${marginLine('Net Marj', net)}
      </div>${liveNote}`;

    el.style.left = tooltip.caretX + 'px';
    el.style.top = tooltip.caretY + 'px';
    el.classList.add('is-visible');

    // Kapsayıcı dışına taşmasın diye (mobil/dar ekran) — brief madde 14.
    requestAnimationFrame(() => {
      const wrap = chart.canvas.closest('.mpc-chart-wrap');
      if (!wrap) return;
      const wrapRect = wrap.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      let left = parseFloat(el.style.left);
      if (elRect.right > wrapRect.right) left -= (elRect.right - wrapRect.right) + 8;
      if (elRect.left < wrapRect.left) left += (wrapRect.left - elRect.left) + 8;
      el.style.left = left + 'px';
    });
  }

  // Klasik Chart.js legend yerine LAL "chip" stiliyle metrik seçici (brief
  // madde 10). Mevcut interaction modelini bozmamak için en düşük riskli
  // davranış: her chip ilgili seriyi aç/kapatır (Chart.js setDatasetVisibility).
  function renderMonthlyProfitSelector(metrics) {
    const container = document.getElementById('monthlyProfitMetricSelector');
    if (!container) return;
    container.innerHTML = metrics.map((m, i) => `
      <button type="button" class="mpc-chip is-active" data-idx="${i}" aria-pressed="true">
        <span class="mpc-chip-dot${m.pointStyle === 'rectRot' ? ' is-diamond' : ''}" style="background:${m.color()}"></span>${m.label}
      </button>`).join('');
    container.querySelectorAll('.mpc-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        const idx = Number(chip.dataset.idx);
        // İki grafik görünümü de AYNI seri sırasını paylaşıyor (Ciro/Brüt
        // Kâr/Net Kâr) — bir seriyi kapatmak her iki görünümde de geçerli
        // olsun diye ikisine birden uygulanır.
        const ref = monthlyProfitChart || monthlyProfitBarChart;
        const nowVisible = ref ? !ref.isDatasetVisible(idx) : true;
        if (monthlyProfitChart) { monthlyProfitChart.setDatasetVisibility(idx, nowVisible); monthlyProfitChart.update(); }
        if (monthlyProfitBarChart) { monthlyProfitBarChart.setDatasetVisibility(idx, nowVisible); monthlyProfitBarChart.update(); }
        chip.classList.toggle('is-active', nowVisible);
        chip.classList.toggle('is-off', !nowVisible);
        chip.setAttribute('aria-pressed', String(nowVisible));
      });
    });
  }

  function renderMonthlyProfitInProgressBadge(months) {
    const badge = document.getElementById('monthlyProfitInProgressBadge');
    if (!badge || !months.length) { if (badge) badge.classList.add('is-hidden'); return; }
    const last = months[months.length - 1];
    const now = new Date();
    const currentKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    if (last.month === currentKey) {
      const [y, mo] = last.month.split('-');
      const label = new Date(y, mo - 1, 1).toLocaleDateString('tr-TR', { month: 'short', year: '2-digit' });
      badge.textContent = `${label} · devam ediyor`;
      badge.classList.remove('is-hidden');
    } else {
      badge.classList.add('is-hidden');
    }
  }

  async function loadMonthlyProfitChart(generation = refreshGeneration) {
    if (monthlyProfitLoaded) return;
    const controller = startRequest('monthlyProfit');
    try {
      const res = await fetch(`/api/monthly-profit?full_history=true&marketplace=${currentMarketplace}`, { signal: controller.signal });
      const data = await res.json();
      if (!isCurrentRequest('monthlyProfit', controller, generation)) return;
      if (data.error) { showError(data.error); return; }
      setVisible('monthly-loading', false);
      setVisible('monthlyProfitChartWrap', true);
      renderMonthlyProfitViews(data.months || []);
      monthlyProfitLoaded = true;
      if (monthlyProfitChart) monthlyProfitChart.resize();
      if (monthlyProfitBarChart) monthlyProfitBarChart.resize();
    } catch (e) {
      if (!isCurrentRequest('monthlyProfit', controller, generation) || e.name === 'AbortError') return;
      showError('Aylık kâr trendi alınamadı: ' + e.message);
    }
  }

  // Aylık rakamların tam TL tablosu — grafikteki kısa etiketlere (₺46,8B)
  // ek olarak her ayın gerçek tutarlarını okunur biçimde verir. Yeniden
  // eskiye sıralı; devam eden ay "devam ediyor" etiketiyle işaretlenir.
  function renderMonthlyProfitTable(months) {
    const body = document.getElementById('monthlyProfitTableBody');
    if (!body) return;
    const curIdx = monthlyProfitCurrentMonthIndex(months);
    const rows = months.map((m, i) => {
      const rev = m.revenue || 0;
      const gross = m.trueGrossProfit || 0;
      const net = monthlyProfitRealNet(m);
      const [y, mo] = m.month.split('-');
      const label = new Date(y, mo - 1, 1).toLocaleDateString('tr-TR', { month: 'long', year: 'numeric' });
      const margin = rev ? `%${((net / rev) * 100).toFixed(1).replace('.', ',')}` : '–';
      return `<tr>
        <td>${label}${i === curIdx ? ' <span class="mpc-table-live">devam ediyor</span>' : ''}</td>
        <td>${monthlyProfitTlFmt.format(rev)}</td>
        <td>${monthlyProfitTlFmt.format(gross)}</td>
        <td class="${net < 0 ? 'is-neg' : 'is-pos'}">${monthlyProfitTlFmt.format(net)}</td>
        <td>${margin}</td>
      </tr>`;
    }).reverse();
    body.innerHTML = rows.join('');
    // Kargo faturası bekleyen siparişler: eskiden ayrı bir rozetti; artık Net Kâr
    // başlığındaki ⓘ ipucunda (net kâr bu aylarda eksik olabilir).
    const hint = document.getElementById('mpcNetHint');
    if (hint) {
      const incomplete = months.filter(m => m.incompleteData && m.ordersMissingCargo > 0);
      if (incomplete.length) {
        const total = incomplete.reduce((t, m) => t + (m.ordersMissingCargo || 0), 0);
        const names = incomplete.map(m => {
          const [y, mo] = m.month.split('-');
          return new Date(y, mo - 1, 1).toLocaleDateString('tr-TR', { month: 'short', year: '2-digit' });
        }).join(', ');
        hint.title = `${names}: ${total} sipariş kargo faturası bekliyor. Bu aylardaki net kâr eksik — kargo faturası gelmeyen siparişler toplama dahil edilmedi (0 olarak uydurulmadı).`;
        hint.setAttribute('aria-label', hint.title);
        hint.classList.remove('is-hidden');
      } else {
        hint.classList.add('is-hidden');
      }
    }
    setVisible('monthlyProfitTableWrap', true);
  }

  // Her iki görünümü de aynı `months` verisiyle inşa eder/günceller — tek
  // fetch, tek veri kaynağı; sadece Trend Analizi (line) ve Finansal Özet
  // (CFO grouped-bar) render fonksiyonları farklıdır.
  function renderMonthlyProfitViews(months) {
    // Sipariş verisi Nisan'da başlıyor; öncesindeki aylar yalnızca birkaç
    // hakediş kaydı taşıyor ve grafikte boş sütun olarak yer kaplıyordu.
    // Ciro, en iyi ayın %3'ünün altında kalan BAŞTAKİ aylar atlanır.
    const peak = Math.max(0, ...months.map(m => m.revenue || 0));
    let first = 0;
    while (first < months.length - 1 && (months[first].revenue || 0) < peak * 0.03) first++;
    months = months.slice(first);
    monthlyProfitMonths = months;

    renderMonthlyProfitInProgressBadge(months);

    renderMonthlyProfitLineChart(months);
    renderMonthlyProfitBarChart(months);
    renderMonthlyProfitTable(months);

    // 2. ve 3. grafik (gosterge-aylik-ek.js) aynı aylık veriyi bu olaydan alır.
    const extra = months.map(m => ({
      month: m.month,
      rev: m.revenue || 0,
      gross: m.trueGrossProfit || 0,
      net: monthlyProfitRealNet(m),
      inProgress: !!m.inProgress,
    }));
    window.__lalMonthlyProfit = extra;
    document.dispatchEvent(new CustomEvent('lal:monthly-profit', { detail: extra }));

    // Chart.js instance'ları artık hazır. Mevcut view state'ini
    // canvas'lara tekrar uygula.
    setMonthlyProfitView(monthlyProfitView);
  }

  // ================================================================
  // GRAFİK GÖRÜNÜM SWITCH
  // ================================================================
  // Tek state noktası. Event delegation kullanıldığı için butonların
  // DOM/render sırası veya Chart.js instance'larının hazır olup olmaması
  // switch davranışını etkilemez.
  function setMonthlyProfitView(view) {
    if (view !== 'trend' && view !== 'cfo') return;

    monthlyProfitView = view;

    const container = document.getElementById('monthlyProfitViewSwitch');
    const lineCanvas = document.getElementById('monthlyProfitChart');
    const barCanvas = document.getElementById('monthlyProfitBarChart');

    if (!container || !lineCanvas || !barCanvas) return;

    const isTrend = view === 'trend';
    const isCfo = view === 'cfo';

    // Buton state
    container.querySelectorAll('.mpc-view-switch-btn').forEach((btn) => {
      const active = btn.dataset.view === view;

      btn.classList.toggle('is-active', active);
      btn.classList.toggle('is-inactive', !active);
      btn.setAttribute('aria-selected', String(active));
    });

    // Canvas state
    lineCanvas.classList.toggle('is-hidden', !isTrend);
    barCanvas.classList.toggle('is-hidden', !isCfo);

    // display:none'den çıkan canvas için Chart.js yeniden ölçülmeli.
    requestAnimationFrame(() => {
      if (isTrend && monthlyProfitChart) {
        monthlyProfitChart.resize();
        monthlyProfitChart.update('none');
      }

      if (isCfo && monthlyProfitBarChart) {
        monthlyProfitBarChart.resize();
        monthlyProfitBarChart.update('none');
      }
    });
  }

  function initMonthlyProfitViewSwitch() {
    // Event delegation:
    // Buton sonradan oluşturulsa bile click çalışır.
    document.addEventListener('click', (event) => {
      const btn = event.target.closest('.mpc-view-switch-btn');
      if (!btn) return;

      const container = btn.closest('#monthlyProfitViewSwitch');
      if (!container) return;

      event.preventDefault();

      const view = btn.dataset.view;
      if (!view) return;

      setMonthlyProfitView(view);
    });

    // İlk görünüm.
    setMonthlyProfitView(monthlyProfitView);
  }

  initMonthlyProfitViewSwitch();

  // Ortak yardımcı: her iki grafik için de aynı ay etiketleri + aynı
  // {revenue, grossProfit, netProfit} veri dizileri (netProfit HER ZAMAN
  // realNetProfit'ten gelir, bkz. monthlyProfitRealNet).
  function monthlyProfitBuildData(months) {
    const labels = months.map(m => {
      const [y, mo] = m.month.split('-');
      return new Date(y, mo - 1, 1).toLocaleDateString('tr-TR', { month: 'short', year: '2-digit' });
    });
    const dataByKey = {
      revenue: months.map(m => m.revenue || 0),
      // FAZ 2 (15.09.2026): 'grossProfit' dataset key'i artık AYLIK
      // kırılımdaki gerçek trueGrossProfit'i (Ciro - sadece COGS) besliyor
      // -- eski (komisyon+kargo dahil) m.grossProfit ARTIK KULLANILMIYOR.
      grossProfit: months.map(m => m.trueGrossProfit || 0),
      netProfit: months.map(monthlyProfitRealNet),
    };
    return { labels, dataByKey };
  }

  // Aynı "bu ay = şu anki gerçek ay mı" mantığı renderMonthlyProfitInProgressBadge
  // ile birebir tutarlı olmalı (tek kaynak, iki yerde farklı hesap olmasın).
  // months son elemanı en güncel aydır; gerçek bugünün ay anahtarıyla
  // eşleşiyorsa index'i, eşleşmiyorsa -1 döner (etiket eşiği her yerde uygulanır).
  function monthlyProfitCurrentMonthIndex(months) {
    if (!months.length) return -1;
    const last = months[months.length - 1];
    const now = new Date();
    const currentKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    return last.month === currentKey ? months.length - 1 : -1;
  }

  // ---------- GRAFİK 1: Trend Analizi (sade 3-çizgi, mevcut yaklaşım) ----------
  function renderMonthlyProfitLineChart(months) {
    const { labels, dataByKey } = monthlyProfitBuildData(months);

    if (monthlyProfitChart) {
      monthlyProfitChart.data.labels = labels;
      monthlyProfitMetrics().forEach((m, i) => { monthlyProfitChart.data.datasets[i].data = dataByKey[m.key]; });
      monthlyProfitChart.update();
      return;
    }

    const metrics = monthlyProfitMetrics();
    const ctx = document.getElementById('monthlyProfitChart').getContext('2d');

    const datasets = metrics.map((m) => {
      const color = m.color();
      // Sadece "Net Kâr" (headline metrik) altı dolgulu — bu, 3 çizgi
      // arasında gözün nereye bakacağını görsel ağırlıkla belirginleştirir
      // (dolgu rengi token'lardan türetilen yarı saydam bir katman, ham
      // hex yok — bkz. tokens.css --lal-green-dim).
      const fillColor = m.key === 'netProfit' ? lalToken('--lal-green-dim') : color;
      return {
        type: 'line',
        label: m.label,
        data: dataByKey[m.key],
        borderColor: color,
        backgroundColor: m.fill ? fillColor : color,
        fill: m.fill ? 'origin' : false,
        borderWidth: m.width,
        borderDash: m.dash,
        tension: 0.3,
        pointStyle: m.pointStyle,
        pointRadius: 2.5,
        pointHoverRadius: 5,
        pointBackgroundColor: color,
        pointBorderColor: lalToken('--lal-surface'),
        pointBorderWidth: 1.5,
        clip: false,
        order: m.fill ? 0 : 1,
      };
    });

    monthlyProfitChart = new Chart(ctx, {
      data: { labels, datasets },
      options: {
        maintainAspectRatio: false,
        layout: { padding: { top: 12, right: 12, bottom: 4, left: 4 } },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false }, // Legend yerine mpc-selector chip'leri kullanılıyor.
          tooltip: { enabled: false, external: monthlyProfitExternalTooltip },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: lalToken('--lal-border-soft') },
            ticks: { font: { size: 13, family: LAL_CHART_FONT }, color: lalToken('--lal-text-muted'), padding: 8 },
          },
          // Tek eksen (brief final karar: dual-axis yok). Ciro/kâr ölçek
          // farkı, veri normalize edilerek değil; Ciro'nun en ince/en nötr
          // çizgi olarak düşük visual weight taşımasıyla ve metrik
          // seçiciyle istenen seriyi tek başına görebilme imkânıyla çözülüyor.
          y: {
            beginAtZero: true,
            grid: { color: lalToken('--lal-border-soft') },
            border: { display: false },
            ticks: { font: { size: 12.5, family: LAL_CHART_FONT }, color: lalToken('--lal-text-muted'), padding: 10, maxTicksLimit: 6, callback: (v) => monthlyProfitTlFmt.format(v) },
            afterFit(scale) { scale.width += 10; },
          },
        },
      },
      plugins: [monthlyProfitGuidePlugin],
    });

    renderMonthlyProfitSelector(metrics);
  }

  // ---------- GRAFİK 2: Finansal Özet (CFO tarzı gruplanmış sütun) ----------
  // Aynı monthlyProfitMetrics() renk/etiket kaynağını kullanır — marka
  // kimliği iki görünüm arasında birebir tutarlı (Ciro/Brüt Kâr/Net Kâr
  // her zaman aynı renk). Sade/düz dolgu (gradient yok), ince sütunlar,
  // gruplar arası boşluk — "executive reporting" hissi için abartısız.
  function renderMonthlyProfitBarChart(months) {
    const { labels, dataByKey } = monthlyProfitBuildData(months);

    if (monthlyProfitBarChart) {
      monthlyProfitBarChart.data.labels = labels;
      monthlyProfitMetrics().forEach((m, i) => { monthlyProfitBarChart.data.datasets[i].data = dataByKey[m.key]; });
      monthlyProfitBarChart.currentMonthIndex = monthlyProfitCurrentMonthIndex(months);
      monthlyProfitBarChart.update();
      return;
    }

    const metrics = monthlyProfitMetrics();
    const ctx = document.getElementById('monthlyProfitBarChart').getContext('2d');

    const datasets = metrics.map((m) => ({
      type: 'bar',
      label: m.label,
      data: dataByKey[m.key],
      // Klasik, düz sütun: Apple sistem renkleri (ciro mavi, brüt kâr turuncu,
      // net kâr yeşil), üst köşeler yuvarlak, cam/parlama efekti yok.
      // Devam eden ay soluk + kesikli kenarlı: tamamlanmış aylarla aynı
      // ağırlıkta görünüp yanlış kıyas yaptırmasın.
      backgroundColor: (c) => (c.chart.currentMonthIndex === c.dataIndex ? m.color() + '59' : m.color()),
      borderColor: (c) => (c.chart.currentMonthIndex === c.dataIndex ? m.color() : 'transparent'),
      borderWidth: (c) => (c.chart.currentMonthIndex === c.dataIndex ? 1.5 : 0),
      borderRadius: { topLeft: 6, topRight: 6, bottomLeft: 0, bottomRight: 0 },
      borderSkipped: false,
      categoryPercentage: 0.84,
      barPercentage: 0.94,
      maxBarThickness: 44,
    }));

    monthlyProfitBarChart = new Chart(ctx, {
      data: { labels, datasets },
      options: {
        maintainAspectRatio: false,
        layout: { padding: { top: 38, right: 12, bottom: 4, left: 4 } },
        interaction: { mode: 'index', intersect: false },
        // Sütun grupları arası nefes payı — "sıkışık e-ticaret bar chart"
        // hissi yerine daha ferah, kurumsal/analitik bir grid.
        categoryPercentage: 0.62,
        barPercentage: 0.86,
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false, external: monthlyProfitExternalTooltip },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: lalToken('--lal-border-soft') },
            ticks: { font: { size: 13, family: LAL_CHART_FONT }, color: lalToken('--lal-text-muted'), padding: 8 },
          },
          y: {
            beginAtZero: true,
            // En yüksek çubuğun (Ciro) üstündeki değer etiketi için pay —
            // etiket, ölçeğin en üst gridline'ına yapışıp kırpılmasın diye.
            grace: '8%',
            grid: { color: lalToken('--lal-border-soft') },
            border: { display: false },
            ticks: { font: { size: 12.5, family: LAL_CHART_FONT }, color: lalToken('--lal-text-muted'), padding: 10, maxTicksLimit: 6, callback: (v) => monthlyProfitTlFmt.format(v) },
            afterFit(scale) { scale.width += 10; },
          },
        },
      },
      plugins: [monthlyProfitBarValueLabels],
    });
    monthlyProfitBarChart.currentMonthIndex = monthlyProfitCurrentMonthIndex(months);

    renderMonthlyProfitSelector(metrics);
  }

  // Tema değişince (açık/koyu) her iki grafiğin renklerini de tazeler —
  // tek, üst-seviye kayıt (grafikler henüz kurulmamış olsa bile güvenli,
  // her biri kendi null-check'ini yapar).
  document.addEventListener('lal:theme-change', () => {
    const freshMetrics = monthlyProfitMetrics();
    if (monthlyProfitChart) {
      freshMetrics.forEach((m, i) => {
        const color = m.color();
        const ds = monthlyProfitChart.data.datasets[i];
        ds.borderColor = color;
        ds.backgroundColor = m.fill ? lalToken('--lal-green-dim') : color;
        ds.pointBackgroundColor = color;
        ds.pointBorderColor = lalToken('--lal-surface');
      });
      monthlyProfitChart.options.scales.x.border.color = lalToken('--lal-border-soft');
      monthlyProfitChart.options.scales.x.ticks.color = lalToken('--lal-text-muted');
      monthlyProfitChart.options.scales.y.grid.color = lalToken('--lal-border-soft');
      monthlyProfitChart.options.scales.y.ticks.color = lalToken('--lal-text-muted');
      monthlyProfitChart.update();
    }
    if (monthlyProfitBarChart) {
      monthlyProfitBarChart.options.scales.x.border.color = lalToken('--lal-border-soft');
      monthlyProfitBarChart.options.scales.x.ticks.color = lalToken('--lal-text-muted');
      monthlyProfitBarChart.options.scales.y.grid.color = lalToken('--lal-border-soft');
      monthlyProfitBarChart.options.scales.y.ticks.color = lalToken('--lal-text-muted');
      monthlyProfitBarChart.update('none');
      monthlyProfitBarChart.draw();
    }
    renderMonthlyProfitSelector(freshMetrics);
  });

  window.__lal_refreshMonthlyProfitChart = function () { monthlyProfitLoaded = false; loadMonthlyProfitChart(); };

  // ---------- Detaylı Grafikler (günlük satış/sipariş/iade) ----------
  function currentDailyChartDefaults() {
    const textMain = lalToken('--lal-text-main');
    const textMuted = lalToken('--lal-text-muted');
    const textFaint = lalToken('--lal-text-faint');
    const surface2 = lalToken('--lal-surface-2');
    const border = lalToken('--lal-border');
    const borderSoft = lalToken('--lal-border-soft');
    const green = lalToken('--lal-green');
    return {
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: surface2, borderColor: green, borderWidth: 1, padding: 12, cornerRadius: 10, titleColor: textMain, titleFont: { size: 13, weight: '600' }, bodyColor: textMain, bodyFont: { size: 13.5, weight: '600' }, displayColors: false }
      },
      scales: {
        x: { grid: { display: false }, border: { color: border }, ticks: { color: textFaint, font: { size: 11 } } },
        y: { beginAtZero: true, grid: { color: borderSoft }, border: { display: false }, ticks: { color: textMuted, font: { size: 11 } } },
      },
      interaction: { mode: 'index', intersect: false },
    };
  }
  const tlFmtShort = new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 0 });
  let salesChart, ordersChart, returnsChart;
  let chartDaily = [], chartReturnsDaily = [];

  function renderCharts(daily, returnsDaily) {
    chartDaily = daily;
    chartReturnsDaily = returnsDaily;
    const darkChartDefaults = currentDailyChartDefaults();
    const green = lalToken('--lal-green');
    const greenDim = lalToken('--lal-green-dim');
    const red = lalToken('--lal-red');
    const redDim = lalToken('--lal-red-dim');
    const surface = lalToken('--lal-surface');
    const labels = daily.map(d => fmtDateShort(d.date));
    const netData = daily.map(d => d.net_amount);
    const orderData = daily.map(d => d.order_count);
    const returnLabels = returnsDaily.map(d => fmtDateShort(d.date));
    const returnCounts = returnsDaily.map(d => d.claim_count);

    const salesCtx = document.getElementById('salesChart').getContext('2d');
    const salesGrad = salesCtx.createLinearGradient(0, 0, 0, 260);
    salesGrad.addColorStop(0, greenDim); salesGrad.addColorStop(1, 'transparent');
    if (salesChart) salesChart.destroy();
    salesChart = new Chart(salesCtx, {
      type: 'line',
      data: { labels, datasets: [{ label: 'Net Satış (₺)', data: netData, borderColor: green, backgroundColor: salesGrad, fill: true, tension: 0.4, cubicInterpolationMode: 'monotone', pointRadius: 0, pointHoverRadius: 6, pointHoverBackgroundColor: green, pointHoverBorderColor: surface, pointHoverBorderWidth: 2, borderWidth: 2.5, borderCapStyle: 'round', borderJoinStyle: 'round' }] },
      options: { ...darkChartDefaults, scales: { ...darkChartDefaults.scales, y: { ...darkChartDefaults.scales.y, beginAtZero: true } }, plugins: { ...darkChartDefaults.plugins, tooltip: { ...darkChartDefaults.plugins.tooltip, callbacks: { label: (ctx) => `Net Satış: ${tlFmtShort.format(ctx.parsed.y)}` } } } }
    });

    const ordersCtx = document.getElementById('ordersChart').getContext('2d');
    const ordersGrad = ordersCtx.createLinearGradient(0, 0, 0, 260);
    ordersGrad.addColorStop(0, green); ordersGrad.addColorStop(1, greenDim);
    if (ordersChart) ordersChart.destroy();
    ordersChart = new Chart(ordersCtx, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Sipariş Adedi', data: orderData, backgroundColor: ordersGrad, borderRadius: 4, borderSkipped: false }] },
      options: { ...darkChartDefaults, scales: { ...darkChartDefaults.scales, y: { ...darkChartDefaults.scales.y, beginAtZero: true, ticks: { ...darkChartDefaults.scales.y.ticks, precision: 0 } } }, plugins: { ...darkChartDefaults.plugins, tooltip: { ...darkChartDefaults.plugins.tooltip, callbacks: { label: (ctx) => `Sipariş: ${ctx.parsed.y} adet` } } } }
    });

    const returnsCtx = document.getElementById('returnsChart').getContext('2d');
    const returnsGrad = returnsCtx.createLinearGradient(0, 0, 0, 260);
    returnsGrad.addColorStop(0, red); returnsGrad.addColorStop(1, redDim);
    if (returnsChart) returnsChart.destroy();
    returnsChart = new Chart(returnsCtx, {
      type: 'bar',
      data: { labels: returnLabels, datasets: [{ label: 'İade Adedi', data: returnCounts, backgroundColor: returnsGrad, borderRadius: 4, borderSkipped: false }] },
      options: { ...darkChartDefaults, scales: { ...darkChartDefaults.scales, y: { ...darkChartDefaults.scales.y, beginAtZero: true, ticks: { ...darkChartDefaults.scales.y.ticks, precision: 0 } } }, plugins: { ...darkChartDefaults.plugins, tooltip: { ...darkChartDefaults.plugins.tooltip, callbacks: { label: (ctx) => `İade: ${ctx.parsed.y} adet` } } } }
    });
  }

  async function loadChartsSection(generation = refreshGeneration) {
    const controller = startRequest('charts');
    setVisible('charts-loading', true);
    setVisible('charts-content', false);
    try {
      const rangeParam = rangeQueryParam();
      const [salesRes, returnsRes] = await Promise.all([
        fetch(`/api/daily-sales?${rangeParam}`, { signal: controller.signal }),
        fetch(`/api/daily-returns?${rangeParam}`, { signal: controller.signal })
      ]);
      const salesData = await salesRes.json();
      const returnsData = await returnsRes.json();
      if (!isCurrentRequest('charts', controller, generation)) return;
      if (salesData.error) { showError(salesData.error); setVisible('charts-loading', false); return; }
      setVisible('charts-loading', false);
      setVisible('charts-content', true);
      renderCharts(salesData.daily, returnsData.daily || []);
      [salesChart, ordersChart, returnsChart].forEach(c => c && c.resize());
      if (returnsData.error) showError('İade verileri alınamadı: ' + returnsData.error);
    } catch (e) {
      if (!isCurrentRequest('charts', controller, generation) || e.name === 'AbortError') return;
      setVisible('charts-loading', false);
      showError('Beklenmeyen bir hata oluştu: ' + e.message);
    }
  }

  // ---------- Başlangıç ----------
  loadSummary();
  loadChartsSection();
  document.addEventListener('lal:data-refresh', function () {
    refreshGeneration += 1;
    monthlyProfitLoaded = false;
    loadSummary(refreshGeneration);
    loadChartsSection(refreshGeneration);
  });
  document.addEventListener('lal:theme-change', function () {
    if (chartDaily.length || chartReturnsDaily.length) renderCharts(chartDaily, chartReturnsDaily);
  });

  // Uyarı bandındaki "settlement bekleyen satırlar" linkinden gelindiyse,
  // sayfa yüklenince otomatik olarak o filtreyi uygula ve tabloya kaydır.
  const params = new URLSearchParams(location.search);
  if (params.get('linesFilter') === 'estimated') {
    const tryApply = () => {
      const cb = document.getElementById('lines-estimated-only');
      if (cb && linesCache.length) {
        cb.checked = true;
        applyLinesFilter();
        document.getElementById('details-charts').scrollIntoView({ behavior: 'smooth', block: 'start' });
      } else {
        setTimeout(tryApply, 300);
      }
    };
    tryApply();
  }
})();
