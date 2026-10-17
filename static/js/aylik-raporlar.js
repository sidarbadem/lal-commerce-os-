(function () {
  'use strict';
  var root = document.getElementById('mr-root');
  if (!root) return;

  var $ = function (id) { return document.getElementById(id); };
  var tryFmt = new Intl.NumberFormat('tr-TR', { style: 'currency', currency: 'TRY', maximumFractionDigits: 0 });
  var intFmt = new Intl.NumberFormat('tr-TR');
  var current = null;
  var activeSet = 'topQuantity';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function money(v) { return v == null ? '—' : tryFmt.format(v); }
  function num(v) { return v == null ? '—' : intFmt.format(v); }
  function delta(p, goodUp) {
    if (p == null) return '<span class="mr-delta is-none">—</span>';
    var cls = p === 0 ? '' : ((p > 0) === goodUp ? 'is-good' : 'is-bad');
    var sign = p > 0 ? '+' : '';
    return '<span class="mr-delta ' + cls + '">' + sign + p.toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + '%</span>';
  }

  function getJSON(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; });
    });
  }

  function renderKpis(v) {
    var defs = [
      ['netRevenue', 'Net ciro', money],
      ['netProfit', 'Net kâr', money],
      ['realNetProfit', 'Gerçek net kâr (sabit giderler sonrası)', money],
      ['orderCount', 'Sipariş', num],
      ['avgBasket', 'Ortalama sepet', money],
      ['unitCount', 'Satılan adet', num]
    ];
    $('mr-kpis').innerHTML = defs.map(function (d) {
      var prev = v.compare.prev[d[0]] || {};
      var yoy = v.compare.yoy[d[0]] || {};
      return '<div class="mr-kpi"><div class="mr-kpi-label">' + esc(d[1]) + '</div>' +
        '<div class="mr-kpi-value">' + d[2](v.metrics[d[0]]) + '</div>' +
        '<div class="mr-kpi-sub"><span>Önceki ay ' + delta(prev.pct, true) + '</span>' +
        '<span>Geçen yıl ' + delta(yoy.pct, true) + '</span></div></div>';
    }).join('');
  }

  function renderBreakdown(v) {
    var rows = [
      ['grossRevenue', 'Brüt ciro', true, false],
      ['returnAmount', 'İadeler', false, false],
      ['netRevenue', 'Net ciro', true, true],
      ['cogsTotal', 'Ürün maliyeti', false, false],
      ['commission', 'Komisyon', false, false],
      ['cargoTotal', 'Kargo', false, false],
      ['overheadTotal', 'Dönemsel giderler (iade, stopaj, platform bedeli)', false, false],
      ['netProfit', 'Net kâr', true, true],
      ['fixedExpenses', 'Sabit giderler', false, false],
      ['realNetProfit', 'Gerçek net kâr', true, true]
    ];
    var html = '<div class="mr-scroll"><table class="mr-table"><thead><tr><th>Kalem</th><th>Bu ay</th><th>Önceki ay</th><th>Değişim</th><th>Geçen yıl</th><th>Değişim</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var p = v.compare.prev[r[0]] || {};
      var y = v.compare.yoy[r[0]] || {};
      html += '<tr' + (r[3] ? ' class="is-strong"' : '') + '><td>' + esc(r[1]) + '</td>' +
        '<td>' + money(v.metrics[r[0]]) + '</td>' +
        '<td>' + money(p.prev) + '</td><td>' + delta(p.pct, r[2]) + '</td>' +
        '<td>' + money(y.prev) + '</td><td>' + delta(y.pct, r[2]) + '</td></tr>';
    });
    $('mr-breakdown').innerHTML = html + '</tbody></table></div>';
  }

  function bar(x, val, w, cls, y, y0) {
    var top = Math.min(y(val), y0);
    var h = Math.max(Math.abs(y(val) - y0), 1);
    return '<rect class="' + cls + '" x="' + x.toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + w.toFixed(1) +
      '" height="' + h.toFixed(1) + '" rx="3"><title>' + esc(money(val)) + '</title></rect>';
  }

  function renderChart(v) {
    var series = v.series || [];
    if (!series.length) { $('mr-chart').innerHTML = '<p class="panel-note">Grafik için rapor bulunamadı.</p>'; return; }
    var W = 720, H = 230, pl = 8, pr = 8, pt = 16, pb = 34;
    var vals = [1, 0];
    series.forEach(function (s) { vals.push(s.grossRevenue || 0, s.netProfit || 0); });
    var max = Math.max.apply(null, vals), min = Math.min.apply(null, vals);
    var span = (max - min) || 1;
    var y = function (val) { return pt + (max - val) / span * (H - pt - pb); };
    var y0 = y(0);
    var slot = (W - pl - pr) / series.length;
    var bw = Math.min(22, slot / 2 - 3);
    var out = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="mr-chart" role="img" aria-label="Son 12 ay ciro ve net kâr">';
    out += '<line class="mr-axis" x1="' + pl + '" x2="' + (W - pr) + '" y1="' + y0.toFixed(1) + '" y2="' + y0.toFixed(1) + '"/>';
    series.forEach(function (s, i) {
      var cx = pl + slot * i + slot / 2;
      var isCur = s.period === v.period;
      var profit = s.netProfit || 0;
      out += bar(cx - bw - 1, s.grossRevenue || 0, bw, 'mr-bar-rev' + (isCur ? ' is-current' : ''), y, y0);
      out += bar(cx + 1, profit, bw, 'mr-bar-profit' + (profit < 0 ? ' is-neg' : ''), y, y0);
      out += '<text class="mr-xlabel' + (isCur ? ' is-current' : '') + '" x="' + cx.toFixed(1) + '" y="' + (H - 12) + '">' +
        esc(String(s.label || s.period).split(' ')[0].slice(0, 3)) + '</text>';
    });
    $('mr-chart').innerHTML = out + '</svg>';
  }

  function renderMarketplaces(v) {
    var mp = v.byMarketplace;
    var labels = { trendyol: 'Trendyol', hepsiburada: 'Hepsiburada' };
    var items = [];
    if (Array.isArray(mp)) {
      mp.forEach(function (x) { items.push([x.marketplace, x]); });
    } else if (mp && typeof mp === 'object') {
      Object.keys(mp).forEach(function (k) { items.push([k, mp[k]]); });
    }
    var rows = items.map(function (it) {
      var d = it[1] || {};
      var rev = d.grossRevenue != null ? d.grossRevenue : d.revenue;
      var profit = d.netProfit != null ? d.netProfit : d.grossProfit;
      return { name: labels[it[0]] || it[0], rev: rev, profit: profit };
    }).filter(function (r) { return typeof r.rev === 'number' || typeof r.profit === 'number'; });
    $('mr-mp-panel').hidden = !rows.length;
    if (!rows.length) return;
    var html = '<div class="mr-scroll"><table class="mr-table"><thead><tr><th>Pazaryeri</th><th>Brüt ciro</th><th>Kâr</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      html += '<tr><td>' + esc(r.name) + '</td><td>' + money(r.rev) + '</td><td>' + money(r.profit) + '</td></tr>';
    });
    $('mr-mp').innerHTML = html + '</tbody></table></div>';
  }

  function renderProducts() {
    if (!current) return;
    var rows = current[activeSet] || [];
    if (!rows.length) {
      $('mr-products').innerHTML = '<p class="panel-note">' +
        (activeSet === 'lossMaking' ? 'Bu ay zarar eden ürün yok.' : 'Kayıt yok.') + '</p>';
      return;
    }
    var html = '<div class="mr-scroll"><table class="mr-table"><thead><tr><th>Ürün</th><th>Adet</th><th>Ciro</th><th>Kâr</th><th>Marj</th><th>Ciro (önceki aya göre)</th></tr></thead><tbody>';
    rows.forEach(function (p) {
      var margin = p.margin == null ? '—' : (p.margin * 100).toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + '%';
      html += '<tr><td>' + esc(p.productName || p.sku || '—') + (p.sku ? '<span class="mr-sku">' + esc(p.sku) + '</span>' : '') + '</td>' +
        '<td>' + num(p.quantity) + '</td><td>' + money(p.revenue) + '</td><td>' + money(p.profit) + '</td>' +
        '<td>' + margin + '</td><td>' + delta(p.revenuePct, true) + '</td></tr>';
    });
    $('mr-products').innerHTML = html + '</tbody></table></div>';
  }

  function renderWarnings(v) {
    var dq = v.dataQuality || {};
    var out = [];
    if (dq.ordersMissingCargo > 0) {
      out.push('Kargo faturası bekleyen ' + dq.ordersMissingCargo + ' sipariş var; net kâr tahmini kargo tutarıyla hesaplandı, fatura geldikçe rapor güncellenir.');
    }
    if (dq.linesEstimated > 0) {
      out.push(dq.linesEstimated + ' satırın hakedişi henüz kesinleşmedi (tahmini değerle hesaplandı).');
    }
    if (dq.skusMissingCost && dq.skusMissingCost.length) {
      out.push('Maliyeti girilmemiş ürün var: ' + dq.skusMissingCost.slice(0, 6).join(', ') + (dq.skusMissingCost.length > 6 ? ' …' : ''));
    }
    $('mr-warnings').innerHTML = out.map(function (t) { return '<div class="mr-warn">' + esc(t) + '</div>'; }).join('');
  }

  function renderReport(v) {
    current = v;
    var badge = $('mr-status');
    badge.hidden = false;
    badge.textContent = v.status === 'kesin' ? 'Kesin' : 'Taslak';
    badge.className = 'mr-badge ' + (v.status === 'kesin' ? 'is-final' : 'is-draft');
    $('mr-refresh').hidden = false;
    $('mr-note').textContent = v.generatedAt ? 'Son hesaplama: ' + v.generatedAt : '';
    $('mr-empty').hidden = true;
    $('mr-content').hidden = false;
    renderWarnings(v);
    renderKpis(v);
    renderBreakdown(v);
    renderChart(v);
    renderMarketplaces(v);
    renderProducts();
  }

  function loadPeriod(period) {
    $('mr-note').textContent = 'Yükleniyor…';
    getJSON('/api/monthly-reports/' + encodeURIComponent(period)).then(function (res) {
      if (!res.ok) {
        $('mr-note').textContent = (res.body && res.body.error) || 'Rapor yüklenemedi.';
        return;
      }
      renderReport(res.body);
    }).catch(function () { $('mr-note').textContent = 'Bağlantı hatası.'; });
  }

  function init() {
    getJSON('/api/monthly-reports').then(function (res) {
      var items = (res.body && res.body.items) || [];
      if (!items.length) {
        $('mr-note').textContent = '';
        $('mr-period').hidden = true;
        $('mr-empty').hidden = false;
        return;
      }
      $('mr-period').innerHTML = items.map(function (it) {
        return '<option value="' + esc(it.period) + '">' + esc(it.label) + (it.status === 'taslak' ? ' (taslak)' : '') + '</option>';
      }).join('');
      loadPeriod(items[0].period);
    }).catch(function () { $('mr-note').textContent = 'Bağlantı hatası.'; });
  }

  $('mr-period').addEventListener('change', function () { loadPeriod(this.value); });

  $('mr-refresh').addEventListener('click', function () {
    var btn = this;
    var period = $('mr-period').value;
    if (!period) return;
    btn.disabled = true;
    $('mr-note').textContent = 'Yeniden hesaplanıyor…';
    getJSON('/api/monthly-reports/' + encodeURIComponent(period) + '/refresh', { method: 'POST' }).then(function (res) {
      btn.disabled = false;
      if (!res.ok) { $('mr-note').textContent = (res.body && res.body.error) || 'Hesaplama başarısız.'; return; }
      loadPeriod(period);
    }).catch(function () { btn.disabled = false; $('mr-note').textContent = 'Bağlantı hatası.'; });
  });

  $('mr-tabs').addEventListener('click', function (e) {
    var t = e.target.closest('.mr-tab');
    if (!t) return;
    activeSet = t.getAttribute('data-set');
    Array.prototype.forEach.call(this.querySelectorAll('.mr-tab'), function (b) { b.classList.toggle('is-active', b === t); });
    renderProducts();
  });

  init();
})();
