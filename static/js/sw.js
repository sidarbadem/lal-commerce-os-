/* LAL service worker: sadece push bildirimi. Sayfa önbelleği YOK
   (finansal veri her zaman canlı gelsin). /sw.js olarak kökten sunulur. */
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });

self.addEventListener('push', function (e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { title: 'LAL', body: e.data ? e.data.text() : '' }; }
  var opts = {
    body: d.body || '',
    icon: '/static/images/android-chrome-192x192.png',
    badge: '/static/images/favicon-32x32.png',
    tag: d.tag || undefined,
    renotify: !!d.tag,
    data: { url: d.url || '/panel' },
    timestamp: Date.now()
  };
  if (d.image) opts.image = d.image;
  if (d.kind === 'order' || d.kind === 'order_cancelled') opts.vibrate = [80, 40, 80];
  e.waitUntil(self.registration.showNotification(d.title || 'LAL', opts));
});

self.addEventListener('notificationclick', function (e) {
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || '/panel';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) {
      var c = list[i];
      if ('focus' in c) { c.navigate && c.navigate(url); return c.focus(); }
    }
    return self.clients.openWindow(url);
  }));
});
