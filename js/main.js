// ===== API CONFIG =====
const API_BASE = "";

// XSS himoyasi — admin kiritgan matnlarni xavfsiz chiqarish
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
let menuItems = [];

// ===== GLOBAL XATO BOSHQARUVI (mijoz sahifasi) =====
function showToastErr(msg) {
  // showToast mavjud bo'lsa ishlatadi, bo'lmasa console
  if (typeof showToast === 'function') showToast('❌ ' + msg);
  else console.error(msg);
}

async function apiFetch(url, opts = {}) {
  try {
    const res = await fetch(url, opts);
    if (!res.ok) {
      let msg = `Server xatosi (${res.status})`;
      try { const d = await res.json(); msg = d.error || msg; } catch {}
      showToastErr(msg);
      return null;
    }
    return res;
  } catch {
    showToastErr("Tarmoq xatosi. Internetni tekshiring.");
    return null;
  }
}

// ===== FORMAT PRICE =====
function formatPrice(p) {
  return Number(p).toLocaleString('uz-UZ') + " so'm";
}

// ===== PARTICLE SYSTEM =====
(function initParticles() {
  const canvas = document.getElementById('particleCanvas');
  const ctx = canvas.getContext('2d');
  let particles = [];
  let W, H;

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  // Girih shakllari: olti burchak, kvadrat, uchburchak
  const SHAPES = ['hex', 'diamond', 'line'];

  class Particle {
    constructor() { this.reset(); }
    reset() {
      this.x     = Math.random() * W;
      this.y     = Math.random() * H;
      this.size  = Math.random() * 14 + 4;
      this.speed = Math.random() * 0.3 + 0.08;
      this.angle = Math.random() * Math.PI * 2;
      this.vx    = Math.cos(this.angle) * this.speed;
      this.vy    = Math.sin(this.angle) * this.speed;
      this.alpha = Math.random() * 0.25 + 0.05;
      this.rot   = Math.random() * Math.PI * 2;
      this.rotSpeed = (Math.random() - 0.5) * 0.01;
      this.shape = SHAPES[Math.floor(Math.random() * SHAPES.length)];
      // Gold yoki cyan
      this.color = Math.random() > 0.5 ? '200,169,110' : '0,212,255';
    }
    draw() {
      ctx.save();
      ctx.translate(this.x, this.y);
      ctx.rotate(this.rot);
      ctx.globalAlpha = this.alpha;
      ctx.strokeStyle = `rgba(${this.color},1)`;
      ctx.lineWidth   = 0.6;
      ctx.beginPath();

      if (this.shape === 'hex') {
        for (let i = 0; i < 6; i++) {
          const a = (i * Math.PI) / 3;
          const xp = this.size * Math.cos(a);
          const yp = this.size * Math.sin(a);
          i === 0 ? ctx.moveTo(xp, yp) : ctx.lineTo(xp, yp);
        }
        ctx.closePath();
      } else if (this.shape === 'diamond') {
        ctx.moveTo(0, -this.size);
        ctx.lineTo(this.size * 0.6, 0);
        ctx.lineTo(0, this.size);
        ctx.lineTo(-this.size * 0.6, 0);
        ctx.closePath();
      } else {
        ctx.moveTo(-this.size, 0);
        ctx.lineTo(this.size, 0);
        ctx.moveTo(0, -this.size * 0.5);
        ctx.lineTo(0, this.size * 0.5);
      }
      ctx.stroke();
      ctx.restore();
    }
    update() {
      this.x   += this.vx;
      this.y   += this.vy;
      this.rot += this.rotSpeed;
      if (this.x < -40 || this.x > W + 40 || this.y < -40 || this.y > H + 40) {
        this.reset();
        this.x = Math.random() > 0.5 ? -20 : W + 20;
        this.y = Math.random() * H;
      }
    }
  }

  for (let i = 0; i < 55; i++) particles.push(new Particle());

  function loop() {
    ctx.clearRect(0, 0, W, H);
    particles.forEach(p => { p.update(); p.draw(); });
    requestAnimationFrame(loop);
  }
  loop();
})();

// ===== LOAD MENU FROM API =====
async function loadMenuFromAPI() {
  try {
    const res  = await fetch(`${API_BASE}/api/menu`);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    if (!Array.isArray(data)) throw new Error('Not array');
    menuItems  = data.filter(i => i.available).map(i => ({
      id: i.id, name: i.name, category: i.category,
      emoji: i.emoji || '🍽', desc: i.description || '',
      price: i.price, image: i.image
    }));
  } catch {}
  renderMenu();
}

