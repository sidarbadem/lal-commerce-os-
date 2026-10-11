(function () {
  'use strict';
  var wrap = document.getElementById('ai-sb');
  var fig = document.querySelector('.greeting-hero .hero-figures');
  if (!wrap || !fig) return;
  var bar = wrap.firstElementChild;
  var RM = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var clamp = function (x) { return Math.min(1, Math.max(0, x)); };
  var $ = function (id) { return document.getElementById(id); };

  function mirror(srcId, fn) {
    var s = $(srcId);
    if (!s) return;
    fn(s);
    new MutationObserver(function () { fn(s); })
      .observe(s, { childList: true, characterData: true, subtree: true, attributes: true });
  }
  function text(dstId) {
    return function (s) { var d = $(dstId); if (d) d.textContent = s.textContent; };
  }
  function chip(dstId, prefix, title) {
    return function (s) {
      var d = $(dstId), t = (s.textContent || '').trim();
      if (!d) return;
      d.textContent = (!t || t === '–' || t === 'Yeterli veri yok') ? '' : (prefix || '') + t.replace(' geçen aya göre', '');
      d.title = title || '';
      d.className = 'ai-sb-chip' + (/^▲/.test(t) ? ' is-up' : (/^▼/.test(t) ? ' is-down' : ''));
    };
  }
  mirror('hero-today-sales', text('sb-sales'));
  mirror('hero-today-net-profit', text('sb-net'));
  mirror('hero-month-sales', text('sb-month'));
  mirror('ai2-kpi-sales-trend', chip('sb-sales-chip', '', '7 günlük ortalamaya göre'));
  mirror('ai2-kpi-profit-trend', chip('sb-net-chip', '', '7 günlük ortalamaya göre'));
  mirror('ai2-mom-projection-delta', chip('sb-month-chip', 'Ay sonu ', 'Bu hızla tahmini ay sonu, geçen aya göre'));
  mirror('ai2-mom-progress-fill', function (s) {
    var p = $('sb-prog'); if (p) p.style.width = Math.min(100, parseFloat(s.style.width) || 0) + '%';
  });
  mirror('ai2-briefing-text', function (s) {
    var line = s.querySelector('.ai2-brief-line'), n = $('sb-note');
    if (!line || !n) return;
    var tone = (line.className.match(/tone-(\w+)/) || [])[1] || '';
    n.textContent = line.textContent;
    n.setAttribute('data-tone', tone);
  });

  var ticking = false;
  function topH() {
    return parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--lal-topbar-h')) || 56;
  }
  function update() {
    ticking = false;
    var r = fig.getBoundingClientRect(), top = topH();
    var t = clamp(-(r.top - top) / Math.max(r.height, 1));
    if (RM) t = t >= 1 ? 1 : 0;
    else {
      fig.style.opacity = 1 - t * 0.85;
      fig.style.transform = 'translateY(' + (-t * 14) + 'px) scale(' + (1 - t * 0.05) + ')';
      fig.style.transformOrigin = '0 0';
    }
    var b = RM ? t : clamp((t - 0.45) * 2.2);
    bar.style.opacity = b;
    bar.style.transform = RM ? '' : 'translateY(' + ((b - 1) * 14) + 'px)';
    bar.style.visibility = b > 0 ? 'visible' : 'hidden';
  }
  function req() { if (!ticking) { ticking = true; requestAnimationFrame(update); } }
  window.addEventListener('scroll', req, { passive: true });
  window.addEventListener('resize', req);
  update();
})();
