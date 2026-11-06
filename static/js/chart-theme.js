// =====================================================================
// Ortak Chart.js temasi. Sadece VARSAYILANLARI ayarlar; grafiklerin
// kendi verdigi renk/secenekler her zaman onceliklidir.
//  - Tema (acik/koyu) degisince yazi/izgara rengi guncellenir
//  - Ortak tooltip, izgara, etkilesim (ayni x'teki tum seriler)
//  - Ekran disinda olusturulan grafik, ekrana girince bastan cizilir
// =====================================================================
(function () {
  'use strict';
  if (!window.Chart) return;
  var C = window.Chart;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function v(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function applyTheme() {
    var d = C.defaults;
    d.color = v('--lal-text-muted') || d.color;
    d.borderColor = v('--lal-border-soft') || d.borderColor;
    var tt = d.plugins.tooltip;
    tt.backgroundColor = v('--lal-bg-elevated') || 'rgba(20,20,22,.95)';
    tt.titleColor = v('--lal-text-main') || '#fff';
    tt.bodyColor = v('--lal-text-muted') || '#ccc';
    tt.footerColor = v('--lal-text-main') || '#fff';
    tt.borderColor = v('--lal-border') || v('--lal-border-soft');
    // Acik tema degisiminde canli grafikleri yeniden boya.
    Object.values(C.instances || {}).forEach(function (ch) {
      try { ch.update('none'); } catch (e) {}
    });
  }

  var d = C.defaults;
  d.font.family = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter', system-ui, sans-serif";
  d.font.size = 12;
  d.locale = 'tr-TR';
  d.animation = { duration: reduce ? 0 : 700, easing: 'easeOutQuart' };
  if (d.transitions && d.transitions.active) d.transitions.active.animation.duration = reduce ? 0 : 200;
  d.interaction = { mode: 'index', intersect: false, axis: 'x' };

  var tt = d.plugins.tooltip;
  tt.padding = { top: 9, right: 12, bottom: 9, left: 12 };
  tt.cornerRadius = 10;
  tt.borderWidth = 1;
  tt.caretSize = 5;
  tt.boxPadding = 5;
  tt.usePointStyle = true;
  tt.titleFont = { weight: '600', size: 12 };
  tt.bodyFont = { size: 12 };
  tt.titleMarginBottom = 6;

  var lg = d.plugins.legend;
  lg.labels.usePointStyle = true;
  lg.labels.pointStyle = 'circle';
  lg.labels.boxWidth = 7;
  lg.labels.boxHeight = 7;
  lg.labels.padding = 14;

  if (d.elements) {
    if (d.elements.point) { d.elements.point.radius = 0; d.elements.point.hoverRadius = 4; d.elements.point.hoverBorderWidth = 2.5; d.elements.point.hitRadius = 8; }
    if (d.elements.line) { d.elements.line.borderWidth = 2; d.elements.line.borderCapStyle = 'round'; d.elements.line.borderJoinStyle = 'round'; }
    if (d.elements.bar) { d.elements.bar.borderRadius = 4; d.elements.bar.borderSkipped = 'start'; }
  }

  // Olcek varsayilanlari: kenar cizgisi yok, ince izgara, tikler sakin.
  ['linear', 'category', 'time', 'logarithmic'].forEach(function (t) {
    var s = d.scales && d.scales[t];
    if (!s) return;
    if (s.border) s.border.display = false;
    if (s.grid) { s.grid.drawTicks = false; }
    if (s.ticks) { s.ticks.padding = 8; }
  });
  if (d.scales && d.scales.category && d.scales.category.grid) d.scales.category.grid.display = false;

  // datalabels eklentisi sayfa acikca istemedikce yazi basmasin.
  if (window.ChartDataLabels && d.plugins.datalabels === undefined) {
    d.set('plugins.datalabels', { display: false });
  }

  applyTheme();
  // shell.js tema degisiminde 'lal:theme-change' yayinliyor.
  document.addEventListener('lal:theme-change', function () { requestAnimationFrame(applyTheme); });

  // Ekrana girince ciz: ekran disinda dogan grafik bir kez bastan animasyon alir.
  if (!reduce && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        io.unobserve(e.target);
        var ch = C.getChart(e.target);
        if (ch && ch.$lalWait) {
          ch.$lalWait = false;
          try { ch.reset(); ch.update(); } catch (err) {}
        }
      });
    }, { threshold: 0.2 });
    C.register({
      id: 'lalInView',
      afterInit: function (chart) {
        var cv = chart.canvas;
        if (!cv || !cv.getBoundingClientRect) return;
        var r = cv.getBoundingClientRect();
        if (r.top > window.innerHeight || r.bottom < 0) {
          chart.$lalWait = true;
          io.observe(cv);
        }
      },
      beforeDestroy: function (chart) {
        if (chart.canvas) io.unobserve(chart.canvas);
      }
    });
  }

  window.LALChart = { cssVar: v, refreshTheme: applyTheme };
})();