// ===== RENDER MENU =====
function renderMenu(category = 'all') {
  const grid  = document.getElementById('menuGrid');
  const items = category === 'all'
    ? menuItems
    : menuItems.filter(i => i.category === category);

  grid.innerHTML = items.map(item => `
    <div class="menu-card">
      <div class="menu-card-img">
        ${item.image
          ? `<img src="${API_BASE}${encodeURI(item.image)}" style="width:100%;height:100%;object-fit:cover;position:absolute;inset:0;" />`
          : ''}
        <span style="position:relative;z-index:1">${esc(item.emoji)}</span>
      </div>
      <div class="menu-card-body">
        <p class="menu-card-cat">${esc(getCatLabel(item.category))}</p>
        <h3 class="menu-card-name">${esc(item.name)}</h3>
        <p class="menu-card-desc">${esc(item.desc)}</p>
        <div class="menu-card-footer">
          <span class="menu-price">${formatPrice(item.price)}</span>
          <button class="menu-order-btn" data-id="${item.id}">${typeof t==='function' ? t('menu.order') : 'Buyurtma'}</button>
        </div>
      </div>
    </div>
  `).join('');

  grid.querySelectorAll('.menu-order-btn').forEach(btn => {
    btn.addEventListener('click', () => openOrderModal(+btn.dataset.id));
  });
}

function getCatLabel(cat) {
  if (typeof t === 'function') return t('cat.' + cat) || cat;
  const labels = { milliy: '🇺🇿 Milliy', grill: '🔥 Grill', salad: '🥗 Salat', drink: '🥤 Ichimlik' };
  return labels[cat] || cat;
}

// ===== MENU TABS =====
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderMenu(btn.dataset.category);
  });
});

loadMenuFromAPI();

// Til o'zganda menu va boshqa dinamik qismlarni qayta render qilish
window.addEventListener('langchange', () => {
  const activeBtn = document.querySelector('.tab-btn.active');
  const activeCat = activeBtn ? activeBtn.dataset.category : 'all';
  renderMenu(activeCat);
});

// ===== GALLERY FROM API =====
async function loadGallery() {
  const grid = document.querySelector('.gallery-grid');
  if (!grid) return;
  try {
    const res   = await fetch(`${API_BASE}/api/gallery?active=1`);
    if (!res.ok) return;
    const items = await res.json();
    if (!Array.isArray(items) || !items.length) return;
    const colors = ['#0a1628,#1a3a6e','#0d1f3c,#0a2463','#050d20,#0a1628','#0a2463,#0d1f3c','#030810,#0a1628','#0d1629,#1a3a6e'];
    const spans  = ['gallery-large','','','','gallery-wide',''];
    grid.innerHTML = items.map((item, i) => {
      const bg   = colors[i % colors.length];
      const span = spans[i] || '';
      const img  = item.image
        ? `<img src="${encodeURI(item.image)}" alt="${esc(item.title)}" style="width:100%;height:100%;object-fit:cover;" />`
        : `<div class="gallery-placeholder" style="background:linear-gradient(135deg,${bg});width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;">
             <span style="font-size:3.5rem;">${esc(item.emoji) || '🖼'}</span>
             <span class="g-label">${esc(item.title)}</span>
           </div>`;
      return `<div class="gallery-item ${span} reveal">
        <div class="gallery-inner">
          ${img}
          <div class="gallery-overlay"><span>${esc(item.title)}</span></div>
        </div>
      </div>`;
    }).join('');
    grid.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));
  } catch(e) {}
}

// ===== PROMOTIONS FROM API =====
async function loadPromos() {
  const grid = document.getElementById('promoGrid');
  if (!grid) return;
  try {
    const res   = await fetch(`${API_BASE}/api/promotions?active=1`);
    if (!res.ok) return;
    const items = await res.json();
    if (!Array.isArray(items) || !items.length) return;
    grid.innerHTML = items.map(p => `
      <div class="promo-card glass-card reveal">
        ${p.badge ? `<div class="promo-badge">${esc(p.badge)}</div>` : ''}
        <div class="promo-icon">${esc(p.emoji) || '🎁'}</div>
        <h3>${esc(p.title)}</h3>
        <p>${esc(p.description || '')}</p>
        <div class="promo-time">
          <span style="color:var(--cyan);font-size:0.8rem;">⏰</span>
          <span style="color:rgba(255,255,255,0.45);font-size:0.8rem;">${esc(p.time_info || '')}</span>
        </div>
      </div>`).join('');
    grid.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));
  } catch(e) {}
}

