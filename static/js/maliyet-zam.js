// =====================================================================
// MALİYET GEÇMİŞİ — "Zam / Güncelle" penceresi (Ürünler sayfası)
// Tedarikçiden zam/indirim gelen ürünün yeni maliyeti, seçilen tarihten
// itibaren geçerli olur; o tarihten ÖNCE verilmiş siparişlerin kârı değişmez.
// API: /api/product-cost/<sku>/{history,change-preview,change,history/<id>/correct}
// urunler.js'ten SONRA yüklenir; tablodaki "Zam / Güncelle" düğmesini
// (data-has-cost="1") yakalayıp eski tarihsiz kaydetme yerine bu pencereyi açar.
// =====================================================================
(function () {
  const tbody = document.getElementById('margins-tbody');
  if (!tbody) return; // bu sayfada değiliz

  const API = (sku) => '/api/product-cost/' + encodeURIComponent(sku);
  const tl = (n) => (n === null || n === undefined || isNaN(n)) ? '–'
    : Number(n).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ₺';
  const KAYNAK = { backfill: 'Başlangıç', manual: 'Elle', ui: 'Arayüz', form: 'Form', fatura: 'Fatura', duzeltme: 'Düzeltme' };

  // ---------- küçük DOM yardımcısı (kullanıcı verisi hep textContent ile) ----------
  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    });
    children.flat().forEach((c) => { if (c != null) node.append(c); });
    return node;
  }

  // ---------- stil ----------
  const style = document.createElement('style');
  style.textContent = `
    .zam-ipucu{margin:0 0 12px;padding:10px 14px;border-radius:10px;font-size:13px;line-height:1.5;
      border:1px solid var(--lal-border,rgba(128,128,128,.35));background:var(--lal-surface-2,rgba(128,128,128,.08));}
    .zam-overlay{position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.45);display:flex;
      align-items:center;justify-content:center;padding:16px;}
    .zam-modal{background:var(--lal-surface,Canvas);color:var(--lal-text,CanvasText);width:100%;max-width:580px;
      max-height:90vh;overflow:auto;padding:20px;border-radius:14px;font-size:14px;line-height:1.5;
      border:1px solid var(--lal-border,rgba(128,128,128,.35));box-shadow:0 20px 60px rgba(0,0,0,.35);}
    .zam-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:8px;}
    .zam-head h3{margin:0;font-size:17px;}
    .zam-sub{opacity:.7;font-size:12px;word-break:break-all;}
    .zam-x{background:none;border:none;font-size:22px;line-height:1;cursor:pointer;color:inherit;opacity:.6;}
    .zam-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px 0;}
    .zam-grid label{display:block;font-size:12px;opacity:.75;margin-bottom:4px;}
    .zam-grid input{width:100%;box-sizing:border-box;padding:8px 10px;border-radius:8px;font:inherit;
      border:1px solid var(--lal-border,rgba(128,128,128,.45));background:transparent;color:inherit;}
    .zam-wide{grid-column:1 / -1;}
    .zam-ro{padding:8px 10px;border-radius:8px;background:var(--lal-surface-2,rgba(128,128,128,.08));}
    .zam-onizleme{min-height:44px;padding:10px 12px;border-radius:10px;margin-bottom:12px;
      background:var(--lal-surface-2,rgba(128,128,128,.08));}
    .zam-uyari{color:var(--red,#c0392b);margin-top:4px;}
    .zam-ok{color:var(--green,#1e8e3e);}
    .zam-actions{display:flex;justify-content:flex-end;gap:8px;margin-bottom:16px;}
    .zam-modal table{width:100%;border-collapse:collapse;font-size:13px;}
    .zam-modal th,.zam-modal td{text-align:left;padding:6px 4px;border-bottom:1px solid var(--lal-border,rgba(128,128,128,.25));}
    .zam-rozet{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;
      border:1px solid var(--lal-border,rgba(128,128,128,.45));margin-left:6px;}
  `;
  document.head.appendChild(style);

  // ---------- sayfaya açıklama (kullanıcıya zamın nasıl girileceği tarif edilir) ----------
  (function ipucuEkle() {
    if (document.getElementById('zam-ipucu')) return;
    const tablo = tbody.closest('table');
    if (!tablo) return;
    const kutu = h('div', { id: 'zam-ipucu', class: 'zam-ipucu' },
      h('strong', { text: 'Tedarikçiden zam mı geldi? ' }),
      'Ürünün maliyet hücresindeki "Zam / Güncelle" düğmesine basın; yeni maliyeti ve geçerli olacağı ',
      'tarihi girin. O tarihten önceki satışların kârı değişmez, sonrasındaki siparişler yeni maliyetle ',
      'hesaplanır. Önceki fiyatları da "Geçmiş" listesinden görebilirsiniz.');
    (tablo.closest('.table-wrap') || tablo).insertAdjacentElement('beforebegin', kutu);
  })();

  // ---------- yardımcılar ----------
  async function jget(url) {
    const r = await fetch(url);
    return r.json();
  }
  async function jpost(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    return { ok: r.ok && !data.error, data };
  }
  function simdiYerel() {
    const d = new Date(); d.setSeconds(0, 0);
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  function yenile() {
    if (window.lalReloadMargins) window.lalReloadMargins(); else location.reload();
  }

  // ---------- pencere ----------
  async function ac(sku, baslangicYeni) {
    document.querySelectorAll('.zam-overlay').forEach((n) => n.remove());

    const yeniInput = h('input', { type: 'number', step: '0.01', min: '0', inputmode: 'decimal', placeholder: 'örn. 1730' });
    const tarihInput = h('input', { type: 'datetime-local', value: simdiYerel() });
    const notInput = h('input', { type: 'text', maxlength: '120', placeholder: 'örn. fatura no (isteğe bağlı)' });
    const guncelEl = h('div', { class: 'zam-ro', text: '…' });
    const onizleme = h('div', { class: 'zam-onizleme', 'aria-live': 'polite', text: 'Yeni maliyeti girin; etkisini burada göreceksiniz.' });
    const kaydet = h('button', { class: 'inline-save-btn', type: 'button', disabled: 'disabled', text: 'Kaydet' });
    const vazgec = h('button', { class: 'inline-save-btn', type: 'button', text: 'Vazgeç',
      style: 'background:none;' });
    const gecmisKutu = h('div', {});
    const kapat = () => overlay.remove();

    const modal = h('div', { class: 'zam-modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Fiyat değişikliği' },
      h('div', { class: 'zam-head' },
        h('div', {}, h('h3', { text: 'Fiyat değişikliği (zam / indirim)' }), h('div', { class: 'zam-sub', text: sku })),
        h('button', { class: 'zam-x', type: 'button', 'aria-label': 'Kapat', text: '×', onclick: kapat })),
      h('p', { text: 'Yeni maliyet, seçtiğiniz tarih ve saatten itibaren verilen siparişlere uygulanır. ' +
        'Daha önce verilmiş siparişlerin kârı değişmez.' }),
      h('div', { class: 'zam-grid' },
        h('div', {}, h('label', { text: 'Şu anki maliyet (KDV dahil)' }), guncelEl),
        h('div', {}, h('label', { text: 'Yeni maliyet (KDV dahil) *' }), yeniInput),
        h('div', {}, h('label', { text: 'Geçerlilik başlangıcı *' }), tarihInput),
        h('div', {}, h('label', { text: 'Not' }), notInput)),
      onizleme,
      h('div', { class: 'zam-actions' }, vazgec, kaydet),
      h('h4', { text: 'Maliyet geçmişi', style: 'margin:0 0 6px;' }),
      gecmisKutu);
    const overlay = h('div', { class: 'zam-overlay', onclick: (e) => { if (e.target === overlay) kapat(); } }, modal);
    document.body.appendChild(overlay);
    vazgec.addEventListener('click', kapat);
    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') { kapat(); document.removeEventListener('keydown', esc); }
    });

    // --- geçmiş ---
    async function gecmisiYukle() {
      const data = await jget(API(sku) + '/history');
      const items = data.items || [];
      const cur = items.find((i) => i.is_current);
      guncelEl.textContent = cur ? tl(cur.cost_incl_vat) : '–';
      gecmisKutu.replaceChildren(
        h('table', {},
          h('thead', {}, h('tr', {}, ...['Geçerlilik', 'Maliyet', 'Kaynak', ''].map((t) => h('th', { text: t })))),
          h('tbody', {}, ...items.map((i) => h('tr', {},
            h('td', { text: i.valid_from_text },
              i.is_current ? h('span', { class: 'zam-rozet', text: 'güncel' }) : null,
              i.is_future ? h('span', { class: 'zam-rozet', text: 'bekliyor' }) : null),
            h('td', { text: tl(i.cost_incl_vat) }),
            h('td', { text: (KAYNAK[i.source] || i.source || '') + (i.note ? ' · ' + i.note : '') }),
            h('td', {}, h('button', { class: 'inline-save-btn', type: 'button', text: 'Düzelt',
              title: 'Yanlış girilmiş bir maliyeti, o kaydın geçerli olduğu tüm dönem için düzeltir',
              onclick: () => duzelt(i) })))))));
    }

    async function duzelt(satir) {
      const girilen = prompt(
        `HATA DÜZELTMESİ\n${satir.valid_from_text} tarihli kayıt için doğru maliyet (KDV dahil):`, satir.cost_incl_vat);
      if (girilen === null) return;
      const yeni = parseFloat(String(girilen).replace(',', '.'));
      if (!(yeni > 0)) { alert('Geçerli bir maliyet girin.'); return; }
      const url = `${API(sku)}/history/${satir.id}/correct`;
      const on = await jpost(url, { cost_incl_vat: yeni });
      if (!on.ok) { alert(on.data.error || 'Düzeltme önizlenemedi.'); return; }
      const d = on.data;
      const onay = confirm(
        `Bu işlem GEÇMİŞİ değiştirir.\n\n${d.from_text} – ${d.to_text} arasındaki ${d.affected_lines} satırın maliyeti ` +
        `${tl(d.old_cost)} yerine ${tl(d.new_cost)} olarak hesaplanacak ve o siparişlerin kârı değişecek.\n\nOnaylıyor musunuz?`);
      if (!onay) return;
      const son = await jpost(url, { cost_incl_vat: yeni, confirm: true, note: 'Hata düzeltmesi (arayüz)' });
      if (!son.ok) { alert(son.data.error || 'Düzeltme kaydedilemedi.'); return; }
      kapat(); yenile();
    }

    // --- önizleme (yazarken, gecikmeli) ---
    let sayac = 0, zamanlayici = null, onizlemeGecerli = false;
    function onizlemeIste() {
      clearTimeout(zamanlayici);
      zamanlayici = setTimeout(async () => {
        const benim = ++sayac;
        const yeni = parseFloat(yeniInput.value);
        onizlemeGecerli = false; kaydet.disabled = true;
        if (!(yeni > 0)) { onizleme.textContent = 'Yeni maliyeti girin; etkisini burada göreceksiniz.'; return; }
        const r = await jpost(API(sku) + '/change-preview', { cost_incl_vat: yeni, effective_at: tarihInput.value });
        if (benim !== sayac) return; // daha yeni bir istek var
        if (!r.ok) { onizleme.replaceChildren(h('div', { class: 'zam-uyari', text: r.data.error || 'Önizleme alınamadı.' })); return; }
        const d = r.data;
        const satirlar = [
          h('div', {}, h('strong', { text: `${tl(d.old_cost)} → ${tl(d.new_cost)} ` }),
            `(%${d.change_pct > 0 ? '+' : ''}${d.change_pct})`),
          h('div', { text: `${d.unchanged_lines} geçmiş satışın kârı DEĞİŞMEYECEK; ` +
            `${d.affected_lines} mevcut satış yeni maliyetle hesaplanacak.` }),
          h('div', { text: d.is_future
            ? `Geçerlilik ileri tarihli (${d.effective_text}): o ana kadar siparişler eski maliyetle hesaplanır.`
            : `Geçerlilik: ${d.effective_text}` }),
        ];
        (d.warnings || []).forEach((w) => satirlar.push(h('div', { class: 'zam-uyari', text: '⚠ ' + w })));
        if (d.blocked) satirlar.push(h('div', { class: 'zam-uyari', text: d.block_reason }));
        onizleme.replaceChildren(...satirlar);
        onizlemeGecerli = !d.blocked && !d.no_change;
        kaydet.disabled = !onizlemeGecerli;
      }, 300);
    }
    yeniInput.addEventListener('input', onizlemeIste);
    tarihInput.addEventListener('input', onizlemeIste);

    kaydet.addEventListener('click', async () => {
      if (!onizlemeGecerli) return;
      kaydet.disabled = true; kaydet.textContent = '…';
      const r = await jpost(API(sku) + '/change', {
        cost_incl_vat: parseFloat(yeniInput.value), effective_at: tarihInput.value, note: notInput.value.trim(),
      });
      if (!r.ok) {
        onizleme.replaceChildren(h('div', { class: 'zam-uyari', text: r.data.error || 'Kaydedilemedi.' }));
        kaydet.disabled = false; kaydet.textContent = 'Kaydet';
        return;
      }
      onizleme.replaceChildren(h('div', { class: 'zam-ok', text: 'Kaydedildi.' }));
      setTimeout(() => { kapat(); yenile(); }, 600);
    });

    await gecmisiYukle();
    if (baslangicYeni) { yeniInput.value = baslangicYeni; onizlemeIste(); }
    yeniInput.focus();
  }

  // ---------- tablodaki düğmeyi yakala (tarihsiz eski kaydetme yerine pencere) ----------
  document.addEventListener('click', (e) => {
    const btn = e.target.closest && e.target.closest('.inline-cost-save[data-has-cost="1"]');
    if (!btn) return;
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    const sku = btn.dataset.sku;
    const input = document.querySelector(`.inline-cost-input[data-sku="${CSS.escape(sku)}"]`);
    const yazilan = input && input.value !== input.defaultValue ? input.value : '';
    ac(sku, yazilan);
  }, true);

  window.lalMaliyetZam = { ac };
})();
