/* === Desire Panel · index.js === */

// Using relative path for API when integrated into Haven-Ombre
const API = '';

const DRIVE_COLORS = {
  attachment:  'hsl(340, 40%, 55%)',
  curiosity:   'hsl(200, 50%, 55%)',
  reflection:  'hsl(260, 35%, 55%)',
  duty:        'hsl(40, 45%, 55%)',
  social:      'hsl(160, 40%, 50%)',
  fatigue:     'hsl(0, 0%, 45%)',
  libido:      'hsl(15, 55%, 55%)',
  stress:      'hsl(0, 45%, 55%)',
};

const DRIVE_LABELS = {
  attachment:  '想念',
  curiosity:   '好奇',
  reflection:  '沉淀',
  duty:        '记挂',
  social:      '看人群',
  fatigue:     '疲劳',
  libido:      '亲密',
  stress:      '压力',
};

const DRIVE_ORDER = [
  'attachment', 'curiosity', 'reflection', 'duty',
  'social', 'fatigue', 'libido', 'stress',
];

const GATE_NAMES = [
  'DESIRE_DRIVEN',
  'DESIRE_COUPLING',
  'DESIRE_BASELINE_DRIFT',
  'HEARTBEAT_AUTONOMY',
  'DESIRE_SELF_DRIVE',
];

/* === DOM refs === */
const $ = (sel) => document.querySelector(sel);
const $id = (id) => document.getElementById(id);

/* === Clock === */
function updateClock() {
  const now = new Date();
  const h = String(now.getHours()).padStart(2, '0');
  const m = String(now.getMinutes()).padStart(2, '0');
  const s = String(now.getSeconds()).padStart(2, '0');
  $id('current-time').textContent = `${h}:${m}:${s}`;
}
setInterval(updateClock, 1000);
updateClock();

/* === Error handling === */
function showError(msg) {
  const banner = $id('error-banner');
  $id('error-text').textContent = msg;
  banner.hidden = false;
}

function clearError() {
  $id('error-banner').hidden = true;
}