loadGallery();
loadPromos();

// ===== QR STOL TIZIMI =====
let tableSession = null; // { table_number, session_id, token }
let cart = [];           // [{ item, qty, comment }]

async function initTableSession() {
  const params = new URLSearchParams(window.location.search);
  const tableNum = params.get('table');
  const token    = params.get('token');
  if (!tableNum) return;

  // Token tekshirish
  if (token) {
    try {
      const res  = await fetch(`${API_BASE}/api/session/validate?token=${encodeURIComponent(token)}`);
      const data = await res.json();
      if (data.valid) {
        tableSession = { table_number: data.table_number, session_id: data.session_id, token };
        showTableBanner(data.table_number);
        return;
      }
    } catch(e) {}
  }
  // Token yo'q yoki eskirgan — faqat stol raqamini ko'rsatamiz
  showTableBanner(tableNum);
  tableSession = { table_number: tableNum, session_id: null, token: null };
}

function showTableBanner(num) {
  const existing = document.getElementById('tableBanner');
  if (existing) existing.remove();
  const banner = document.createElement('div');
  banner.id = 'tableBanner';
  banner.style.cssText = `position:fixed;bottom:80px;left:50%;transform:translateX(-50%);
    background:linear-gradient(135deg,rgba(0,100,170,0.95),rgba(0,180,220,0.9));
    border:1px solid rgba(0,212,255,0.5);border-radius:50px;
    padding:10px 24px;font-family:'Rajdhani',sans-serif;font-weight:700;
    letter-spacing:2px;font-size:0.85rem;color:#fff;z-index:900;
    display:flex;align-items:center;gap:10px;box-shadow:0 8px 32px rgba(0,212,255,0.3);`;
  banner.innerHTML = `<span style="color:var(--cyan,#00d4ff);">⊞ STOL #${esc(String(num))}</span>
    <span style="opacity:0.6">|</span>
    <span id="cartCount" style="color:#fff;">Savatcha bo'sh</span>
    <button onclick="openCart()" style="background:rgba(255,255,255,0.15);border:none;
      color:#fff;padding:4px 14px;border-radius:20px;cursor:pointer;font-family:inherit;
      font-size:0.8rem;font-weight:700;">Savatcha ▲</button>`;
  document.body.appendChild(banner);
}

function updateCartCount() {
  const el = document.getElementById('cartCount');
  if (!el) return;
  const total = cart.reduce((s,c) => s + c.item.price * c.qty, 0);
  const count = cart.reduce((s,c) => s + c.qty, 0);
  el.textContent = count ? `${count} ta · ${Number(total).toLocaleString()} so'm` : 'Savatcha bo\'sh';
}

function addToCart(item) {
  if (!tableSession) return;
  const existing = cart.find(c => c.item.id === item.id);
  if (existing) { existing.qty++; }
  else { cart.push({ item, qty: 1, comment: '' }); }
  updateCartCount();
  showCartToast(item.name);
}

function showCartToast(name) {
  const t = document.createElement('div');
  t.style.cssText = `position:fixed;bottom:140px;right:20px;
    background:rgba(0,212,255,0.15);border:1px solid rgba(0,212,255,0.4);
    color:#00d4ff;padding:10px 18px;border-radius:8px;font-family:'Rajdhani',sans-serif;
    font-weight:700;font-size:0.85rem;z-index:999;letter-spacing:1px;
    animation:slideIn 0.3s ease;`;
  t.textContent = '✓ Savatchaga qo\'shildi: ' + name;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2000);
}

function openCart() {
  const modal = document.getElementById('cartModal');
  if (!modal) { createCartModal(); return; }
  renderCart();
  modal.style.display = 'flex';
}

