// Finansal Performans'ın altındaki 2. ve 3. grafik:
//  2) Ay ayrıntısı  — iç içe kapsül satırları (ciro ⊃ brüt kâr ⊃ net kâr), seçili satır açılır
//  3) Aylık halkalar — seçili ayın en iyi aya oranı (dış ciro, orta brüt, iç net)
// Veri, gosterge-paneli.js'in yayınladığı 'lal:monthly-profit' olayından gelir
// (aynı aylık veri; net kâr = realNetProfit). Renkler Apple sistem renkleri,
// açık/koyu tema için ayrı tonlar; tema değişince bir sonraki karede yenilenir.
(function () {
  'use strict';
  var cvCap = document.getElementById('mpxCapsules');
  var cvRing = document.getElementById('mpxRings');
  if (!cvCap || !cvRing) return;
  var wrapCap = cvCap.parentElement;
  var RM = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter', system-ui, sans-serif";
  var cc = cvCap.getContext('2d'), cr = cvRing.getContext('2d');
  var px = document.createElement('canvas'); px.width = px.height = 1;
  var pc2 = px.getContext('2d', { willReadFrequently: true });
  var data = [], sel = -1, rh = [], dv = { r: 0, g: 0, n: 0 }, t0 = performance.now();
  var vis = [true, true], ys = [], hs = [], ringRowH = 100;
  var clamp = function (x, a, b) { return Math.min(b, Math.max(a, x)); };
  var ease = function (t) { return 1 - Math.pow(1 - t, 3); };
  var tok = function (n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); };
  function rgb(c) { pc2.clearRect(0, 0, 1, 1); pc2.fillStyle = '#000'; pc2.fillStyle = c; pc2.fillRect(0, 0, 1, 1); var d = pc2.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]]; }
  function isLight() { var c = rgb(tok('--lal-surface')); return (c[0] * 299 + c[1] * 587 + c[2] * 114) / 1000 > 150; }
  function pal() { return isLight() ? ['#007AFF', '#FF9500', '#34C759'] : ['#0A84FF', '#FF9F0A', '#30D158']; }
  function al(h, a) { var c = rgb(h); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }
  var K = function (v) { return '₺' + Math.round(v).toLocaleString('tr-TR'); };
  var S = function (v) { return Math.abs(v) >= 1000 ? '₺' + Math.round(v / 1000) + 'B' : '₺' + Math.round(v); };
  var pct = function (a, b) { return b > 0 ? (a / b * 100).toFixed(1).replace('.', ',') + '%' : '–'; };
  function F(w, s) { return (w || '') + ' ' + (s || 13) + 'px ' + FONT; }

  document.addEventListener('lal:monthly-profit', function (e) {
    data = (e.detail || []).map(function (m) {
      var p = m.month.split('-'), d = new Date(+p[0], +p[1] - 1, 1);
      return {
        short: d.toLocaleDateString('tr-TR', { month: 'short' }) + ' ' + String(p[0]).slice(2),
        long: d.toLocaleDateString('tr-TR', { month: 'long', year: 'numeric' }),
        r: m.rev, g: m.gross, n: m.net,
      };
    });
    if (sel < 0 || sel >= data.length) sel = data.length - 1;
    rh = data.map(function () { return 36; });
    wrapCap.style.height = (Math.max(0, data.length - 1) * 36 + 178 + 16) + 'px';
    t0 = performance.now();
  });
  if (window.__lalMonthlyProfit) document.dispatchEvent(new CustomEvent('lal:monthly-profit', { detail: window.__lalMonthlyProfit }));

  function prep(cv, c) {
    var d = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
    if (!W || !H) return null;
    if (cv.width !== Math.round(W * d) || cv.height !== Math.round(H * d)) { cv.width = W * d; cv.height = H * d; }
    c.setTransform(d, 0, 0, d, 0, 0); c.clearRect(0, 0, W, H);
    return [W, H];
  }
  function rr(c, x, y, w, h, r) { c.beginPath(); if (c.roundRect) c.roundRect(x, y, w, h, r); else c.rect(x, y, w, h); }
  function cap(c, x, y, w, h) {
    var r = h / 2; w = Math.max(w, h);
    c.beginPath(); c.moveTo(x + r, y); c.lineTo(x + w - r, y); c.arc(x + w - r, y + r, r, -Math.PI / 2, Math.PI / 2);
    c.lineTo(x + r, y + h); c.arc(x + r, y + r, r, Math.PI / 2, Math.PI * 1.5); c.closePath();
  }

  function drawCap(W, H, g) {
    var n = data.length, cl = pal(), fg = tok('--lal-text-main'), mu = tok('--lal-text-muted'), sep = tok('--lal-border-soft'), fill = tok('--lal-surface-2');
    var mx = Math.max.apply(null, data.map(function (d) { return d.r; }).concat([1]));
    var pl = 78, pr = Math.min(170, W * .3), tw = W - pl - pr - 14, y = 6;
    ys = []; hs = [];
    for (var r = 0; r < n; r++) {
      var k = n - 1 - r, h = rh[k], isSel = k === sel, d = data[k];
      rh[k] += ((isSel ? 178 : 36) - rh[k]) * (RM ? 1 : .2); h = rh[k];
      ys.push(y); hs.push(h);
      if (isSel) { cc.fillStyle = fill; rr(cc, 4, y + 2, W - 8, h - 4, 18); cc.fill(); }
      else { cc.fillStyle = sep; cc.fillRect(16, y + h - .5, W - 32, .5); }
      var bh = isSel ? 30 : 13, by = isSel ? y + 16 : y + (h - bh) / 2;
      cc.textAlign = 'left'; cc.fillStyle = isSel ? fg : mu; cc.font = F(isSel ? '650' : '', 13);
      cc.fillText(d.short, 16, isSel ? by + bh / 2 + 5 : y + h / 2 + 4);
      cc.globalAlpha = isSel ? 1 : .6;
      [[d.r, 0, 1], [d.g, 1, .7], [d.n, 2, .42]].forEach(function (q) {
        var hh = bh * q[2]; cc.fillStyle = cl[q[1]]; cap(cc, pl, by + (bh - hh) / 2, Math.max(0, q[0]) / mx * tw * g, hh); cc.fill();
      });
      cc.globalAlpha = 1;
      cc.textAlign = 'right'; cc.fillStyle = isSel ? fg : mu; cc.font = F(isSel ? '650' : '', 13);
      cc.fillText(S(d.r) + '  ·  ' + S(d.n), W - 12, isSel ? by + bh / 2 + 5 : y + h / 2 + 4);
      if (isSel && h > 150) {
        var w3 = (W - pl - 12 - 24) / 3, yy = y + 66, prev = k > 0 ? data[k - 1] : null;
        [['Ciro', d.r, 0], ['Brüt kâr', d.g, 1], ['Net kâr', d.n, 2]].forEach(function (q, i) {
          var x = pl + i * (w3 + 12), s = q[2];
          cc.fillStyle = al(cl[s], .14); rr(cc, x, yy, w3, 86, 16); cc.fill();
          cc.fillStyle = cl[s]; cc.beginPath(); cc.arc(x + 16, yy + 19, 4.5, 0, 7); cc.fill();
          cc.fillStyle = mu; cc.textAlign = 'left'; cc.font = F('600', 13); cc.fillText(q[0], x + 28, yy + 23);
          cc.fillStyle = fg; cc.font = F('700', w3 < 150 ? 18 : 24); cc.fillText(K(q[1]), x + 14, yy + 52);
          cc.fillStyle = mu; cc.font = F('', 12);
          var sub = '';
          if (s === 0) { if (prev && prev.r > 0) { var dp = (d.r / prev.r - 1) * 100; sub = (dp >= 0 ? '▲ ' : '▼ ') + Math.abs(dp).toFixed(1).replace('.', ',') + '% önceki aya göre'; } }
          else if (s === 1) sub = 'Brüt marj ' + pct(d.g, d.r);
          else sub = 'Net marj ' + pct(d.n, d.r);
          cc.fillText(sub, x + 14, yy + 72);
        });
      }
      y += h;
    }
  }

  function drawRings(W, H, g) {
    var n = data.length; if (!n) return;
    var d = data[sel], cl = pal(), fg = tok('--lal-text-main'), mu = tok('--lal-text-muted'), fill = tok('--lal-surface-2');
    var best = { r: 1, g: 1, n: 1 };
    data.forEach(function (x) { best.r = Math.max(best.r, x.r); best.g = Math.max(best.g, x.g); best.n = Math.max(best.n, x.n); });
    var tg = { r: d.r / best.r, g: d.g / best.g, n: d.n / best.n };
    ['r', 'g', 'n'].forEach(function (k) { dv[k] += (clamp(tg[k], 0, 1) - dv[k]) * (RM ? 1 : .12); });
    var cy = (H - ringRowH) / 2, R = Math.min(cy - 4, W * .2, 130), cx = Math.max(R + 24, W * .24);
    var lw = Math.max(8, Math.min(22, R / 4.6)), rs = [R, R - lw - 5, R - 2 * (lw + 5)], ks = ['r', 'g', 'n'];
    rs.forEach(function (r, s) {
      cr.lineWidth = lw; cr.lineCap = 'round'; cr.strokeStyle = al(cl[s], .2); cr.beginPath(); cr.arc(cx, cy, r, 0, 7); cr.stroke();
      var p = clamp(dv[ks[s]], 0, 1) * g;
      if (p > .002) { cr.strokeStyle = cl[s]; cr.beginPath(); cr.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * p); cr.stroke(); }
    });
    cr.textAlign = 'center'; cr.fillStyle = fg; cr.font = F('650', Math.round(Math.min(21, R / 5))); cr.fillText(d.short, cx, cy + 2);
    cr.fillStyle = mu; cr.font = F('', 12); cr.fillText('rekor aya oran', cx, cy + 19);
    var tx = Math.min(W * .55, cx + R + 56);
    [['Ciro', d.r, best.r], ['Brüt kâr', d.g, best.g], ['Net kâr', d.n, best.n]].forEach(function (q, s) {
      var y = cy - 56 + s * 58;
      cr.fillStyle = cl[s]; cr.beginPath(); cr.arc(tx, y - 6, 6, 0, 7); cr.fill();
      cr.textAlign = 'left'; cr.fillStyle = mu; cr.font = F('600', 13); cr.fillText(q[0] + '  ·  rekorun %' + Math.round(Math.max(0, q[1]) / q[2] * 100), tx + 16, y - 2);
      cr.fillStyle = fg; cr.font = F('700', 26); cr.fillText(K(q[1]), tx, y + 26);
    });
    var cw = W / n, ry = H - ringRowH / 2 - 4;
    data.forEach(function (m, k) {
      var x = cw * k + cw / 2, isSel = k === sel;
      if (isSel) { cr.fillStyle = fill; rr(cr, cw * k + 3, H - ringRowH + 4, cw - 6, ringRowH - 8, 18); cr.fill(); }
      [[m.r / best.r, 0, 17], [m.g / best.g, 1, 12], [m.n / best.n, 2, 7]].forEach(function (q) {
        cr.lineWidth = 4; cr.lineCap = 'round'; cr.strokeStyle = al(cl[q[1]], .2); cr.beginPath(); cr.arc(x, ry, q[2], 0, 7); cr.stroke();
        if (q[0] > .01) { cr.strokeStyle = cl[q[1]]; cr.beginPath(); cr.arc(x, ry, q[2], -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.min(q[0], 1) * g); cr.stroke(); }
      });
      cr.fillStyle = isSel ? fg : mu; cr.font = F(isSel ? '650' : '', 12); cr.textAlign = 'center';
      cr.fillText(m.short.split(' ')[0], x, H - 10);
    });
  }

  function capIndex(ev) {
    var y = ev.clientY - cvCap.getBoundingClientRect().top;
    for (var r = 0; r < ys.length; r++) if (y >= ys[r] && y < ys[r] + hs[r]) return data.length - 1 - r;
    return -1;
  }
  function ringIndex(ev) {
    var b = cvRing.getBoundingClientRect();
    if (!data.length || ev.clientY - b.top < b.height - ringRowH) return -1;
    return clamp(Math.floor((ev.clientX - b.left) / (b.width / data.length)), 0, data.length - 1);
  }
  cvCap.addEventListener('click', function (e) { var i = capIndex(e); if (i >= 0) sel = i; });
  cvRing.addEventListener('click', function (e) { var i = ringIndex(e); if (i >= 0) sel = i; });
  cvCap.addEventListener('mousemove', function (e) { cvCap.style.cursor = capIndex(e) >= 0 ? 'pointer' : 'default'; });
  cvRing.addEventListener('mousemove', function (e) { cvRing.style.cursor = ringIndex(e) >= 0 ? 'pointer' : 'default'; });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { vis[0] = es[0].isIntersecting; }).observe(cvCap);
    new IntersectionObserver(function (es) { vis[1] = es[0].isIntersecting; }).observe(cvRing);
  }
  (function loop(now) {
    if (data.length && sel >= 0) {
      var g = RM ? 1 : ease(clamp((now - t0) / 1000));
      if (vis[0]) { var a = prep(cvCap, cc); if (a) drawCap(a[0], a[1], g); }
      if (vis[1]) { var b = prep(cvRing, cr); if (b) drawRings(b[0], b[1], g); }
    }
    requestAnimationFrame(loop);
  })(performance.now());
})();
