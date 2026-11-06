// Bildirim panelinde "Bu cihaza bildirim" satırı + Web Push aboneliği.
(function () {
  'use strict';
  var supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  var secure = window.isSecureContext;
  var ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  var reg = null, cfg = null, row, sw, note, testBtn;

  function api(url, body) {
    return fetch(url, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) { return r.json(); });
  }
  function b64ToBytes(s) {
    var pad = '='.repeat((4 - s.length % 4) % 4);
    var raw = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  function setState(on, text, disabled) {
    if (!row) return;
    sw.setAttribute('aria-checked', on ? 'true' : 'false');
    sw.disabled = !!disabled;
    row.classList.toggle('is-on', !!on);
    note.textContent = text || '';
    testBtn.hidden = !on;
  }

  function refresh() {
    if (!supported) {
      setState(false, ios && !standalone
        ? 'iPhone\'da: Safari\'de Paylaş → Ana Ekrana Ekle, sonra LAL simgesinden açıp buradan etkinleştir.'
        : 'Bu tarayıcı bildirim desteklemiyor.', true);
      return;
    }
    if (!secure) { setState(false, 'Güvenli (HTTPS) adres gerekli — Tailscale adresinden aç.', true); return; }
    if (cfg && !cfg.enabled) { setState(false, 'Sunucuda bildirim anahtarı tanımlı değil.', true); return; }
    if (Notification.permission === 'denied') { setState(false, 'İzin reddedilmiş; cihaz ayarlarından LAL bildirimlerine izin ver.', true); return; }
    if (!reg) { setState(false, 'Hazırlanıyor…', true); return; }
    reg.pushManager.getSubscription().then(function (s) {
      setState(!!s, s ? 'Yeni sipariş, iptal ve yorumlar bu cihaza gelecek.' : 'Kapalı', false);
      if (s) api('/api/push/subscribe', { subscription: s.toJSON() }).catch(function () {}); // sunucu tarafını tazele
    });
  }

  function enable() {
    sw.disabled = true;
    Notification.requestPermission().then(function (p) {
      if (p !== 'granted') { refresh(); return; }
      return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(cfg.publicKey) })
        .then(function (s) { return api('/api/push/subscribe', { subscription: s.toJSON() }); })
        .then(function () { return api('/api/push/test', {}); })
        .then(refresh);
    }).catch(function (e) { setState(false, 'Açılamadı: ' + (e && e.message ? e.message : e), false); });
  }
  function disable() {
    sw.disabled = true;
    reg.pushManager.getSubscription().then(function (s) {
      if (!s) return;
      var ep = s.endpoint;
      return s.unsubscribe().then(function () { return api('/api/push/unsubscribe', { endpoint: ep }); });
    }).then(refresh, refresh);
  }

  function build() {
    var head = document.querySelector('.lal-ndrawer-head');
    if (!head || document.querySelector('.lal-npush')) return !!head;
    row = document.createElement('div');
    row.className = 'lal-npush';
    var txt = document.createElement('div');
    txt.className = 'lal-npush-text';
    var t = document.createElement('div');
    t.className = 'lal-npush-title';
    t.textContent = 'Bu cihaza bildirim';
    note = document.createElement('div');
    note.className = 'lal-npush-note';
    txt.appendChild(t); txt.appendChild(note);
    testBtn = document.createElement('button');
    testBtn.type = 'button'; testBtn.className = 'lal-ndrawer-link'; testBtn.textContent = 'Test gönder'; testBtn.hidden = true;
    testBtn.addEventListener('click', function () {
      testBtn.disabled = true;
      api('/api/push/test', {}).finally(function () { testBtn.disabled = false; });
    });
    sw = document.createElement('button');
    sw.type = 'button'; sw.className = 'lal-switch'; sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-label', 'Bu cihaza bildirim');
    sw.addEventListener('click', function () {
      if (sw.getAttribute('aria-checked') === 'true') disable(); else enable();
    });
    row.appendChild(txt); row.appendChild(testBtn); row.appendChild(sw);
    head.parentNode.insertBefore(row, head.nextSibling);
    return true;
  }

  function start() {
    if (!build()) { setTimeout(start, 300); return; }
    refresh();
    if (!supported || !secure) return;
    api('/api/push/config').then(function (c) {
      cfg = c;
      if (!c.enabled) { refresh(); return; }
      return navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(function (r) {
        reg = r;
        return navigator.serviceWorker.ready;
      }).then(function (r) { reg = r; refresh(); });
    }).catch(function () { setState(false, 'Bildirim servisine ulaşılamadı.', true); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