function createCartModal() {
  const div = document.createElement('div');
  div.id = 'cartModal';
  div.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.85);
    z-index:9999;display:flex;align-items:flex-end;justify-content:center;`;
  div.innerHTML = `<div style="background:#0d1420;border-radius:20px 20px 0 0;width:100%;max-width:600px;
      padding:28px 24px;border-top:1px solid rgba(0,212,255,0.2);max-height:85vh;overflow-y:auto;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
      <h2 style="font-family:'Cinzel',serif;color:#00d4ff;font-size:1.1rem;letter-spacing:2px;">SAVATCHA</h2>
      <button onclick="document.getElementById('cartModal').style.display='none'"
        style="background:none;border:none;color:rgba(255,255,255,0.5);font-size:1.4rem;cursor:pointer;">✕</button>
    </div>
    <div id="cartItems"></div>
    <div id="cartTotal" style="margin-top:16px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.1);"></div>
    <div style="margin-top:8px;">
      <input id="cartNote" type="text" placeholder="Umumiy izoh (masalan: piyozsiz)" maxlength="300"
        style="width:100%;background:rgba(255,255,255,0.05);border:1px solid rgba(0,212,255,0.15);
        border-radius:8px;color:#fff;padding:10px 14px;font-family:inherit;font-size:0.9rem;margin-bottom:14px;"/>
      <button onclick="submitCart()" style="width:100%;background:linear-gradient(135deg,#005577,#0099cc);
        border:none;color:#fff;padding:16px;border-radius:10px;font-family:'Rajdhani',sans-serif;
        font-size:1rem;font-weight:700;letter-spacing:2px;cursor:pointer;">
        BUYURTMA BERISH ✓
      </button>
      ${tableSession && tableSession.session_id ? `
      <button onclick="requestBill()" style="width:100%;background:rgba(255,152,0,0.1);
        border:1px solid rgba(255,152,0,0.3);color:#ff9800;padding:12px;border-radius:10px;
        font-family:'Rajdhani',sans-serif;font-size:0.9rem;font-weight:700;cursor:pointer;margin-top:8px;">
        🧾 Hisob so'rash
      </button>` : ''}
    </div>
  </div>`;
  document.body.appendChild(div);
  renderCart();
}

function renderCart() {
  const el = document.getElementById('cartItems');
  const tot = document.getElementById('cartTotal');
  if (!el) return;
  if (!cart.length) {
    el.innerHTML = '<p style="color:rgba(255,255,255,0.3);text-align:center;padding:24px;">Savatcha bo\'sh</p>';
    if (tot) tot.innerHTML = '';
    return;
  }
  el.innerHTML = cart.map((c,i) => `
    <div style="display:flex;align-items:center;gap:12px;padding:12px 0;
        border-bottom:1px solid rgba(255,255,255,0.06);">
      <span style="font-size:1.8rem;">${esc(c.item.emoji)||'🍽'}</span>
      <div style="flex:1;">
        <div style="font-weight:600;font-size:0.95rem;">${esc(c.item.name)}</div>
        <div style="color:#c8a96e;font-size:0.85rem;">${Number(c.item.price).toLocaleString()} so'm</div>
        <input type="text" placeholder="Izoh (piyozsiz...)" value="${esc(c.comment)}"
          onchange="cart[${i}].comment=this.value"
          style="margin-top:4px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);
          border-radius:6px;color:#fff;padding:4px 10px;font-size:0.78rem;width:100%;font-family:inherit;"/>
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <button onclick="changeQty(${i},-1)" style="background:rgba(255,255,255,0.08);border:none;
          color:#fff;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:1rem;">−</button>
        <span style="font-weight:700;min-width:20px;text-align:center;">${c.qty}</span>
        <button onclick="changeQty(${i},1)" style="background:rgba(0,212,255,0.1);border:none;
          color:#00d4ff;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:1rem;">+</button>
        <button onclick="removeFromCart(${i})" style="background:none;border:none;
          color:rgba(255,68,68,0.7);cursor:pointer;font-size:1rem;margin-left:4px;">✕</button>
      </div>
    </div>`).join('');
  const total = cart.reduce((s,c) => s + c.item.price * c.qty, 0);
  if (tot) tot.innerHTML = `<div style="display:flex;justify-content:space-between;font-weight:700;font-size:1.05rem;">
    <span>Jami:</span><span style="color:#c8a96e;">${Number(total).toLocaleString()} so'm</span></div>`;
}

function changeQty(i, d) {
  cart[i].qty += d;
  if (cart[i].qty <= 0) cart.splice(i, 1);
  renderCart(); updateCartCount();
}
function removeFromCart(i) { cart.splice(i, 1); renderCart(); updateCartCount(); }

