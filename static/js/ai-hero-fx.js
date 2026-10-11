(function () {
  'use strict';
  var RM = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var hero = document.querySelector('.greeting-hero');
  if (!hero) return;
  var clamp = function (x, a, b) { return Math.min(b === undefined ? 1 : b, Math.max(a === undefined ? 0 : a, x)); };
  var mx = -9999, visible = true;

  // ---- Kinetik karşılama: harf harf ağırlık (hafif) ----
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
  window.addEventListener('resize', measure);

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
    }
    requestAnimationFrame(loop);
  }
  measure();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);
  requestAnimationFrame(loop);
})();
