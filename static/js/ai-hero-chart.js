(function () {
  'use strict';
  // AI Genel Bakış — son 30 gün günlük satış grafiği (canvas).
  // Modlar: total (satış + 7 gün ort.), platform (Trendyol/Hepsiburada/Diğer
  // yığılmış alan), profit (satış + kâr, aynı TL ekseni).
  // Veri: 'lal:daily-sales' (daily-sales satırları, by_marketplace dahil) ve
  // 'lal:daily-profit' ({ 'YYYY-MM-DD': kâr }) event'leri.
  var hero = document.querySelector('.greeting-hero');
  var cv = document.getElementById('ai-chart-cv');
  var chip = document.getElementById('ai-chart-chip');
  var legend = document.getElementById('ai-chart-legend');
  var tip = document.getElementById('ai-chart-tip');
  var modeBox = document.getElementById('ai-chart-modes');
  if (!hero || !cv) return;
  var RM = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var cx = cv.getContext('2d');
  var MON = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
  var DAY = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];
  var pts = [], t0 = performance.now(), hover = null, visible = true, dirty = true;
  var rawDaily = null, profitMap = null;
  var mode = 'total';
  try { mode = localStorage.getItem('lal-ai-chart-mode') || 'total'; } catch (e) {}
  var clamp = function (x) { return Math.min(1, Math.max(0, x)); };
  var ease = function (t) { return 1 - Math.pow(1 - t, 3); };
  var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
  var key = function (d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); };
  var fmt = function (v) { return '₺' + Math.round(v).toLocaleString('tr-TR'); };
  var short = function (v) { return v >= 1000 ? '₺' + Math.round(v / 1000) + ' bin' : '₺' + Math.round(v); };
  var css = function (n) { return getComputedStyle(hero).getPropertyValue(n).trim(); };
  var esc = function (s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; };

  function mp() {
    return (typeof currentMarketplace !== 'undefined' && currentMarketplace) ? currentMarketplace : 'all';
  }

  // TEK trend formülü: bugün vs. önceki 7 TAKVİM gününün ortalaması (satışsız
  // günler 0 olarak dahil). KPI kartı, brifing ve "Bugün neden böyle?" de bunu
  // kullanır — eskiden KPI yalnızca satış olan günlerin ortalamasını aldığı
  // için grafikle farklı yüzde gösteriyordu.
  window.lalSalesTrend = function (valueByDate, today) {
    today = today || new Date();
    var sum = 0;
    for (var i = 1; i <= 7; i++) {
      var d = new Date(today); d.setDate(d.getDate() - i);
      sum += valueByDate[key(d)] || 0;
    }
    var avg = sum / 7, cur = valueByDate[key(today)] || 0;
    return { today: cur, avg: avg, pct: avg > 0 ? (cur / avg - 1) * 100 : null };
  };

  function valueFor(row, which) {
    if (!row) return 0;
    var m = which || mp();
    if (m === 'all') return row.net_amount || 0;
    return (row.by_marketplace && row.by_marketplace[m]) || 0;
  }

  function rebuild() {
    if (!rawDaily) return;
    var rows = {};
    rawDaily.forEach(function (d) { rows[(d.date || '').slice(0, 10)] = d; });
    var m = mp();
    pts = [];
    for (var i = 29; i >= 0; i--) {
      var d = new Date(); d.setDate(d.getDate() - i);
      var r = rows[key(d)];
      var bm = (r && r.by_marketplace) || {};
      pts.push({
        d: d, k: key(d), v: valueFor(r, m), ma: 0,
        ty: bm.trendyol || 0, hb: bm.hepsiburada || 0, ot: (bm.manuel || 0),
        orders: r ? (r.order_count || 0) - (r.cancelled_count || 0) : 0,
        pr: profitMap ? (profitMap[key(d)] !== undefined ? profitMap[key(d)] : null) : null
      });
    }
    pts.forEach(function (p, i) {
      var s = 0, n = 0;
      for (var j = Math.max(0, i - 6); j <= i; j++) { s += pts[j].v; n++; }
      p.ma = s / n;
    });
    var map = {};
    pts.forEach(function (p) { map[p.k] = p.v; });
    var tr = window.lalSalesTrend(map);
    var up = tr.pct === null || tr.pct >= 0;
    hero.classList.toggle('ai-up', up);
    hero.classList.toggle('ai-dn', !up);
    if (chip) {
      chip.textContent = tr.pct === null ? '' : (tr.pct >= 0 ? '▲ %' : '▼ %') + Math.abs(tr.pct).toFixed(1).replace('.', ',') +
        ' · 7 günlük ortalamanın ' + (tr.pct >= 0 ? 'üstünde' : 'altında');
      chip.className = 'ai-chart-chip ' + (up ? 'is-up' : 'is-down');
    }
    renderLegend();
    t0 = performance.now(); dirty = true;
  }

  function renderLegend() {
    if (!legend) return;
    var items;
    if (mode === 'platform' && mp() === 'all') {
      items = [['--ai-ty', 'Trendyol', 'sq'], ['--ai-hb', 'Hepsiburada', 'sq']];
      if (pts.some(function (p) { return p.ot > 0; })) items.push(['--ai-ot', 'Diğer (manuel)', 'sq']);
    } else if (mode === 'profit') {
      items = [['--ai-lc', 'Satış', 'ln'], ['--ai-pr', 'Kâr', 'ln']];
    } else {
      items = [['--ai-lc', 'Satış', 'ln'], ['--lal-text-faint', '7 gün ort.', 'dash']];
    }
    items.push(['--lal-text-faint', 'Sipariş yok', 'ring']);
    legend.innerHTML = items.map(function (it) {
      return '<span class="ai-lg"><i class="ai-lg-' + it[2] + '" style="--c:var(' + it[0] + ')"></i>' + esc(it[1]) + '</span>';
    }).join('');
  }

  function setMode(m) {
    mode = m;
    try { localStorage.setItem('lal-ai-chart-mode', m); } catch (e) {}
    if (modeBox) modeBox.querySelectorAll('button').forEach(function (b) {
      var on = b.dataset.mode === m;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-pressed', String(on));
    });
    renderLegend();
    t0 = performance.now(); dirty = true;
  }
  if (modeBox) {
    modeBox.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-mode]');
      if (b) setMode(b.dataset.mode);
    });
  }
  setMode(mode);

  document.addEventListener('lal:daily-sales', function (e) { rawDaily = e.detail || []; rebuild(); });
  document.addEventListener('lal:daily-profit', function (e) { profitMap = e.detail || null; rebuild(); });
  document.addEventListener('lal:theme-change', function () { dirty = true; });
  if (window.__lalDailySales) { rawDaily = window.__lalDailySales; rebuild(); }

  function pick(e) {
    var r = cv.getBoundingClientRect();
    var W = r.width, pl = 8, pr = 56;
    var i = Math.round(clamp(((e.clientX - r.left) - pl) / (W - pl - pr)) * 29);
    if (hover !== i) { hover = i; dirty = true; showTip(i, e.clientX - r.left, r.width); }
  }
  cv.addEventListener('mousemove', pick);
  cv.addEventListener('mouseleave', function () { hover = null; dirty = true; if (tip) tip.hidden = true; });

  function showTip(i, x, W) {
    if (!tip || !pts[i]) return;
    var p = pts[i];
    var rows = [];
    var head = DAY[p.d.getDay()] + ', ' + p.d.getDate() + ' ' + MON[p.d.getMonth()];
    rows.push('<div class="ai-tip-h">' + head + '</div>');
    if (p.v === 0 && p.orders === 0) {
      rows.push('<div class="ai-tip-r"><span>Sipariş yok</span></div>');
    } else {
      rows.push('<div class="ai-tip-r"><span>Satış</span><b>' + fmt(p.v) + '</b></div>');
      if (mp() === 'all' && (p.ty || p.hb || p.ot)) {
        rows.push('<div class="ai-tip-r sub"><span><i style="background:var(--ai-ty)"></i>Trendyol</span><b>' + fmt(p.ty) + '</b></div>');
        rows.push('<div class="ai-tip-r sub"><span><i style="background:var(--ai-hb)"></i>Hepsiburada</span><b>' + fmt(p.hb) + '</b></div>');
        if (p.ot) rows.push('<div class="ai-tip-r sub"><span><i style="background:var(--ai-ot)"></i>Diğer</span><b>' + fmt(p.ot) + '</b></div>');
      }
      if (p.pr !== null) rows.push('<div class="ai-tip-r"><span>Kâr</span><b>' + fmt(p.pr) + '</b></div>');
      rows.push('<div class="ai-tip-r"><span>Sipariş</span><b>' + p.orders + '</b></div>');
    }
    rows.push('<div class="ai-tip-r muted"><span>7 gün ort.</span><b>' + fmt(p.ma) + '</b></div>');
    tip.innerHTML = rows.join('');
    tip.hidden = false;
    var tw = tip.offsetWidth;
    var left = x + 14;
    if (left + tw > W - 4) left = x - tw - 14;
    tip.style.left = Math.max(4, left) + 'px';
  }

  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { visible = es[0].isIntersecting; if (visible) dirty = true; }).observe(cv);
  }
  window.addEventListener('resize', function () { dirty = true; });

  function smooth(X, Y, vals) {
    cx.moveTo(X(0), Y(vals[0]));
    for (var i = 1; i < vals.length; i++) {
      var x0 = X(i - 1), y0 = Y(vals[i - 1]), x1 = X(i), y1 = Y(vals[i]);
      cx.quadraticCurveTo(x0, y0, (x0 + x1) / 2, (y0 + y1) / 2);
    }
    cx.lineTo(X(vals.length - 1), Y(vals[vals.length - 1]));
  }

  function draw(now) {
    var d = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
    if (!W || pts.length < 2) return false;
    if (cv.width !== Math.round(W * d) || cv.height !== Math.round(H * d)) { cv.width = Math.round(W * d); cv.height = Math.round(H * d); }
    cx.setTransform(d, 0, 0, d, 0, 0);
    cx.clearRect(0, 0, W, H);
    var pl = 8, pr = 56, pt = 14, pb = 26;
    var lc = css('--ai-lc') || '#c4574f', mu = css('--lal-text-faint') || '#999', fg = css('--lal-text-main') || '#222', sf = css('--lal-surface') || '#fff';
    var cTy = css('--ai-ty'), cHb = css('--ai-hb'), cOt = css('--ai-ot'), cPr = css('--ai-pr');
    var platform = mode === 'platform' && mp() === 'all';
    var vals = pts.map(function (p) { return p.v; });
    var maxv = Math.max.apply(null, pts.map(function (p) {
      return Math.max(p.v, mode === 'total' ? p.ma : 0, mode === 'profit' && p.pr ? p.pr : 0);
    }).concat([1])) * 1.12;
    var minv = mode === 'profit' ? Math.min(0, Math.min.apply(null, pts.map(function (p) { return p.pr || 0; })) * 1.12) : 0;
    var X = function (i) { return pl + (W - pl - pr) * i / 29; };
    var Y = function (v) { return H - pb - (H - pt - pb) * (v - minv) / (maxv - minv); };
    var step = Math.pow(10, Math.floor(Math.log10((maxv - minv) / 3))), m = (maxv - minv) / 3 / step;
    step *= m > 5 ? 5 : m > 2 ? 2 : 1;
    cx.font = '12px -apple-system, system-ui, sans-serif';
    for (var g = Math.ceil(minv / step) * step; g < maxv; g += step) {
      cx.globalAlpha = g === 0 ? .45 : .2; cx.strokeStyle = mu; cx.lineWidth = 1;
      cx.beginPath(); cx.moveTo(pl, Math.round(Y(g)) + .5); cx.lineTo(W - pr, Math.round(Y(g)) + .5); cx.stroke();
      if (g !== 0) { cx.globalAlpha = .95; cx.fillStyle = mu; cx.textAlign = 'left'; cx.fillText((g < 0 ? '−' : '') + short(Math.abs(g)), W - pr + 8, Y(g) + 4); }
    }
    cx.globalAlpha = 1; cx.fillStyle = mu; cx.textAlign = 'center';
    [0, 7, 14, 21, 29].forEach(function (i) {
      var p = pts[i]; cx.fillText(p.d.getDate() + ' ' + MON[p.d.getMonth()], Math.min(Math.max(X(i), 22), W - pr - 6), H - 7);
    });

    var gr = RM ? 1 : ease(clamp((now - t0) / 900));
    cx.save();
    cx.beginPath(); cx.rect(0, 0, pl + (W - pl - pr) * gr + 1, H); cx.clip();
    cx.lineJoin = 'round'; cx.lineCap = 'round';

    if (platform) {
      // Yığılmış alan: Trendyol altta, Hepsiburada üstünde, Diğer en üstte.
      var layers = [
        { c: cTy, f: function (p) { return p.ty; } },
        { c: cHb, f: function (p) { return p.hb; } },
        { c: cOt, f: function (p) { return p.ot; } }
      ];
      var base = pts.map(function () { return 0; });
      layers.forEach(function (L) {
        var top = pts.map(function (p, i) { return base[i] + L.f(p); });
        if (top.every(function (v, i) { return v === base[i]; })) return;
        cx.beginPath();
        cx.moveTo(X(0), Y(top[0]));
        for (var i = 1; i < 30; i++) cx.lineTo(X(i), Y(top[i]));
        for (var j = 29; j >= 0; j--) cx.lineTo(X(j), Y(base[j]));
        cx.closePath();
        cx.globalAlpha = .55; cx.fillStyle = L.c; cx.fill();
        cx.globalAlpha = 1;
        cx.beginPath(); cx.moveTo(X(0), Y(top[0]));
        for (var k = 1; k < 30; k++) cx.lineTo(X(k), Y(top[k]));
        cx.strokeStyle = L.c; cx.lineWidth = 2; cx.stroke();
        base = top;
      });
    } else {
      if (mode === 'total') {
        cx.globalAlpha = .55; cx.strokeStyle = mu; cx.lineWidth = 1.5; cx.setLineDash([2, 5]);
        cx.beginPath(); smooth(X, Y, pts.map(function (p) { return p.ma; })); cx.stroke();
        cx.setLineDash([]); cx.globalAlpha = 1;
      }
      var grad = cx.createLinearGradient(0, pt, 0, H - pb);
      grad.addColorStop(0, lc + '40'); grad.addColorStop(1, lc + '00');
      cx.beginPath(); smooth(X, Y, vals);
      cx.lineTo(X(29), Y(0)); cx.lineTo(X(0), Y(0)); cx.closePath(); cx.fillStyle = grad; cx.fill();
      cx.beginPath(); smooth(X, Y, vals);
      cx.strokeStyle = lc; cx.lineWidth = 2.5; cx.stroke();
      if (mode === 'profit' && pts.some(function (p) { return p.pr !== null; })) {
        cx.beginPath(); smooth(X, Y, pts.map(function (p) { return p.pr || 0; }));
        cx.strokeStyle = cPr; cx.lineWidth = 2; cx.stroke();
      }
    }
    cx.restore();

    // Siparişsiz günler: taban çizgisinde içi boş halka.
    pts.forEach(function (p, i) {
      if (p.v === 0 && p.orders === 0) {
        cx.beginPath(); cx.arc(X(i), Y(0), 4, 0, 7);
        cx.fillStyle = sf; cx.fill(); cx.lineWidth = 1.5; cx.strokeStyle = mu; cx.stroke();
      }
    });

    if (gr >= 1 && !platform) {
      var tx = X(29), ty = Y(pts[29].v);
      cx.beginPath(); cx.arc(tx, ty, 12, 0, 7); cx.fillStyle = lc; cx.globalAlpha = .16; cx.fill(); cx.globalAlpha = 1;
      cx.beginPath(); cx.arc(tx, ty, 5, 0, 7); cx.fillStyle = lc; cx.fill(); cx.lineWidth = 2; cx.strokeStyle = sf; cx.stroke();
    }
    if (hover !== null && pts[hover]) {
      var p = pts[hover], px = X(hover);
      cx.strokeStyle = fg; cx.globalAlpha = .25; cx.lineWidth = 1;
      cx.beginPath(); cx.moveTo(Math.round(px) + .5, pt - 4); cx.lineTo(Math.round(px) + .5, H - pb); cx.stroke(); cx.globalAlpha = 1;
      var dot = function (v, c) { cx.beginPath(); cx.arc(px, Y(v), 4.5, 0, 7); cx.fillStyle = c; cx.fill(); cx.lineWidth = 2; cx.strokeStyle = sf; cx.stroke(); };
      if (platform) dot(p.ty + p.hb + p.ot, fg);
      else {
        dot(p.v, lc);
        if (mode === 'profit' && p.pr !== null) dot(p.pr, cPr);
      }
    }
    return gr < 1;
  }
  if (window.ResizeObserver) new ResizeObserver(function () { dirty = true; }).observe(cv);
  // Yalnızca bir şey değiştiğinde (veri, hover, tema, boyut, giriş animasyonu)
  // yeniden çizer; boşta CPU harcamaz.
  (function loop(now) {
    if (visible && dirty) dirty = draw(now) === true;
    requestAnimationFrame(loop);
  })(performance.now());
})();
