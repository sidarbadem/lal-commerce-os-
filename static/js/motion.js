// =====================================================================
// LAL hareket katmani (ui-effects.js + reveal.js yerine tek sistem)
// Kural: icerik varsayilan olarak GORUNUR. Animasyon sadece sayfa
// acildiginda ekranin altinda kalan bloklara uygulanir; gozlemci hic
// tetiklenmese bile emniyet zamanlayicisi her seyi gorunur yapar.
// Yalnizca gorseldir; veri/API mantigina dokunmaz.
// =====================================================================
(function () {
  'use strict';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var hasIO = 'IntersectionObserver' in window;
  var root = document.documentElement;

  // ---------- 1) Ust bar: kaydirinca golge + ince ilerleme cizgisi ----------
  var header = document.querySelector('.lal-topbar') || document.querySelector('header');
  var bar = document.createElement('div');
  bar.className = 'lal-scroll-progress';
  bar.setAttribute('aria-hidden', 'true');
  document.body.appendChild(bar);
  var ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      ticking = false;
      var y = window.scrollY || 0;
      if (header) header.classList.toggle('is-scrolled', y > 8);
      var max = (document.documentElement.scrollHeight - window.innerHeight) || 0;
      var p = max > 40 ? Math.min(1, y / max) : 0;
      bar.style.transform = 'scaleX(' + p.toFixed(4) + ')';
      bar.classList.toggle('is-on', p > 0.005);
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  onScroll();

  // ---------- 2) Kaydirma ile belirme ----------
  var SEL = [
    '.lal-page-content .panel',
    '.lal-page-content .lal-panel',
    '.lal-page-content .lal-status-card',
    '.lal-page-content .summary-grid > *',
    '.lal-page-content .lal-grid-4 > *',
    '.lal-page-content .card',
    '.lal-page-content .hero-stat',
    '.lal-page-content .pk-card'
  ].join(',');
  var seen = typeof WeakSet === 'function' ? new WeakSet() : null;
  var queue = [], flushT = null;

  function reveal(el) {
    el.classList.add('mo-in');
    setTimeout(function () {
      el.classList.remove('mo-rv', 'mo-in');
      el.style.removeProperty('--mo-delay');
    }, 900);
  }

  var io = hasIO && !reduce ? new IntersectionObserver(function (entries) {
    var i = 0;
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      io.unobserve(e.target);
      e.target.style.setProperty('--mo-delay', Math.min(i++ * 60, 300) + 'ms');
      reveal(e.target);
    });
  }, { rootMargin: '0px 0px -6% 0px', threshold: 0.04 }) : null;

  function consider(el) {
    if (seen) { if (seen.has(el)) return; seen.add(el); }
    else { if (el.__mo) return; el.__mo = 1; }
    if (!io) return;
    // Baska bir animasyonlu blogun icindeyse sadece dis blok animasyon alir.
    var p = el.parentElement && el.parentElement.closest(SEL);
    if (p) return;
    var r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return; // gizli eleman: dokunma
    if (r.top < window.innerHeight * 0.94) return; // zaten ekranda: titretme
    el.classList.add('mo-rv');
    io.observe(el);
  }

  function scan(scope) {
    if (scope.matches && scope.matches(SEL)) queue.push(scope);
    if (scope.querySelectorAll) Array.prototype.push.apply(queue, scope.querySelectorAll(SEL));
    if (!flushT) flushT = requestAnimationFrame(function () {
      flushT = null;
      var q = queue; queue = [];
      q.forEach(consider);
    });
  }

  if (io) {
    root.classList.add('mo-on');
    scan(document);
    new MutationObserver(function (ms) {
      ms.forEach(function (m) {
        m.addedNodes.forEach(function (n) { if (n.nodeType === 1) scan(n); });
      });
    }).observe(document.body, { childList: true, subtree: true });
    // Emniyet: sekme arka plandayken / gozlemci takilirsa icerik gizli kalmasin.
    function failsafe() {
      document.querySelectorAll('.mo-rv:not(.mo-in)').forEach(function (el) {
        var r = el.getBoundingClientRect();
        if (r.top < window.innerHeight) reveal(el);
      });
    }
    window.addEventListener('load', function () { setTimeout(failsafe, 1500); });
    setInterval(failsafe, 2500);
    window.addEventListener('beforeprint', function () {
      document.querySelectorAll('.mo-rv').forEach(reveal);
    });
  }

  // ---------- 3) Deger guncellemesinde kisa canlanma ----------
  if (!reduce) {
    var VAL = '.hero-stat-value, .card .value, .hf-value, #today-order-count';
    var watched = typeof WeakSet === 'function' ? new WeakSet() : null;
    var valueMo = new MutationObserver(function (ms) {
      var touched = [];
      ms.forEach(function (m) {
        var el = m.target.nodeType === 3 ? m.target.parentElement : m.target;
        el = el && el.closest ? el.closest(VAL) : null;
        if (el && touched.indexOf(el) < 0) touched.push(el);
      });
      touched.forEach(function (el) {
        el.classList.remove('value-pulse');
        void el.offsetWidth;
        el.classList.add('value-pulse');
      });
    });
    function watch(el) {
      if (watched) { if (watched.has(el)) return; watched.add(el); }
      valueMo.observe(el, { characterData: true, childList: true, subtree: true });
    }
    document.querySelectorAll(VAL).forEach(watch);
    new MutationObserver(function (ms) {
      ms.forEach(function (m) {
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (n.matches && n.matches(VAL)) watch(n);
          if (n.querySelectorAll) n.querySelectorAll(VAL).forEach(watch);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  }
})();
