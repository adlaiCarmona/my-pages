/* ── Booster box break-even calculator ── */
function updateSection(el) {
  const slug = el.id.replace('box-price-', '');
  const boxCost = parseFloat(el.value) || 0;
  const details = el.closest('.breakeven-details');
  const ev = parseFloat(details.dataset.ev) || 0;

  const diff    = ev - boxCost;
  const outcome = document.getElementById('be-outcome-' + slug);
  const outVal  = document.getElementById('be-outcome-val-' + slug);
  const boxesEl = document.getElementById('be-boxes-' + slug);

  outcome.classList.remove('be-profit', 'be-loss');
  if (diff >= 0) {
    outcome.classList.add('be-profit');
    outVal.textContent = '+$' + diff.toFixed(2) + ' profit';
    boxesEl.textContent = '1 box';
  } else {
    outcome.classList.add('be-loss');
    outVal.textContent = '-$' + Math.abs(diff).toFixed(2) + ' loss';
    const boxes = ev > 0 ? Math.ceil(boxCost / ev) : '∞';
    boxesEl.textContent = boxes + (boxes !== '∞' ? ' boxes' : '');
  }
}

document.querySelectorAll('.box-price-input').forEach(input => {
  input.addEventListener('input', () => updateSection(input));
  updateSection(input);
});

/* ── Card overlay ── */
const backdrop = document.getElementById('overlay-backdrop');
const ovClose  = document.getElementById('overlay-close');

function openOverlay(card) {
  const d = card.dataset;

  document.getElementById('ov-img').src = d.image;
  document.getElementById('ov-img').alt = d.name;
  document.getElementById('ov-name').textContent = d.name;

  const price = d.price || '';
  const priceEl = document.getElementById('ov-price');
  priceEl.textContent = price;
  const p = parseFloat(price.replace('$',''));
  priceEl.className = 'overlay-price ' + (p >= 50 ? 'price-high' : p >= 10 ? 'price-mid' : 'price-low');

  // Price change
  const deltaEl = document.getElementById('ov-delta');
  if (d.priceChange !== undefined && d.priceChange !== '') {
    const dv = parseFloat(d.priceChange);
    if (dv > 0) {
      deltaEl.textContent = '▲ $' + dv.toFixed(2) + ' since last scan';
      deltaEl.className = 'price-delta delta-up';
    } else if (dv < 0) {
      deltaEl.textContent = '▼ $' + Math.abs(dv).toFixed(2) + ' since last scan';
      deltaEl.className = 'price-delta delta-down';
    } else {
      deltaEl.textContent = '— no change since last scan';
      deltaEl.className = 'price-delta delta-flat';
    }
    deltaEl.style.display = '';
  } else {
    deltaEl.textContent = '';
    deltaEl.style.display = 'none';
  }

  // Rank change
  const rankEl = document.getElementById('ov-rank-delta');
  const rc = d.rankChange;
  if (rc === 'new') {
    rankEl.textContent = 'NEW to ranking';
    rankEl.className = 'rank-delta rank-new';
    rankEl.style.display = '';
  } else if (rc !== undefined && rc !== '' && rc !== '0') {
    const rv = parseInt(rc, 10);
    if (rv > 0) {
      rankEl.textContent = '▲ ' + rv + ' rank';
      rankEl.className = 'rank-delta rank-up';
    } else {
      rankEl.textContent = '▼ ' + Math.abs(rv) + ' rank';
      rankEl.className = 'rank-delta rank-down';
    }
    rankEl.style.display = '';
  } else {
    rankEl.textContent = '';
    rankEl.style.display = 'none';
  }

  // Badges
  const badges = document.getElementById('ov-badges');
  badges.innerHTML = '';
  if (d.number)    badges.innerHTML += `<span class="badge">${d.number}</span>`;
  if (d.rarityDb)  badges.innerHTML += `<span class="badge rarity">${d.rarityDb}</span>`;
  if (d.rarityName) badges.innerHTML += `<span class="rarity-name">${d.rarityName}</span>`;
  if (d.color)     badges.innerHTML += `<span class="badge badge-color">${d.color}</span>`;
  if (d.cardType)  badges.innerHTML += `<span class="badge badge-type">${d.cardType}</span>`;

  // Stats grid
  const stats = [
    ['Cost',      d.cost],
    ['Power',     d.power],
    ['Counter',   d.counter],
    ['Life',      d.life],
    ['Attribute', d.attribute],
    ['Subtypes',  d.subtypes],
  ];
  const statsEl = document.getElementById('ov-stats');
  statsEl.innerHTML = stats
    .filter(([, v]) => v)
    .map(([label, val]) =>
      `<div class="overlay-stat">
        <span class="overlay-stat-label">${label}</span>
        <span class="overlay-stat-value">${val}</span>
      </div>`
    ).join('');

  // Description (may contain HTML tags from TCGPlayer)
  const descEl = document.getElementById('ov-desc');
  if (d.description) {
    descEl.innerHTML = d.description;
    descEl.style.display = '';
  } else {
    descEl.style.display = 'none';
  }

  backdrop.classList.add('open');
  document.body.style.overflow = 'hidden';

  // ── Price history chart ──
  const chartWrap   = document.getElementById('ov-chart-wrap');
  const chartCanvas = document.getElementById('ov-chart');
  const chartFooter = document.getElementById('ov-chart-footer');
  const productId   = d.productId;

  chartCanvas.style.display = 'none';
  chartFooter.textContent   = '';
  chartWrap.classList.remove('ov-chart-error', 'ov-chart-loading');

  const ph = PRICE_HISTORY[productId];
  if (!ph || !ph.buckets || !ph.buckets.length) {
    chartWrap.classList.add('ov-chart-error');
  } else {
    drawPriceChart(chartCanvas, chartFooter, ph);
  }
}