/* === API helpers === */
async function apiFetch(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

/* === Build drive bars (once) === */
let driveBarsBuilt = false;

function buildDriveBars() {
  const container = $id('drive-bars');
  container.innerHTML = '';

  for (const key of DRIVE_ORDER) {
    const row = document.createElement('div');
    row.className = `drive-row drive-row--${key}`;

    const label = document.createElement('span');
    label.className = 'drive-row__label';
    label.textContent = DRIVE_LABELS[key];

    const track = document.createElement('div');
    track.className = 'drive-row__track';

    const fill = document.createElement('div');
    fill.className = 'drive-row__fill';
    fill.id = `drive-fill-${key}`;
    track.appendChild(fill);

    // Fatigue threshold line at 0.72
    if (key === 'fatigue') {
      const threshold = document.createElement('div');
      threshold.className = 'drive-row__threshold';
      threshold.style.left = '72%';
      threshold.title = '阈值 0.72';
      track.appendChild(threshold);
    }

    const value = document.createElement('span');
    value.className = 'drive-row__value';
    value.id = `drive-val-${key}`;
    value.textContent = '—';

    row.appendChild(label);
    row.appendChild(track);
    row.appendChild(value);
    container.appendChild(row);
  }

  driveBarsBuilt = true;
}

/* === Render functions === */
function renderDriveBars(scores) {
  if (!driveBarsBuilt) buildDriveBars();

  for (const key of DRIVE_ORDER) {
    const val = scores && scores[key] != null ? scores[key] : 0;
    const pct = Math.min(Math.max(val * 100, 0), 100);

    const fill = $id(`drive-fill-${key}`);
    const valEl = $id(`drive-val-${key}`);

    if (fill) fill.style.width = `${pct}%`;
    if (valEl) valEl.textContent = val.toFixed(2);
  }
}

function renderIntent(intent) {
  const card = $id('intent-card');
  const actionEl = $id('intent-action');
  const reasonEl = $id('intent-reason');
  const scoreEl = $id('intent-score');

  if (!intent || !intent.want_action) {
    actionEl.textContent = '无明确意图';
    reasonEl.textContent = '';
    scoreEl.textContent = '—';
    card.style.borderLeftColor = 'var(--text-dim)';
    return;
  }

  actionEl.textContent = intent.want_action;
  reasonEl.textContent = intent.reason || '';
  scoreEl.textContent = typeof intent.score === 'number' ? intent.score.toFixed(2) : '—';

  // Color the left border by the drive dimension
  const drive = intent.drive_key;
  if (drive && DRIVE_COLORS[drive]) {
    card.style.borderLeftColor = DRIVE_COLORS[drive];
  } else {
    card.style.borderLeftColor = 'var(--text-dim)';
  }
}

function renderThoughts(thoughts) {
  const list = $id('thought-list');
  const empty = $id('thought-empty');

  if (!thoughts || thoughts.length === 0) {
    list.innerHTML = '';
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  // Sort: fixations first, then by strength desc
  const sorted = [...thoughts].sort((a, b) => {
    const aFix = a.kind === 'fixation' ? 1 : 0;
    const bFix = b.kind === 'fixation' ? 1 : 0;
    if (aFix !== bFix) return bFix - aFix;
    return (b.strength || 0) - (a.strength || 0);
  });

  list.innerHTML = sorted.map((t) => {
    const kind = t.kind || 'flit';
    const kindLabel = kind === 'fixation' ? '执念' : '闪念';
    const badgeClass = kind === 'fixation' ? 'thought-item__badge--fixation' : 'thought-item__badge--flit';
    const driveLabel = DRIVE_LABELS[t.drive] || t.drive || '';
    const driveColor = DRIVE_COLORS[t.drive] || 'var(--text-dim)';
    const strength = t.strength != null ? t.strength : 0;
    const pct = Math.min(Math.max(strength * 100, 0), 100);
    const fedInfo = kind === 'fixation' && t.fed_count != null
      ? `<span class="thought-item__fed">喂养 ×${t.fed_count}</span>`
      : '';

    return `
      <li class="thought-item">
        <div class="thought-item__top">
          <span class="thought-item__text">${escapeHtml(t.text || '')}</span>
          <span class="thought-item__badge ${badgeClass}">${kindLabel}</span>
        </div>
        <div class="thought-item__meta">
          <span class="thought-item__drive" style="color:${driveColor}">${driveLabel}</span>
          ${fedInfo}
        </div>
        <div class="thought-item__bar">
          <div class="thought-item__bar-fill" style="width:${pct}%;background:${driveColor}"></div>
        </div>
      </li>`;
  }).join('');
}

function renderSelfDrive(sd) {
  if (!sd) return;
  $id('self-curiosity-floor').textContent =
    sd.curiosity_self_floor != null ? sd.curiosity_self_floor.toFixed(2) : '—';
  $id('self-action-count').textContent =
    sd.today_self_actions != null ? sd.today_self_actions : '—';
  $id('self-last-pulse').textContent =
    sd.last_self_pulse ? formatTime(sd.last_self_pulse) : '—';
}

function renderGates(gates) {
  const container = $id('gates');

  // Build once, then update
  if (container.children.length === 0) {
    container.innerHTML = GATE_NAMES.map((name) => `
      <div class="gate-row">
        <span class="gate-row__name">${name}</span>
        <label class="toggle">
          <input type="checkbox" id="gate-${name}" onchange="toggleGate('${name}', this.checked)">
          <span class="toggle__track"></span>
        </label>
      </div>
    `).join('');
  }

  if (!gates) return;
  for (const name of GATE_NAMES) {
    const input = $id(`gate-${name}`);
    if (input) input.checked = !!gates[name];
  }
}

/* === Fetch & update === */
async function fetchState() {
  try {
    const state = await apiFetch('/api/desire/state');
    clearError();

    renderDriveBars(state.drive || state.scores || state.drives);
    renderIntent(state.intent);
    renderThoughts(state.thoughts);
    renderSelfDrive(state.self_drive);
    renderGates(state.gates);

    // Heartbeat interval
    if (state.heartbeat_interval != null) {
      $id('heartbeat-interval').textContent = state.heartbeat_interval;
    }
  } catch (err) {
    showError(`连接失败: ${err.message}`);
  }
}

/* === Actions === */
async function feedThought() {
  const text = $id('feed-text').value.trim();
  if (!text) return;

  const body = {
    text,
    drive: $id('feed-drive').value,
    kind: $id('feed-kind').value,
    strength: parseFloat($id('feed-strength').value),
  };

  try {
    await apiFetch('/api/desire/feed', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    $id('feed-text').value = '';
    clearError();
    fetchState();
  } catch (err) {
    showError(`注入失败: ${err.message}`);
  }
}

async function manualTick() {
  try {
    await apiFetch('/api/desire/tick', { method: 'POST' });
    clearError();
    fetchState();
  } catch (err) {
    showError(`心跳失败: ${err.message}`);
  }
}

async function satisfyAction(action) {
  try {
    await apiFetch('/api/desire/satisfy', {
      method: 'POST',
      body: JSON.stringify({ action }),
    });
    clearError();
    fetchState();
  } catch (err) {
    showError(`操作失败: ${err.message}`);
  }
}

async function toggleGate(name, enabled) {
  try {
    await apiFetch('/api/desire/gate', {
      method: 'POST',
      body: JSON.stringify({ gate_name: name, enabled }),
    });
    clearError();
  } catch (err) {
    showError(`闸门切换失败: ${err.message}`);
  }
}

/* === Utilities === */
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatTime(ts) {
  try {
    const d = new Date(ts);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
  } catch {
    return ts;
  }
}

/* === Init === */
function init() {
  buildDriveBars();
  renderGates(null);

  // Strength slider live value
  const slider = $id('feed-strength');
  const sliderVal = $id('feed-strength-val');
  slider.addEventListener('input', () => {
    sliderVal.textContent = parseFloat(slider.value).toFixed(2);
  });

  // Feed form
  $id('feed-form').addEventListener('submit', (e) => {
    e.preventDefault();
    feedThought();
  });

  // Initial fetch
  fetchState();

  // Auto-refresh every 5s
  setInterval(fetchState, 5000);
}

document.addEventListener('DOMContentLoaded', init);
