// ===== API CONFIG =====
const API_BASE = "";
let menuItems = [];

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
    const data = await res.json();
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
          ? `<img src="${API_BASE}${item.image}" style="width:100%;height:100%;object-fit:cover;position:absolute;inset:0;" />`
          : ''}
        <span style="position:relative;z-index:1">${item.emoji}</span>
      </div>
      <div class="menu-card-body">
        <p class="menu-card-cat">${getCatLabel(item.category)}</p>
        <h3 class="menu-card-name">${item.name}</h3>
        <p class="menu-card-desc">${item.desc}</p>
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
      <span style="font-size:2.2rem">${currentItem.emoji}</span>
      <div>
        <strong style="font-size:1rem;font-family:'Rajdhani',sans-serif;letter-spacing:1px;">${currentItem.name}</strong>
        <p style="color:rgba(255,255,255,0.45);font-size:0.82rem;margin-top:2px">${currentItem.desc}</p>
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
    await fetch(`${API_BASE}/api/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_name: currentItem.name, item_id: currentItem.id,
        quantity: currentQty, total_price: currentItem.price * currentQty,
        customer_name: name, customer_phone: phone
      })
    });
  } catch {}
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
    await fetch(`${API_BASE}/api/reservations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ customer_name: name, customer_phone: phone, date, time, guests, note })
    });
  } catch {}
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