function drawPriceChart(chartCanvas, chartFooter, ph) {
  const condition = ph.condition || '';
  const points = ph.buckets
    .map((v, i) => { const p = parseFloat(v); return { i, v: p }; })
    .filter(p => p.v > 0);

  if (!points.length) {
    chartCanvas.closest('.ov-chart-wrap').classList.add('ov-chart-error');
    return;
  }

  const W = chartCanvas.parentElement.clientWidth || 400;
  const H = 140;
  chartCanvas.width  = W;
  chartCanvas.height = H;
  chartCanvas.style.display = 'block';

  const ctx  = chartCanvas.getContext('2d');
  const pad  = { top: 14, right: 12, bottom: 24, left: 46 };
  const pw   = W - pad.left - pad.right;
  const ph2  = H - pad.top  - pad.bottom;

  const prices   = points.map(p => p.v);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const priceRange = maxPrice - minPrice || 1;

  function cx(idx)   { return pad.left + (idx / 51) * pw; }
  function cy(price) { return pad.top  + ph2 - ((price - minPrice) / priceRange) * ph2; }

  // Grid lines + Y labels
  ctx.strokeStyle = 'rgba(255,255,255,.06)';
  ctx.lineWidth   = 1;
  ctx.fillStyle   = 'rgba(180,180,200,.55)';
  ctx.font        = '9px system-ui, sans-serif';
  ctx.textAlign   = 'right';
  const yTicks = 4;
  for (let t = 0; t <= yTicks; t++) {
    const val = minPrice + (priceRange * t / yTicks);
    const y   = cy(val);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
    ctx.fillText('$' + val.toFixed(0), pad.left - 4, y + 3);
  }

  // X axis grid lines (quarterly)
  ctx.textAlign = 'center';
  [0, 13, 26, 39, 51].forEach(idx => {
    const x = cx(idx);
    ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, H - pad.bottom); ctx.stroke();
  });

  // Gradient fill under line
  const grad = ctx.createLinearGradient(0, pad.top, 0, H - pad.bottom);
  grad.addColorStop(0, 'rgba(167,139,250,.35)');
  grad.addColorStop(1, 'rgba(167,139,250,.02)');

  function drawSegments(filled) {
    ctx.beginPath();
    let segStart = points[0].i;
    ctx.moveTo(cx(points[0].i), cy(points[0].v));
    for (let k = 1; k < points.length; k++) {
      if (points[k].i === points[k-1].i + 1) {
        ctx.lineTo(cx(points[k].i), cy(points[k].v));
      } else {
        if (filled) {
          ctx.lineTo(cx(points[k-1].i), H - pad.bottom);
          ctx.lineTo(cx(segStart), H - pad.bottom);
          ctx.closePath();
          ctx.fillStyle = grad; ctx.fill();
          ctx.beginPath();
        } else {
          ctx.stroke();
          ctx.beginPath();
        }
        segStart = points[k].i;
        ctx.moveTo(cx(points[k].i), cy(points[k].v));
      }
    }
    if (filled) {
      ctx.lineTo(cx(points[points.length-1].i), H - pad.bottom);
      ctx.lineTo(cx(segStart), H - pad.bottom);
      ctx.closePath();
      ctx.fillStyle = grad; ctx.fill();
    } else {
      ctx.strokeStyle = '#a78bfa';
      ctx.lineWidth   = 2;
      ctx.lineJoin    = 'round';
      ctx.stroke();
    }
  }

  drawSegments(true);
  drawSegments(false);

  // Current price dot
  const last = points[points.length - 1];
  ctx.beginPath();
  ctx.arc(cx(last.i), cy(last.v), 3.5, 0, Math.PI * 2);
  ctx.fillStyle = '#a78bfa'; ctx.fill();

  chartFooter.textContent = condition ? `Condition: ${condition}` : '';
}

function closeOverlay() {
  backdrop.classList.remove('open');
  document.body.style.overflow = '';
}

document.querySelectorAll('.card').forEach(card => {
  card.addEventListener('click', () => openOverlay(card));
  card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openOverlay(card); });
});

/* ── Rarity filters ── */
function applyRarityFilter(slug) {
  const section = document.getElementById(slug);
  const activeTags = [...document.querySelectorAll(`.rf-tag[data-slug="${slug}"].active`)];
  const activeRarities = new Set(activeTags.map(t => t.dataset.r));
  section.querySelectorAll('.card').forEach(card => {
    const r = card.dataset.rarityDb || '';
    card.style.display = activeRarities.size === 0 || activeRarities.has(r) ? '' : 'none';
  });
}

document.querySelectorAll('.rf-tag').forEach(tag => {
  tag.addEventListener('click', () => {
    tag.classList.toggle('active');
    applyRarityFilter(tag.dataset.slug);
  });
});

ovClose.addEventListener('click', closeOverlay);
backdrop.addEventListener('click', e => { if (e.target === backdrop) closeOverlay(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeOverlay(); });

/* ── Hamburger / sidebar ── */
const hamburger       = document.getElementById('hamburger');
const sidebar         = document.getElementById('sidebar');
const sidebarBackdrop = document.getElementById('sidebar-backdrop');

function openSidebar() {
  sidebar.classList.add('open');
  sidebarBackdrop.classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeSidebar() {
  sidebar.classList.remove('open');
  sidebarBackdrop.classList.remove('open');
  document.body.style.overflow = '';
}

hamburger.addEventListener('click', openSidebar);
sidebarBackdrop.addEventListener('click', closeSidebar);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSidebar(); });
sidebar.querySelectorAll('a').forEach(a => a.addEventListener('click', closeSidebar));