async function submitCart() {
  if (!cart.length) return;
  if (!tableSession || !tableSession.session_id) {
    alert('Stol sessiyasi topilmadi. Iltimos, QR kodni qayta skaner qiling.');
    return;
  }
  const items = cart.map(c => ({
    menu_item_id: c.item.id, name: c.item.name,
    emoji: c.item.emoji, price: c.item.price,
    quantity: c.qty, comment: c.comment,
    category: c.item.category
  }));
  const note = document.getElementById('cartNote')?.value || '';
  const res = await apiFetch(`${API_BASE}/api/session/${tableSession.session_id}/order`, {
    method: 'POST',
    headers: { 'Content-Type':'application/json', 'X-Session-Token': tableSession.token },
    body: JSON.stringify({ items, note })
  });
  if (!res) return;
  const data = await res.json();
  if (data.ok) {
    cart = [];
    updateCartCount();
    document.getElementById('cartModal').style.display = 'none';
    showSuccessModal();
  } else {
    showToastErr(data.error || "Qayta urinib ko'ring");
  }
}

function showSuccessModal() {
  const div = document.createElement('div');
  div.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.9);z-index:9999;
    display:flex;align-items:center;justify-content:center;`;
  div.innerHTML = `<div style="text-align:center;padding:40px;">
    <div style="font-size:4rem;margin-bottom:16px;">✅</div>
    <h2 style="font-family:'Cinzel',serif;color:#00d4ff;letter-spacing:3px;margin-bottom:8px;">BUYURTMA QABUL QILINDI!</h2>
    <p style="color:rgba(255,255,255,0.5);margin-bottom:24px;">Stol #${esc(String(tableSession.table_number))} · Oshxona tayyorlab beradi</p>
    <button onclick="this.parentElement.parentElement.remove()"
      style="background:rgba(0,212,255,0.15);border:1px solid rgba(0,212,255,0.3);
      color:#00d4ff;padding:12px 32px;border-radius:8px;font-family:'Rajdhani',sans-serif;
      font-size:1rem;font-weight:700;cursor:pointer;letter-spacing:2px;">YOPISH</button>
  </div>`;
  document.body.appendChild(div);
  setTimeout(() => div.remove(), 5000);
}

async function requestBill() {
  if (!tableSession?.session_id) return;
  const res = await apiFetch(`${API_BASE}/api/session/${tableSession.session_id}/bill`, {
    method: 'POST', headers: { 'Content-Type':'application/json', 'X-Session-Token': tableSession.token }
  });
  if (!res) return;
  document.getElementById('cartModal').style.display = 'none';
  const div = document.createElement('div');
  div.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.9);z-index:9999;
    display:flex;align-items:center;justify-content:center;`;
  div.innerHTML = `<div style="text-align:center;padding:40px;">
    <div style="font-size:4rem;margin-bottom:16px;">🧾</div>
    <h2 style="font-family:'Cinzel',serif;color:#ff9800;letter-spacing:2px;margin-bottom:8px;">HISOB SO'RALDI</h2>
    <p style="color:rgba(255,255,255,0.5);">Ofitsiant yaqinda keladi</p>
    <button onclick="this.parentElement.parentElement.remove()"
      style="margin-top:20px;background:rgba(255,152,0,0.15);border:1px solid rgba(255,152,0,0.3);
      color:#ff9800;padding:12px 32px;border-radius:8px;font-family:'Rajdhani',sans-serif;
      font-size:1rem;font-weight:700;cursor:pointer;">YOPISH</button>
  </div>`;
  document.body.appendChild(div);
}

// Menu kartasida "Savatchaga" tugmasi — tableSession mavjud bo'lsa ko'rinadi
function menuCardAction(item) {
  if (tableSession) { addToCart(item); }
  else { openOrderModal(item.id); }
}

initTableSession();

// ===== NAVBAR SCROLL =====
const navbar = document.getElementById('navbar');
window.addEventListener('scroll', () => {
  navbar.classList.toggle('scrolled', window.scrollY > 60);
});

// ===== HAMBURGER =====
const hamburger = document.getElementById('hamburger');
const navLinks  = document.getElementById('navLinks');
hamburger.addEventListener('click', () => navLinks.classList.toggle('open'));
navLinks.querySelectorAll('a').forEach(a => a.addEventListener('click', () => navLinks.classList.remove('open')));

// ===== SCROLL REVEAL =====
const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry, idx) => {
    if (entry.isIntersecting) {
      setTimeout(() => entry.target.classList.add('visible'), idx * 80);
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.1 });

document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

