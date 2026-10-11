(function () {
  'use strict';
  var RM = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var hero = document.querySelector('.greeting-hero');
  if (!hero) return;
  var clamp = function (x, a, b) { return Math.min(b === undefined ? 1 : b, Math.max(a === undefined ? 0 : a, x)); };
  var mx = -9999, visible = true;

  // ---- Kinetik karşılama: harf harf ağırlık ----
  var hello = hero.querySelector('.hello');
  var letters = [];
  if (hello) {
    (function split(node) {
      Array.prototype.slice.call(node.childNodes).forEach(function (n) {
        if (n.nodeType === 3) {
          var frag = document.createDocumentFragment();
          n.textContent.split('').forEach(function (ch) {
            var s = document.createElement('span');
            s.className = 'fx-ch';
            s.textContent = ch === ' ' ? '\u00a0' : ch;
            frag.appendChild(s);
            letters.push({ s: s, cx: 0 });
          });
          node.replaceChild(frag, n);
        } else if (n.nodeType === 1) split(n);
      });
    })(hello);
    hello.setAttribute('aria-label', hello.textContent.replace(/\u00a0/g, ' '));
  }
  function measure() {
    letters.forEach(function (l) { var r = l.s.getBoundingClientRect(); l.cx = r.left + r.width / 2; });
  }
  window.addEventListener('mousemove', function (e) { mx = e.clientX; }, { passive: true });
  window.addEventListener('resize', function () { measure(); size(); });

  // ---- Tel kafes 3D: son 7 gün ----
  var cv = hero.querySelector('#hero-3d'), cx = cv && cv.getContext('2d');
  var W = 0, H = 0, vals = [], t0 = performance.now();
  function size() {
    if (!cv) return;
    var d = window.devicePixelRatio || 1;
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = W * d; cv.height = H * d;
    cx.setTransform(d, 0, 0, d, 0, 0);
  }
  function pad(n) { return n < 10 ? '0' + n : '' + n; }
  function setData(daily) {
    var map = {};
    (daily || []).forEach(function (d) { map[(d.date || '').slice(0, 10)] = d.net_amount || 0; });
    vals = [];
    for (var i = 6; i >= 0; i--) {
      var d = new Date(); d.setDate(d.getDate() - i);
      vals.push(map[d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())] || 0);
    }
    t0 = performance.now();
  }
  document.addEventListener('lal:daily-sales', function (e) { setData(e.detail); });
  if (window.__lalDailySales) setData(window.__lalDailySales);

  function wire(now) {
    if (!cv || W < 40 || !vals.length) return;
    cx.clearRect(0, 0, W, H);
    var cs = getComputedStyle(document.documentElement);
    var main = cs.getPropertyValue('--lal-text-main').trim() || '#888';
    var ac = cs.getPropertyValue('--lal-accent').trim() || '#a92639';
    var mu = cs.getPropertyValue('--lal-text-faint').trim() || '#999';
    var top = hero.getBoundingClientRect().top;
    var ang = 0.55 + (RM ? 0 : (now - t0) / 1000 * 0.06) + (-top) / 520;
    var tilt = 0.55, sc = Math.min(W / 640, H / 330), fov = 900;
    var grow = RM ? 1 : 1 - Math.pow(1 - clamp((now - t0) / 1400), 3);
    var max = Math.max.apply(null, vals.concat([1]));
    var avg = vals.slice(0, 6).reduce(function (a, b) { return a + b; }, 0) / 6;
    function P(x, y, z) {
      var c = Math.cos(ang), s = Math.sin(ang), X = x * c - z * s, Z = x * s + z * c;
      var ct = Math.cos(tilt), st = Math.sin(tilt), Y = y * ct - Z * st;
      Z = y * st + Z * ct;
      var k = fov / (fov + Z + 300);
      return [W * 0.5 + X * k * sc, H * 0.7 - Y * k * sc];
    }
    function seg(a, b, col, w, al) {
      var A = P(a[0], a[1], a[2]), B = P(b[0], b[1], b[2]);
      cx.globalAlpha = al; cx.strokeStyle = col; cx.lineWidth = w;
      cx.beginPath(); cx.moveTo(A[0], A[1]); cx.lineTo(B[0], B[1]); cx.stroke();
    }
    for (var g = -260; g <= 260; g += 52) {
      seg([g, 0, -260], [g, 0, 260], mu, 1, 0.22);
      seg([-260, 0, g], [260, 0, g], mu, 1, 0.22);
    }
    var E = [[0,1],[2,3],[4,5],[6,7],[0,2],[1,3],[4,6],[5,7],[0,4],[1,5],[2,6],[3,7]];
    vals.forEach(function (v, i) {
      var x = (i - 3) * 70, h = v / max * 190 * grow, w = 22, today = i === 6, pts = [];
      [-w, w].forEach(function (dx) { [-w, w].forEach(function (dz) { [0, h].forEach(function (y) { pts.push([x + dx, y, dz]); }); }); });
      E.forEach(function (e) { seg(pts[e[0]], pts[e[1]], today ? ac : main, today ? 2 : 1.2, today ? 1 : 0.65); });
    });
    var ah = avg / max * 190 * grow;
    [[[-250, ah, -30], [250, ah, -30]], [[-250, ah, 30], [250, ah, 30]], [[-250, ah, -30], [-250, ah, 30]], [[250, ah, -30], [250, ah, 30]]]
      .forEach(function (e) { seg(e[0], e[1], ac, 1, 0.5); });
    cx.globalAlpha = 1;
  }

  // ---- döngü ----
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { visible = es[0].isIntersecting; }).observe(hero);
  }
  var open0 = performance.now();
  function loop(now) {
    if (visible) {
      var open = RM ? 1 : clamp((now - open0) / 1600);
      letters.forEach(function (l, i) {
        var boost = clamp(1 - Math.abs(l.cx - mx) / 220);
        var wave = RM ? 0 : 0.5 + 0.5 * Math.sin(now / 1000 * 1.4 + i * 0.7);
        var w = 600 + 200 * boost + 120 * wave * (1 - open) - 300 * (1 - open) * (1 - wave);
        l.s.style.fontWeight = Math.round(clamp(w, 200, 900));
      });
      wire(now);
    }
    requestAnimationFrame(loop);
  }
  size(); measure();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);
  requestAnimationFrame(loop);
})();
