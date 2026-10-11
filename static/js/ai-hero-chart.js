(function () {
  'use strict';
  var hero = document.querySelector('.greeting-hero');
  var cv = document.getElementById('ai-chart-cv');
  var chip = document.getElementById('ai-chart-chip');
  if (!hero || !cv) return;
  var RM = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var cx = cv.getContext('2d');
  var MON = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'];
  var pts = [], t0 = performance.now(), mxc = null, visible = true;
  var clamp = function (x) { return Math.min(1, Math.max(0, x)); };
  var ease = function (t) { return 1 - Math.pow(1 - t, 3); };
  var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
  var key = function (d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); };
  var fmt = function (v) { return '₺' + Math.round(v).toLocaleString('tr-TR'); };
  var short = function (v) { return v >= 1000 ? '₺' + Math.round(v / 1000) + ' bin' : '₺' + Math.round(v); };
  var css = function (n) { return getComputedStyle(hero).getPropertyValue(n).trim(); };

  function setData(daily) {
    var map = {};
    (daily || []).forEach(function (d) { map[(d.date || '').slice(0, 10)] = d.net_amount || 0; });
    pts = [];
    for (var i = 29; i >= 0; i--) {
      var d = new Date(); d.setDate(d.getDate() - i);
      pts.push({ d: d, v: map[key(d)] || 0, ma: 0 });
    }
    pts.forEach(function (p, i) {
      var s = 0, n = 0;
      for (var j = Math.max(0, i - 6); j <= i; j++) { s += pts[j].v; n++; }
      p.ma = s / n;
    });
    var today = pts[29].v;
    var avg = pts.slice(22, 29).reduce(function (a, p) { return a + p.v; }, 0) / 7;
    var pct = avg ? (today / avg - 1) * 100 : 0;
    hero.classList.toggle('ai-up', pct >= 0);
    hero.classList.toggle('ai-dn', pct < 0);
    if (chip) {
      chip.textContent = (pct >= 0 ? '▲ %' : '▼ %') + Math.abs(pct).toFixed(1).replace('.', ',') +
        ' · 7 günlük ortalamanın ' + (pct >= 0 ? 'üstünde' : 'altında');
    }
    t0 = performance.now();
  }
  document.addEventListener('lal:daily-sales', function (e) { setData(e.detail); });
  if (window.__lalDailySales) setData(window.__lalDailySales);

  cv.addEventListener('mousemove', function (e) { var r = cv.getBoundingClientRect(); mxc = (e.clientX - r.left) / r.width; });
  cv.addEventListener('mouseleave', function () { mxc = null; });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { visible = es[0].isIntersecting; }).observe(cv);
  }

  function draw(now) {
    var d = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
    if (!W || pts.length < 2) return;
    if (cv.width !== Math.round(W * d)) { cv.width = W * d; cv.height = H * d; }
    cx.setTransform(d, 0, 0, d, 0, 0);
    cx.clearRect(0, 0, W, H);
    var pl = 8, pr = 52, pt = 18, pb = 26;
    var lc = css('--ai-lc') || '#c4574f', mu = css('--lal-text-faint') || '#999', fg = css('--lal-text-main') || '#222', sf = css('--lal-surface') || '#fff';
    var max = Math.max.apply(null, pts.map(function (p) { return Math.max(p.v, p.ma); }).concat([1])) * 1.12;
    var X = function (i) { return pl + (W - pl - pr) * i / 29; };
    var Y = function (v) { return H - pb - (H - pt - pb) * v / max; };
    var step = Math.pow(10, Math.floor(Math.log10(max / 3))), m = max / 3 / step;
    step *= m > 5 ? 5 : m > 2 ? 2 : 1;
    cx.font = '12px -apple-system, system-ui, sans-serif';
    for (var g = step; g < max; g += step) {
      cx.globalAlpha = .22; cx.strokeStyle = mu; cx.lineWidth = 1;
      cx.beginPath(); cx.moveTo(pl, Y(g)); cx.lineTo(W - pr, Y(g)); cx.stroke();
      cx.globalAlpha = .9; cx.fillStyle = mu; cx.textAlign = 'left'; cx.fillText(short(g), W - pr + 8, Y(g) + 4);
    }
    cx.globalAlpha = 1; cx.fillStyle = mu; cx.textAlign = 'center';
    [0, 7, 14, 21, 29].forEach(function (i) {
      var p = pts[i]; cx.fillText(p.d.getDate() + ' ' + MON[p.d.getMonth()], Math.min(Math.max(X(i), 22), W - pr - 6), H - 7);
    });
    var gr = RM ? 1 : ease(clamp((now - t0) / 1200));
    cx.save();
    cx.beginPath(); cx.rect(0, 0, pl + (W - pl - pr) * gr + 1, H); cx.clip();
    function path(get) {
      cx.beginPath(); cx.moveTo(X(0), Y(get(pts[0])));
      for (var i = 1; i < 30; i++) {
        var x0 = X(i - 1), y0 = Y(get(pts[i - 1])), x1 = X(i), y1 = Y(get(pts[i]));
        cx.quadraticCurveTo(x0, y0, (x0 + x1) / 2, (y0 + y1) / 2);
      }
      cx.lineTo(X(29), Y(get(pts[29])));
    }
    cx.globalAlpha = .45; cx.strokeStyle = mu; cx.lineWidth = 1.5; cx.setLineDash([2, 5]); cx.lineCap = 'round';
    path(function (p) { return p.ma; }); cx.stroke(); cx.setLineDash([]); cx.globalAlpha = 1;
    var grad = cx.createLinearGradient(0, pt, 0, H - pb);
    grad.addColorStop(0, lc + '4d'); grad.addColorStop(1, lc + '00');
    path(function (p) { return p.v; });
    cx.lineTo(X(29), H - pb); cx.lineTo(X(0), H - pb); cx.closePath(); cx.fillStyle = grad; cx.fill();
    path(function (p) { return p.v; });
    cx.strokeStyle = lc; cx.lineWidth = 2.5; cx.lineJoin = 'round'; cx.stroke();
    cx.restore();
    if (gr >= 1) {
      var tx = X(29), ty = Y(pts[29].v);
      cx.beginPath(); cx.arc(tx, ty, 13, 0, 7); cx.fillStyle = lc; cx.globalAlpha = .16; cx.fill(); cx.globalAlpha = 1;
      cx.beginPath(); cx.arc(tx, ty, 6, 0, 7); cx.fillStyle = lc; cx.fill(); cx.lineWidth = 2.5; cx.strokeStyle = sf; cx.stroke();
    }
    if (mxc !== null) {
      var i = Math.round(clamp((mxc * W - pl) / (W - pl - pr)) * 29), p = pts[i], px = X(i), py = Y(p.v);
      cx.strokeStyle = fg; cx.globalAlpha = .25; cx.lineWidth = 1;
      cx.beginPath(); cx.moveTo(px, pt - 4); cx.lineTo(px, H - pb); cx.stroke(); cx.globalAlpha = 1;
      cx.beginPath(); cx.arc(px, py, 5, 0, 7); cx.fillStyle = fg; cx.fill(); cx.lineWidth = 2; cx.strokeStyle = sf; cx.stroke();
      cx.fillStyle = fg; cx.font = '600 13px -apple-system, system-ui, sans-serif';
      cx.textAlign = px > W * .6 ? 'right' : 'left';
      cx.fillText(p.d.getDate() + ' ' + MON[p.d.getMonth()] + ' · ' + fmt(p.v), px + (px > W * .6 ? -10 : 10), 12);
    }
  }
  (function loop(now) { if (visible) draw(now); requestAnimationFrame(loop); })(performance.now());
})();
