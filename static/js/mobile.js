// Telefon davranışları (≤900px, dokunmatik): aşağı çek-yenile.
// iPhone ana ekran uygulamasında (PWA) tarayıcının yenile düğmesi yok; bu yüzden şart.
(function () {
  'use strict';
  var mq = window.matchMedia('(max-width: 900px)');

  // ---- Gezinme çubuğu 2. satırı: segment kontrol + dönem seçici ----
  // Elemanlar taşınır (kopyalanmaz): id'ler ve dinleyiciler aynı kalır.
  var topbar = document.querySelector('.lal-topbar');
  var controls = topbar && topbar.querySelector('.lal-topbar-controls');
  var row2 = null, marks = [];
  function rowItems() {
    return [document.getElementById('mp-switch'),
      (controls && controls.querySelector('.lal-dd')) || document.getElementById('range-select')]
      .filter(Boolean);
  }
  function layout() {
    if (!topbar || !controls) return;
    if (mq.matches) {
      if (row2) return;
      row2 = document.createElement('div');
      row2.className = 'lal-topbar-row2';
      rowItems().forEach(function (el) {
        var m = document.createComment('lal-row2');
        el.parentNode.insertBefore(m, el);
        marks.push([m, el]);
        row2.appendChild(el);
      });
      topbar.appendChild(row2);
    } else if (row2) {
      marks.forEach(function (p) {
        // select sonradan .lal-dd ile sarılmış olabilir: sarmalayıcıyla birlikte geri koy
        var node = p[1].parentNode && p[1].parentNode.classList && p[1].parentNode.classList.contains('lal-dd') ? p[1].parentNode : p[1];
        p[0].parentNode.insertBefore(node, p[0]); p[0].remove();
      });
      marks = [];
      row2.remove();
      row2 = null;
    }
  }
  // topbar.js range seçiciyi .lal-dd'ye çeviriyor (defer); hazır olunca yerleştir.
  function boot() { layout(); setTimeout(layout, 0); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  if (mq.addEventListener) mq.addEventListener('change', layout); else mq.addListener(layout);

  if (!('ontouchstart' in window)) return;
  var THRESH = 72, MAX = 110;
  var ind = document.createElement('div');
  ind.className = 'lal-ptr';
  ind.setAttribute('aria-hidden', 'true');
  ind.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>';
  document.body.appendChild(ind);
  var svg = ind.firstChild;
  var startY = null, dy = 0, busy = false;

  function topOffset() {
    var bar = document.querySelector('.lal-topbar');
    return bar ? bar.getBoundingClientRect().bottom : 0;
  }
  function blocked(t) {
    // Açık çekmece/paneller ve form alanlarında devre dışı
    return document.documentElement.classList.contains('lal-drawer-open') ||
      (t.closest && t.closest('.lal-ndrawer.is-open, .lal-cmdk-overlay, .pk-overlay, input, textarea, select, canvas'));
  }
  function paint() {
    var p = Math.min(dy, MAX);
    ind.style.top = topOffset() + 'px';
    ind.style.opacity = String(Math.min(1, p / THRESH));
    ind.style.transform = 'translateY(' + (p * 0.6 - 30) + 'px)';
    svg.style.transform = 'rotate(' + (p / THRESH) * 270 + 'deg)';
    ind.classList.toggle('is-ready', p >= THRESH);
  }
  function reset() {
    ind.style.transition = 'transform .25s ease, opacity .25s ease';
    ind.style.opacity = '0';
    ind.style.transform = 'translateY(-50px)';
    setTimeout(function () { ind.style.transition = ''; }, 260);
  }

  document.addEventListener('touchstart', function (e) {
    if (!mq.matches || busy || window.scrollY > 0 || e.touches.length !== 1 || blocked(e.target)) { startY = null; return; }
    startY = e.touches[0].clientY; dy = 0;
  }, { passive: true });
  document.addEventListener('touchmove', function (e) {
    if (startY === null) return;
    dy = e.touches[0].clientY - startY;
    if (dy <= 0 || window.scrollY > 0) { dy = 0; ind.style.opacity = '0'; return; }
    paint();
  }, { passive: true });
  document.addEventListener('touchend', function () {
    if (startY === null) return;
    startY = null;
    if (dy >= THRESH) {
      busy = true;
      ind.classList.add('is-loading');
      ind.style.transform = 'translateY(' + (THRESH * 0.6 - 30) + 'px)';
      setTimeout(function () { location.reload(); }, 250);
    } else {
      reset();
    }
    dy = 0;
  }, { passive: true });
})();