// ===== PARALLAX GIRIH =====
const heroGirih = document.getElementById('heroGirih');
window.addEventListener('scroll', () => {
  if (!heroGirih) return;
  const y = window.scrollY;
  heroGirih.style.transform = `translateY(${y * 0.25}px)`;
});

// ===== ORDER MODAL =====
let currentItem = null;
let currentQty  = 1;

function openOrderModal(id) {
  currentItem = menuItems.find(i => i.id === id);
  if (!currentItem) return;
  currentQty  = 1;
  document.getElementById('qtyValue').textContent = 1;
  document.getElementById('orderItemInfo').innerHTML = `
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:20px;padding:14px;
                background:rgba(0,212,255,0.05);border:1px solid rgba(0,212,255,0.15);border-radius:8px;">
      <span style="font-size:2.2rem">${esc(currentItem.emoji)}</span>
      <div>
        <strong style="font-size:1rem;font-family:'Rajdhani',sans-serif;letter-spacing:1px;">${esc(currentItem.name)}</strong>
        <p style="color:rgba(255,255,255,0.45);font-size:0.82rem;margin-top:2px">${esc(currentItem.desc)}</p>
      </div>
    </div>
  `;
  updateOrderTotal();
  document.getElementById('orderModal').classList.add('active');
  document.body.style.overflow = 'hidden';
}

function updateOrderTotal() {
  if (!currentItem) return;
  document.getElementById('orderTotal').textContent =
    `Jami: ${formatPrice(currentItem.price * currentQty)}`;
}

document.getElementById('qtyMinus').addEventListener('click', () => {
  if (currentQty > 1) { currentQty--; document.getElementById('qtyValue').textContent = currentQty; updateOrderTotal(); }
});
document.getElementById('qtyPlus').addEventListener('click', () => {
  if (currentQty < 20) { currentQty++; document.getElementById('qtyValue').textContent = currentQty; updateOrderTotal(); }
});

document.getElementById('modalClose').addEventListener('click', closeModal);
document.getElementById('orderModal').addEventListener('click', e => {
  if (e.target === document.getElementById('orderModal')) closeModal();
});
function closeModal() {
  document.getElementById('orderModal').classList.remove('active');
  document.body.style.overflow = '';
}

document.getElementById('confirmOrder').addEventListener('click', async () => {
  const name  = document.getElementById('orderName').value.trim();
  const phone = document.getElementById('orderPhone').value.trim();
  if (!name || !phone) { showToast(typeof t==='function' ? t('toast.fill') : 'Iltimos, ism va telefon raqamni kiriting!'); return; }
  try {
    const r = await fetch(`${API_BASE}/api/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_name: currentItem.name, item_id: currentItem.id,
        quantity: currentQty, total_price: currentItem.price * currentQty,
        customer_name: name, customer_phone: phone
      })
    });
    if (!r.ok) { showToast('Xatolik yuz berdi, qayta urinib ko\'ring'); return; }
  } catch { showToast('Tarmoq xatosi, qayta urinib ko\'ring'); return; }
  closeModal();
  showToast(`"${currentItem.name}" ✓`);
  document.getElementById('orderName').value  = '';
  document.getElementById('orderPhone').value = '';
});

// ===== RESERVATION =====
document.getElementById('resDate').min = new Date().toISOString().split('T')[0];

document.getElementById('reservationForm').addEventListener('submit', async e => {
  e.preventDefault();
  const name   = document.getElementById('resName').value.trim();
  const phone  = document.getElementById('resPhone').value.trim();
  const date   = document.getElementById('resDate').value;
  const time   = document.getElementById('resTime').value;
  const guests = document.getElementById('resGuests').value;
  const note   = document.getElementById('resNote').value.trim();
  if (!name || !phone || !date || !time) { showToast(typeof t==='function' ? t('toast.res.err') : "Barcha maydonlarni to'ldiring!"); return; }
  try {
    const r = await fetch(`${API_BASE}/api/reservations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ customer_name: name, customer_phone: phone, date, time, guests, note })
    });
    if (!r.ok) { showToast('Bron yuborilmadi, qayta urinib ko\'ring'); return; }
  } catch { showToast('Tarmoq xatosi, qayta urinib ko\'ring'); return; }
  showToast(`${name} — ${typeof t==='function' ? t('toast.res.ok') : 'Bron tasdiqlandi!'} (${date} ${time})`);
  e.target.reset();
});

// ===== TOAST =====
function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 4000);
}
