/* Protocol Studio — Phase-0 clickable mock.
   Vanilla JS, hash router. Each screen is a function returning HTML; small
   pieces of interactivity (select block, run Ask, change calculator inputs)
   re-render only the affected region. Intentionally dependency-free so it can
   be opened from disk. */

const $ = (sel, el = document) => el.querySelector(sel);
const h = (strings, ...vals) => strings.map((s, i) => s + (vals[i] ?? '')).join('');
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const state = {
  route: location.hash.slice(1) || '/login',
  section: 3,
  block: 'B-3-4',
  itab: 'inspect',
  ask: [],
  askModel: 'gpt-6-astra',
  calc: { p0: 0.16, p1: 0.45, alpha: 0.05, power: 0.9, ratio: 1, dropout: 0.1, pool: false },
  adminTab: 'users',
  wizardStep: 1,
  libTab: 'works',
};

function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.style.display = 'none'), 2200);
}
function go(path) { location.hash = '#' + path; }
window.addEventListener('hashchange', () => { state.route = location.hash.slice(1); render(); });

/* ---------- shared chrome ---------- */
const ICONS = {
  library: '<svg viewBox="0 0 24 24"><path d="M4 5h4v14H4zM10 5h4v14h-4zM16.5 5.5l3.5 1-3 13-3.5-1z"/></svg>',
  works: '<svg viewBox="0 0 24 24"><path d="M6 3h9l4 4v14H6z"/><path d="M9 12h6M9 16h6M14 3v5h5"/></svg>',
  calc: '<svg viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 12h3M13 12h3M8 16h3M13 16h3"/></svg>',
  admin: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/></svg>',
};
/* Primary navigation: [key, landing route, label, sub-links]. Sub-links are the labelled
   second level shown in the sidebar; `work:` prefix expands to the user's open works. */
const NAV = [
  ['works', '/library', 'Workspace', [['My works', '/library'], ['New from starter', '/new/1'], 'work:']],
  ['library', '/library/studies', 'Library', [['Study library', '/library/studies'], ['Master sheet · AD', '/library/master'], ['Conversion templates', '/library/templates']]],
  ['calc', '/calculator', 'Trial calculator', [['Sample size & history', '/calculator'], ['Endpoint explorer', null, 'Pilot 4b'], ['Criteria comparator', '/editor/W-102', null, "state.itab='compare';render()"]]],
  ['admin', '/admin/users', 'Admin', [['Users', '/admin/users'], ['Works & permissions', '/admin/works'], ['Usage', '/admin/usage'], ['Models & providers', '/admin/models'], ['Audit log', '/admin/audit']]],
];
/* Left sidebar: always labelled. Collapses to icons only when the user asks (« button). */
function rail(active) {
  const route = state.route;
  const sub = ([label, path, soon, pre]) => {
    if (!path) return h`<a class="sub soon" onclick="toast('${label}: planned for ${soon} (mock)')">${label}<span class="k">${soon}</span></a>`;
    return h`<a class="sub ${route === path && !pre ? 'active' : ''}" href="#${path}" ${pre ? h`onclick="${pre}"` : ''}>${label}</a>`;
  };
  const works = () => WORKS.map((w) => h`<a class="sub work ${route === '/editor/' + w.id ? 'active' : ''}" href="#/editor/${w.id}" title="${w.title}"><span class="dot ${w.blocking ? 'err' : 'ok'}"></span><span class="t">${w.title.split(' · ')[0]} · ${w.kind}</span><span class="k">${w.pct}%</span></a>`).join('');
  const group = ([k, path, title, subs]) => h`<div class="group ${active === k ? 'active' : ''}">
    <a class="top" href="#${path}" title="${title}">${ICONS[k]}<span class="label">${title}</span></a>
    ${active === k ? h`<div class="subs">${subs.map((s) => (s === 'work:' ? works() : sub(s))).join('')}</div>` : ''}</div>`;
  return h`<nav class="rail ${state.railCollapsed ? 'collapsed' : ''}">
    <a class="brandrow" href="#/library"><span class="logo">P</span><span class="label">Protocol Studio</span></a>
    ${NAV.map(group).join('')}
    <div class="spacer"></div>
    <a class="collapse" onclick="state.railCollapsed=!state.railCollapsed;render()" title="${state.railCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}">${state.railCollapsed ? '»' : '«'}<span class="label">Collapse</span></a>
    <div class="me ${state.userMenu ? 'open' : ''}" title="Account" onclick="event.stopPropagation();state.userMenu=!state.userMenu;render()"><span class="avatar">BA</span><span class="label"><b>Ben Altman</b><small>ben@sarika.com · admin</small></span><span class="caret">▴</span></div>
  </nav>${state.userMenu ? userMenu() : ''}`;
}
/* Persistent horizontal bar: the same on every screen (Google-Docs-style app header). */
function topnav(active) {
  return h`<header class="topnav">
    ${NAV.map(([k, path, title]) => h`<a class="nav ${active === k ? 'active' : ''}" href="#${path}">${title}</a>`).join('')}
    <div class="grow"></div><input class="search" placeholder="Search works, studies, criteria…  ( / )" onkeydown="if(event.key==='Enter')toast('Search: '+this.value+' (mock)')">
    <span class="env">rev 42 · eu-west-1</span>
    <span class="who" onclick="event.stopPropagation();state.userMenu=!state.userMenu;render()"><span class="avatar">BA</span>Ben</span></header>`;
}
function userMenu() {
  return h`<div class="usermenu" onclick="event.stopPropagation()"><div class="head"><span class="avatar">BA</span><div><b>Ben Altman</b><div class="tiny muted">ben@sarika.com · ${chip('accent', 'admin')}</div></div></div>
    <a onclick="go('/library');state.userMenu=false">My works <span class="k">3</span></a>
    <a onclick="toast('Your permissions: owner W-102, W-098 · edit W-103 (mock)');state.userMenu=false;render()">My permissions</a>
    <a onclick="go('/admin/users');state.userMenu=false">Administration <span class="k">admin</span></a>
    <a onclick="toast('Preferences: theme, keyboard shortcuts, default model (mock)');state.userMenu=false;render()">Preferences <span class="k">,</span></a>
    <a onclick="toast('Keyboard shortcuts panel (mock)');state.userMenu=false;render()">Keyboard shortcuts <span class="k">?</span></a>
    <div class="foot"><a onclick="state.userMenu=false;go('/login')">Sign out</a></div></div>`;
}
function topbar(crumbs, right = '') {
  return h`<header class="topbar"><div class="crumbs">${crumbs}</div><div class="grow"></div>${right}</header>`;
}
function frame(active, crumbs, body, right = '') {
  return h`<div class="app">${rail(active)}${topnav(active)}${topbar(crumbs, right)}<main class="main">${body}</main></div>`;
}
document.addEventListener('click', () => { if (state.userMenu || state.menu) { state.userMenu = false; state.menu = null; render(); } });
function progress(pct, extra = '') {
  return h`<span class="progress"><span class="bar"><b style="width:${pct}%"></b><em style="left:60%" title="design-ready"></em><em style="left:85%" title="operationally specified"></em></span><span class="mono">${pct}%</span>${extra}</span>`;
}
const chip = (cls, text) => h`<span class="chip ${cls}"><i></i>${text}</span>`;

/* ---------- Login ---------- */
function loginView(denied) {
  return h`<div class="login"><div class="box"><div class="mark">P</div>
    <h1>Protocol Studio</h1><div class="muted">Clinical protocol &amp; SAP authoring</div>
    <button class="btn g" onclick="go('/library')">Continue with Google</button>
    <button class="btn ghost g" style="margin-top:6px" onclick="go('/login/denied')">Simulate non-allowlisted account</button>
    ${denied ? '<div class="denied"><b>jon.smith@gmail.com</b> is not authorised for this workspace. An access request has been sent to the administrator (ben@sarika.com).</div>' : ''}
    <div class="tiny muted" style="margin-top:20px">Access is limited to accounts on the administrator's allowlist.</div>
  </div></div>`;
}

/* ---------- Workspace / Library ---------- */
function libraryView(tab) {
  const tabs = h`<div class="tabs">
    <a href="#/library" class="${tab === 'works' ? 'active' : ''}">My works</a>
    <a href="#/library/studies" class="${tab === 'studies' ? 'active' : ''}">Study library</a>
    <a href="#/library/master" class="${tab === 'master' ? 'active' : ''}">Master sheet · Atopic dermatitis</a>
    <a href="#/library/templates" class="${tab === 'templates' ? 'active' : ''}">Templates</a></div>`;
  let body = '';
  if (tab === 'works') {
    body = h`<div class="toolbar"><button class="btn primary" onclick="go('/new')">New protocol from starter</button><button class="btn" onclick="toast('Blank protocol created (mock)')">Blank protocol</button><div class="grow"></div><input class="btn" placeholder="Search works…" style="width:220px"></div>
    <div class="cards">${WORKS.map((w) => h`<div class="card" onclick="go('/editor/${w.id}')"><h4>${esc(w.title)}</h4>
      <div class="meta">${chip('', w.kind)}<span>${w.version}</span><span>· ${w.updated}</span></div>
      <div class="meta">${progress(w.pct)}${w.blocking ? chip('error', w.blocking + ' blocking') : chip('ok', 'no blocking findings')}</div>
      <div class="meta"><span>Starter: ${esc(w.starter)}</span></div>
      <div class="presence" style="margin-top:6px">${w.collaborators.map((c, i) => h`<span style="background:${['#3A4B5E', '#6E4BC4', '#0E7C6B'][i % 3]}">${c}</span>`).join('')}</div></div>`).join('')}</div>`;
  } else if (tab === 'studies') {
    body = h`<div class="toolbar"><button class="btn primary" onclick="toast('Add study: paste a Dropbox/S3/https link or drop PDF · MD · XLSX (mock)')">Add study</button><select class="btn"><option>Indication: Atopic dermatitis</option><option>All</option></select><div class="grow"></div><span class="muted tiny">${STUDIES.length} studies · 7 sources · 1 needs review</span></div>
    <div class="panel"><table class="grid"><thead><tr><th>Study</th><th>Drug · MoA</th><th>Phase</th><th class="num">N</th><th>Endpoints</th><th>Timepoints</th><th>Source / extraction</th><th>State</th></tr></thead><tbody>
    ${STUDIES.map((s) => h`<tr onclick="toast('Study page: parsed sections, arms, assertions with page links (mock)')"><td><b>${esc(s.name)}</b><div class="tiny muted mono">${s.id}</div></td><td>${s.drug}<div class="tiny muted">${s.moa}</div></td><td>${s.phase}</td><td class="num">${s.n}</td><td>${s.endpoints.map((e) => chip('mono', e)).join(' ')}</td><td class="mono">${s.tps.join(' ')}</td><td class="tiny">${s.source}${s.ocr ? ' ' + chip('warning', 'OCR ' + s.ocr) : ''}</td><td>${s.status === 'accepted' ? chip('ok', 'accepted record') : chip('warning', 'needs review')}</td></tr>`).join('')}
    </tbody></table></div>`;
  } else if (tab === 'master') {
    body = h`<div class="toolbar"><select class="btn"><option>Endpoint: EASI-75</option><option>EASI-90</option><option>EASI CFB</option><option>NRS ≥4</option></select><select class="btn"><option>Timepoint: all</option></select><label class="tiny muted" style="display:flex;gap:6px;align-items:center"><input type="checkbox" checked> reviewed records only</label><div class="grow"></div><button class="btn" onclick="toast('Exported master_sheet_AD.xlsx (mock)')">Export XLSX</button></div>
    <div class="panel"><table class="grid"><thead><tr><th>Study</th><th>Arm</th><th>Endpoint</th><th>TP</th><th class="num">%</th><th class="num">n</th><th>Population</th><th>Background / rescue</th><th>Estimand handling</th><th>Evidence</th></tr></thead><tbody>
    ${HIST.map((r) => { const s = STUDIES.find((x) => x.id === r.study); return h`<tr><td>${esc(s.name)}</td><td>${r.arm}</td><td class="mono">${r.endpoint}</td><td class="mono">${r.tp}</td><td class="num">${r.pct.toFixed(1)}</td><td class="num">${r.n}</td><td class="tiny">mod-severe adults</td><td class="tiny">${r.why && r.why.includes('TCS') ? 'TCS allowed' : 'no TCS; rescue → NRI'}</td><td class="tiny">composite (NRI)</td><td>${chip('source', 'p. ' + r.page)}${s.ocr ? ' ' + chip('warning', 'OCR') : ''}</td></tr>`; }).join('')}
    </tbody></table></div>`;
  } else {
    body = h`<div class="cards"><div class="card"><h4>Temtokibart P2b → anti-OX40L class</h4><div class="meta">${chip('inherited', 'template')}<span>used 2×</span><span>saved by BA · 3 d ago</span></div><div class="tiny muted">Mapping accepted 214/221 blocks · 7 dropped (not carried over) · decision register 38 decisions · 12 study-specific re-asked on reuse</div></div>
    <div class="card"><h4>GSK P2b → topical PDE4</h4><div class="meta">${chip('inherited', 'template')}<span>used 1×</span></div><div class="tiny muted">Mapping accepted 188/203 · decision register 31</div></div></div>`;
  }
  return frame(tab === 'works' ? 'works' : 'library', h`<b>Workspace</b>`, h`<div class="page"><h1>${tab === 'works' ? 'Works' : tab === 'studies' ? 'Study library' : tab === 'master' ? 'Master sheet — Atopic dermatitis' : 'Conversion templates'}</h1>${tabs}${body}</div>`);
}

/* ---------- Starter wizard ---------- */
function wizardView(step) {
  const steps = ['Choose starter', 'Split & map to outline', 'Bind & adapt', 'Key inputs', 'Review & create'];
  const side = h`<aside class="steps">${steps.map((s, i) => h`<a href="#/new/${i + 1}" class="${i + 1 < step ? 'done' : ''} ${i + 1 === step ? 'active' : ''}"><i>${i + 1 < step ? '✓' : i + 1}</i>${s}</a>`).join('')}
    <div class="meta">Starter: <b>Temtokibart P2b</b><br>New product: <b>SRK-201</b> (anti-OX40L, SC q4w)<br>Template: <b>found</b> — reusing accepted mapping</div></aside>`;
  let body = '';
  if (step === 1) body = h`<h1>Choose a starter protocol</h1><div class="sub">A starter is a library study with an accepted record. If a conversion template exists for your drug class, mapping and block decisions are reused.</div>
    <div class="field"><label>New product</label><div class="row"><input value="SRK-201"><input value="anti-OX40L monoclonal antibody, SC"></div></div>
    <div class="cards">${STUDIES.slice(0, 4).map((s, i) => h`<div class="card" style="${i === 0 ? 'border-color:var(--accent-700)' : ''}" onclick="go('/new/2')"><h4>${esc(s.name)}</h4><div class="meta">${chip('', s.phase)}<span>${s.drug} · ${s.moa}</span></div><div class="meta">${i === 0 ? chip('inherited', 'template available') : chip('', 'no template — full conversion (~6 min)')}${s.ocr ? chip('warning', 'OCR ' + s.ocr) : ''}</div></div>`).join('')}</div>`;
  if (step === 2) body = h`<h1>Split &amp; map to the universal outline</h1><div class="sub">Source headings → Section 0–14. Unmapped source content is never dropped silently.</div>
    <div class="mapping">${[['Title page, Protocol synopsis', '0 · 1', ''], ['1 Introduction · 1.1 Background · 1.2 Rationale', '2', ''], ['2 Objectives and endpoints', '3', ''], ['3 Study design · 3.1 Overall design · 3.2 Rationale', '4', ''], ['4 Study population', '5', ''], ['5 Study intervention · 5.4 Rescue medication', '6', ''], ['6 Discontinuation', '7', ''], ['7 Assessments · Appendix 2 SoA', '8', ''], ['8 Adverse events', '9', ''], ['9 Statistics', '10', ''], ['10 Supporting documentation', '11 · 12', ''], ['Appendix 5: Temtokibart pharmacology summary', '—', 'unmapped']].map(([a, b, c]) => h`<div class="row"><div class="cell">${esc(a)}</div><div class="arrow">→</div><div class="cell ${c}">${c ? 'Not carried over — review required <span class="tiny muted">(drug-specific; propose §2.1 background for SRK-201 instead)</span>' : 'Section ' + b}</div></div>`).join('')}</div>
    <div class="toolbar" style="margin-top:16px"><button class="btn primary" onclick="go('/new/3')">Accept mapping (from template)</button><span class="tiny muted">221 blocks · 214 mapped · 7 not carried over</span></div>`;
  if (step === 3) body = h`<h1>Bind &amp; adapt</h1><div class="sub">Each block is bound to model objects; blocks bound to the old product are classified by the model, then decided by you. Nothing here is a find-and-replace.</div>
    <div class="cols3"><div class="col"><h4>${chip('ok', 'keep')} 162</h4>
      <div class="bcard"><div class="src">Participants will be randomised 1:1:1 to receive …</div><div class="why">Bound to allocation AL-01 — product-independent.</div></div>
      <div class="bcard"><div class="src">EASI-75 is defined as ≥75% improvement from baseline in EASI score.</div><div class="why">Definition of EP-02 — product-independent.</div></div></div>
    <div class="col"><h4>${chip('proposed', 'adapt')} 41</h4>
      <div class="bcard proposed"><div class="src"><del class="muted">Temtokibart 300 mg SC at Weeks 0, 2, 4, 6, 8, 12</del><br><ins>SRK-201 [dose] SC every 4 weeks from Week 0 to Week 12</ins></div><div class="why">Bound to RG-01. Interval differs (q2w → q4w) — asks Q1. Loading dose unknown — asks Q1.</div><div class="tags">${chip('proposed', 'proposal')}${chip('', 'Q1')}</div></div>
      <div class="bcard proposed"><div class="src"><del class="muted">Prior IL-22-targeted therapy within 12 weeks</del> <ins>Prior OX40/OX40L-targeted therapy within [washout]</ins></div><div class="why">Exclusion CR-14 refers to the class of the old product. Washout asks Q3.</div><div class="tags">${chip('proposed', 'proposal')}${chip('', 'Q3')}</div></div></div>
    <div class="col"><h4>${chip('na', 'drop / add')} 18</h4>
      <div class="bcard"><div class="src">IL-22 receptor occupancy will be measured at Weeks 0 and 16.</div><div class="why">Mechanism-specific PD assessment → <b>Not carried over — review required</b>.</div></div>
      <div class="bcard proposed"><div class="src"><ins>Cytokine release–related reactions will be monitored for 2 h after the first two administrations.</ins></div><div class="why">Proposed addition: class-typical for T-cell co-stimulation blockers. Confirm via Q4.</div><div class="tags">${chip('proposed', 'proposal')}${chip('', 'Q4')}</div></div></div></div>
    <div class="toolbar" style="margin-top:16px"><button class="btn primary" onclick="go('/new/4')">Continue to key inputs</button><span class="tiny muted">You will review every proposal in the editor; nothing is approved here.</span></div>`;
  if (step === 4) body = h`<h1>Key inputs</h1><div class="sub">Decision register: 38 decisions · 21 answered by starter · 5 derived · 12 open or study-specific. Grouping reduced 19 questions to 7 prompts; every decision still maps to an answer.</div>
    <div class="rounds"><span class="r">register <b>38</b></span><span class="arr">→</span><span class="r">open <b>19</b></span><span class="arr">→</span><span class="r">grouped <b>7</b> prompts</span><span class="arr">→</span><span class="r">coverage <b>38/38</b> ✓</span></div>
    ${QUESTIONS.map((q) => h`<div class="qcard"><div class="q">${esc(q.q)}</div><div class="qmeta">${chip('', q.pkg)}${q.covers.map((c) => chip('mono', c)).join('')}${q.status.startsWith('merged') ? chip('na', q.status) : q.status.startsWith('derived') ? chip('derived', q.status) : q.status.startsWith('inherited') ? chip('inherited', q.status) : chip('incomplete', 'open')}</div>
      ${q.status.startsWith('merged') ? '' : q.type === 'choice' ? h`<div class="ans">${q.opts.map((o, i) => h`<label style="display:block"><input type="radio" name="${q.id}" ${i === 0 ? 'checked' : ''}> ${esc(o)}</label>`).join('')}</div>` : h`<div class="ans"><input class="btn" style="width:100%" placeholder="${q.prefill ? '' : 'Your answer'}" value="${q.prefill || ''}"></div>`}</div>`).join('')}
    <div class="toolbar"><button class="btn primary" onclick="go('/new/5')">Save answers</button><button class="btn" onclick="toast('Why these questions? Each prompt lists the decision_ids it covers (mock)')">Why these questions?</button></div>`;
  if (step === 5) body = h`<h1>Review &amp; create</h1><div class="sub">A new work is created from the template and your answers. All adapted content is <i>proposed</i> and unapproved.</div>
    <div class="kpis"><div class="kpi"><div class="v">64%</div><div class="l">complete (approved &amp; applicable slots)</div></div><div class="kpi"><div class="v">59</div><div class="l">proposals to review</div></div><div class="kpi"><div class="v">7</div><div class="l">not carried over — review required</div></div><div class="kpi"><div class="v">5</div><div class="l">blocking findings (rev 1)</div></div></div>
    <label class="tiny" style="display:flex;gap:8px;align-items:center;margin-bottom:12px"><input type="checkbox" checked> Save as template <b>"Temtokibart P2b → anti-OX40L"</b> (mapping + block decisions + decision register; study-specific answers are re-asked on reuse)</label>
    <button class="btn primary" onclick="go('/editor/W-102')">Create work SRK-201</button>`;
  return h`<div class="app">${rail('works')}${topnav('works')}${topbar(h`<a href="#/library">Workspace</a><span class="sep">/</span><b>New protocol from starter</b>`)}<main class="main"><div class="wizard">${side}<div class="wbody">${body}</div></div></main></div>`;
}

/* ---------- Editor ---------- */
const BLOCKS_S3 = [
  { id: 'B-3-1', kind: 'h2', text: '3.1 Primary Objective and Associated Estimand' },
  { id: 'B-3-2', prov: 'inherited', text: 'To evaluate the efficacy of SRK-201 compared with placebo in adults with moderate-to-severe atopic dermatitis.', bind: ['OBJ-01'], claims: [{ s: 'checked', t: 'OBJ-01 population = POP-01' }] },
  { id: 'B-3-3', prov: 'derived', text: 'The primary endpoint is the proportion of participants achieving <span class="linknum" title="EP-02 · derived">EASI-75</span> at <span class="linknum" title="EP-02.time_reference.week = 16 · rev 41">Week 16</span>.', bind: ['EP-02'], claims: [{ s: 'checked', t: 'EP-02.time_reference = W16' }], gen: true },
  { id: 'B-3-4', prov: 'proposed', text: 'Rescue treatment for atopic dermatitis will be handled using a <u class="warn">composite strategy</u>: participants who receive rescue treatment before Week 16 will be considered non-responders. Discontinuation of trial intervention for other reasons will be handled using a <u class="err">hypothetical strategy</u>.', bind: ['EST-01', 'EV-03'], claims: [{ s: 'checked', t: 'EST-01.event_strategies[rescue] = composite' }, { s: 'mismatch', t: 'EST-01.event_strategies[discontinuation] = treatment_policy (model) vs hypothetical (text)' }] },
  { id: 'B-3-5', prov: 'author', text: 'The population-level summary is the difference in response proportions between SRK-201 and placebo, with a 95% confidence interval.', bind: ['EST-01'], claims: [{ s: 'checked', t: 'EST-01.population_summary = risk difference' }] },
  { id: 'B-3-6', kind: 'h2', text: '3.2 Secondary Objectives and Associated Estimands' },
  { id: 'B-3-7', prov: 'inherited', text: 'To evaluate the effect of SRK-201 on <span class="linknum">EASI-90</span>, <span class="linknum">IGA 0/1 with ≥2-grade improvement</span> and <span class="linknum">Peak Pruritus NRS ≥4-point improvement</span> at Week 16.', bind: ['OBJ-02', 'EP-03', 'EP-04', 'EP-05'], claims: [{ s: 'checked', t: '3 endpoints bound' }] },
  { id: 'B-3-8', prov: 'author', text: '<span class="ph">Estimand for EP-04 (IGA 0/1): population-level summary not yet specified.</span>', bind: ['EST-02'], claims: [{ s: 'unbound', t: 'EST-02.population_summary — required slot empty (R12)' }] },
  { id: 'B-3-9', kind: 'h2', text: '3.3 Exploratory Objectives <span class="cond">{optional}</span>' },
  { id: 'B-3-10', prov: 'author', text: 'Not applicable — no exploratory objectives are planned for this trial.', na: true, bind: [], claims: [] },
];

function editorView(workId) {
  const w = WORKS.find((x) => x.id === workId) || WORKS[0];
  const sec = OUTLINE[state.section];
  const dots = (s) => h`<span class="dots">${s.err ? '<i style="background:var(--state-error)"></i>' : ''}${s.warn ? '<i style="background:var(--state-warning)"></i>' : ''}${s.inc ? '<i style="background:var(--state-incomplete)"></i>' : ''}</span>`;
  const outline = h`<div class="outline"><div class="hdr"><span>Sections · ICH M11</span><span>${OUTLINE.reduce((a, s) => a + s.err, 0)} blocking</span></div>
    ${OUTLINE.map((s) => h`<div class="sec ${s.n === state.section ? 'active' : ''} ${s.n === 0 ? 'section0' : ''}" onclick="selectSection(${s.n})" title="${s.m11}"><span class="n">${s.n}</span><span class="t">${esc(s.title)}</span><span class="pct">${s.pct}%${dots(s)}</span>
      ${s.n === state.section ? h`<span class="d">${s.m11} · ${s.err} blocking · ${s.warn} warnings · ${s.inc} required slots open</span><span class="bar"><b style="width:${s.pct}%"></b></span>` : ''}</div>`).join('')}
    <div class="foot"><div class="tiny muted" style="margin-bottom:4px">Overall completion (approved, applicable required slots)</div>${progress(w.pct, h`<a href="#" onclick="setSide('workflow');return false">what's left</a>`)}<div class="tiny muted" style="margin-top:6px">Design-ready ✓ · Operationally specified ✗ (R04, R11) · Formal review ✗</div></div></div>`;
  const stabs = ['outline', 'workflow', 'analysis'];
  const sidebar = h`<aside class="sidebar"><div class="stabs">${stabs.map((t) => h`<a href="#" class="${(state.side || 'outline') === t ? 'active' : ''}" onclick="setSide('${t}');return false">${t}</a>`).join('')}</div>
    ${(state.side || 'outline') === 'outline' ? outline : state.side === 'workflow' ? workflowHtml(w) : analysisHtml(w)}</aside>`;

  const canvas = state.section === 3 ? BLOCKS_S3.map(blockHtml).join('') : h`<h2>${esc(sec.m11)}</h2><div class="gen-note">Mock: only Section 3 is populated in this clickable mock. Other sections show the same block model.</div>${state.section === 8 ? soaHtml() : h`<div class="block author"><span class="ph">Section ${sec.n} content …</span></div>`}`;
  const canvasWrap = h`<section class="canvas-wrap"><article class="canvas"><h1>${esc(sec.m11)} <span class="heading-tag">Section ${sec.n} · ${sec.pct}% · ${sec.err} blocking</span></h1>${canvas}</article></section>`;

  return h`<div class="app no-topbar">${rail('works')}${topnav('works')}
    <main class="main" style="display:flex;flex-direction:column;overflow:hidden">${docHead(w)}<div class="editor">${sidebar}${canvasWrap}${inspector()}</div></main></div>`;
}

/* Google-Docs-style document header: title row, menu bar, formatting toolbar. */
const MENUS = {
  File: [['New from starter…', ''], ['Open…', '⌘O'], ['Create version…', ''], ['Version history', ''], ['-'], ['Export → PDF (LaTeX)', ''], ['Export → DOCX', ''], ['Export model (JSON)', ''], ['-'], ['Share & permissions…', ''], ['Document details', '']],
  Edit: [['Undo', '⌘Z'], ['Redo', '⇧⌘Z'], ['-'], ['Find in document', '⌘F'], ['Find object (EP-, EST-, …)', '⌘K'], ['-'], ['Mark block Not applicable', ''], ['Revert text to model', '']],
  View: [['Show provenance borders', '✓'], ['Show claim underlines', '✓'], ['Show generated views', '✓'], ['-'], ['Reading mode (M11 render)', ''], ['Compare with v0.2', ''], ['Suggesting mode', '']],
  Insert: [['Section (from M11 outline)', ''], ['Table', ''], ['Generated view: SoA / endpoint table / synopsis', ''], ['Reference', ''], ['Comment', '⌘⌥M'], ['Proposal from Ask…', '']],
  Format: [['Heading level', ''], ['Bold / Italic / Underline', ''], ['Bulleted / numbered list', ''], ['-'], ['M11 text class: universal / optional / instructional', '']],
  Tools: [['Run checks now', ''], ['Trial calculator', ''], ['Criteria comparator', ''], ['Decision register', ''], ['Readiness report', '']],
  Model: [['Ask about selection…', '⌘⇧A'], ['Draft rationale', ''], ['Suggest rewrite', ''], ['Explain finding', ''], ['-'], ['Context sent to model…', ''], ['Model: GPT-6 Astra', '']],
  Help: [['Keyboard shortcuts', '?'], ['ICH M11 guidance', ''], ['E9(R1) estimands', ''], ['About Protocol Studio', '']],
};
function docHead(w) {
  return h`<div class="dochead"><div class="title"><span class="docicon"></span><div><h2>${esc(w.title)}</h2><div class="sub">${w.kind} · ${w.version} · rev 42 · Starter: ${esc(w.starter)}</div></div><div class="grow"></div>
      <span class="save-status"><i></i>All changes saved · 8 s ago</span><div class="presence"><span style="background:#3A4B5E" title="Ben Altman">BA</span><span style="background:#6E4BC4" title="Maya K. · editing §10">MK</span></div>
      <button class="btn sm" onclick="toast('Share: per-user view / comment / edit; data class confidential (mock)')">Share</button><button class="btn sm" onclick="toast('Create version: semantic diff vs v0.2; readiness predicate lists failing clauses (mock)')">Create version</button><button class="btn sm primary" onclick="toast('Export → PDF (LaTeX/Tectonic) · DOCX; job queued (mock)')">Export</button></div>
    <nav class="menubar">${Object.keys(MENUS).map((m) => h`<a class="${state.menu === m ? 'open' : ''}" onclick="event.stopPropagation();state.menu=state.menu==='${m}'?null:'${m}';render()">${m}${state.menu === m ? h`<div class="dd">${MENUS[m].map(([l, k]) => l === '-' ? '<hr>' : h`<div onclick="toast('${esc(l)} (mock)')">${esc(l)}<span class="k">${k}</span></div>`).join('')}</div>` : ''}</a>`).join('')}</nav>
    <div class="doctools">${['↶', '↷'].map((x) => h`<button title="Undo/Redo">${x}</button>`).join('')}<span class="sep"></span>
      <select><option>Body text</option><option>Heading 2</option><option>Heading 3</option><option>Instructional (remove before final)</option></select><span class="sep"></span>
      <button style="font-weight:700">B</button><button style="font-style:italic">I</button><button style="text-decoration:underline">U</button><span class="sep"></span>
      <button title="Bulleted list">•≡</button><button title="Numbered list">1≡</button><button title="Table">▦</button><span class="sep"></span>
      <button onclick="toast('Comment (mock)')">💬 Comment</button><button onclick="setTab('ask')">✦ Ask model</button><button class="on" title="Editing mode">✎ Editing</button><span class="sep"></span>
      <button onclick="setSide('analysis')">Analysis</button><button onclick="setTab('findings')">Findings · ${FINDINGS.length}</button></div></div>`;
}
function workflowHtml(w) {
  const stages = [['Starter conversion', 'done', 'template applied · 38 decisions answered'], ['Draft & bind', 'now', '59 proposals to review · 7 not carried over'], ['Checks', 'now', '5 blocking · 3 warnings · 2 candidates to adjudicate'], ['Internal review', '', 'reviewers: MK (stats), Priya S. (regulatory)'], ['Version v0.4', '', 'readiness: formal review ✗'], ['Export & submit', '', 'PDF (LaTeX) + DOCX']];
  return h`<div class="wf"><h5 style="margin-top:0">Workflow · ${esc(w.id)}</h5>${stages.map(([n, s, d], i) => h`<div class="stage ${s}"><i>${s === 'done' ? '✓' : i + 1}</i><div><b>${n}</b><div class="tiny">${d}</div></div></div>`).join('')}
    <h5>What's left (your queue)</h5>
    ${[[59, 'proposals awaiting approval', "setTab('inspect')"], [5, 'blocking findings', "setTab('findings')"], [7, 'blocks not carried over — review', "selectSection(2)"], [12, 'study-specific decisions to confirm', "toast('Decision register (mock)')"], [2, 'candidate findings to adjudicate', "setTab('findings')"], [3, 'open comments (MK)', "toast('Comments (mock)')"]].map(([n, t, a]) => h`<div class="task" onclick="${a}"><span class="n">${n}</span><span>${t}</span></div>`).join('')}
    <h5>Readiness predicates</h5>
    ${[['Design-ready', true, 'objectives, endpoints, estimands, design bound'], ['Operationally specified', false, 'R04 SoA gap · R11 rescue rule unlinked'], ['Ready for formal review', false, '5 errors · 2 candidates · 12 decisions']].map(([n, ok, d]) => h`<div class="stage ${ok ? 'done' : ''}"><i>${ok ? '✓' : '✗'}</i><div><b>${n}</b><div class="tiny">${d}</div></div></div>`).join('')}</div>`;
}
function analysisHtml(w) {
  const prov = [['source', 31], ['inherited', 38], ['derived', 12], ['proposed', 14], ['author', 5]];
  const colors = { source: 'var(--prov-source)', inherited: 'var(--prov-inherited)', derived: 'var(--prov-derived)', proposed: 'var(--prov-proposed)', author: 'var(--slate-400)' };
  return h`<div class="an"><h5 style="margin-top:0">Document analysis · rev 42</h5>
    <div class="tiny muted" style="margin-bottom:8px">Completion per section (bar) with blocking findings (red ticks). Click a row to jump.</div>
    ${OUTLINE.map((s) => h`<div class="hbar" onclick="selectSection(${s.n})"><span class="n">${s.n}</span><span class="t"><b style="width:${s.pct}%"></b>${Array.from({ length: s.err }).map((_, i) => h`<s style="left:${s.pct + 3 + i * 5}%"></s>`).join('')}</span><span class="v">${s.pct}%</span></div>`).join('')}
    <h5>Provenance mix (blocks)</h5><div class="stack">${prov.map(([k, v]) => h`<i style="width:${v}%;background:${colors[k]}"></i>`).join('')}</div><div class="lg">${prov.map(([k, v]) => h`<span><i style="background:${colors[k]}"></i>${k} ${v}%</span>`).join('')}</div>
    <h5>Findings by check type</h5>
    ${[['Model consistency (R03/R07/R10/R13)', 3, 'error'], ['Structure & required slots (R01/R12)', 1, 'error'], ['Schedule ↔ endpoints (R04)', 1, 'error'], ['Estimand & rescue links (R11/R14)', 2, 'warning'], ['Change impact (R22)', 1, 'warning']].map(([t, n, s]) => h`<div class="finding" style="padding:5px 0"><span class="sev ${s}" style="width:10px;height:10px;margin-top:4px"></span><div class="msg" style="font-size:12px">${t} <b class="mono">${n}</b></div></div>`).join('')}
    <h5>Claims coverage</h5><div class="tiny">214 sentences · <b>171 checked</b> · 2 mismatch · 9 unbound · 3 ambiguous · 29 no claim (narrative)</div>
    <h5>Cross-section dependencies of §${state.section}</h5>
    ${[['EP-02 (EASI-75 W16)', '§1 synopsis · §8 SoA · §10.2 primary analysis'], ['EST-01', '§10.3 estimator · SAP §4.1'], ['RL-03 rescue rule', '§6.5 rescue · §7.2 discontinuation']].map(([a, b]) => h`<div class="dep"><b>${a}</b> → <span class="mono">${b}</span></div>`).join('')}
    <h5>Model usage on this document</h5><div class="tiny">gpt-6-astra · 41 adapt proposals · 3 Ask threads · 184k tokens · $6.90 · all calls: data class confidential → approved</div></div>`;
}
function setSide(t) { state.side = t; render(); }
function blockHtml(b) {
  if (b.kind === 'h2') return h`<h2>${b.text}</h2>`;
  const sel = b.id === state.block ? 'selected' : '';
  return h`<div class="block ${b.prov} ${sel} ${b.gen ? 'generated' : ''}" ${b.gen ? '' : 'contenteditable="true" spellcheck="false"'} onclick="selectBlock('${b.id}')">${b.text}
    <span class="bmenu" contenteditable="false"><button class="btn sm ghost" onclick="event.stopPropagation();askAbout('${b.id}')">Ask</button><button class="btn sm ghost" onclick="event.stopPropagation();toast('Comment thread (mock)')">Comment</button></span>
    <span class="btags" contenteditable="false">${chip(b.prov, b.prov)}${b.na ? chip('na', 'not applicable') : ''}${b.prov === 'proposed' ? chip('incomplete', 'unapproved') : chip('ok', 'approved · rev 37')}${b.bind.map((x) => chip('mono', x)).join('')}</span></div>`;
}
function soaHtml() {
  const cols = ['Scr', 'W0', 'W2', 'W4', 'W8', 'W12', 'W16', 'EOS'];
  const rows = [['Informed consent', 'x', '', '', '', '', '', '', ''], ['Randomisation', '', 'x', '', '', '', '', '', ''], ['SRK-201 / placebo SC', '', 'x', '', 'x', 'x', 'x', '', ''], ['EASI', 'x', 'x', 'x', 'x', 'x', 'x', '<u class="err">—</u>', 'x'], ['IGA', 'x', 'x', 'x', 'x', 'x', 'x', 'x', 'x'], ['Peak Pruritus NRS (daily)', '', '←', '', '', '', '', '→', ''], ['ADA sample', '', 'x', '', 'x', '', '', 'x', 'x']];
  return h`<div class="block derived selected generated" style="margin-bottom:26px"><div class="gen-note">Generated view — schedule of activities is rendered from <span class="mono">scheduled_activities</span>. Edit through the model (Inspector), not here.</div>
    <table><thead><tr><th>Activity</th>${cols.map((c) => h`<th>${c}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => h`<tr>${r.map((c, i) => h`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>
    <span class="btags">${chip('derived', 'derived')}${chip('error', 'R04: EASI missing at W16 (EP-02)')}</span></div>`;
}
function inspector() {
  const b = BLOCKS_S3.find((x) => x.id === state.block) || BLOCKS_S3[3];
  const tabs = ['inspect', 'findings', 'ask', 'compare', 'history'];
  const head = h`<div class="itabs">${tabs.map((t) => h`<a href="#" class="${state.itab === t ? 'active' : ''}" onclick="setTab('${t}');return false">${t[0].toUpperCase() + t.slice(1)}${t === 'findings' ? ' · ' + FINDINGS.length : ''}</a>`).join('')}</div>`;
  let body = '';
  if (state.itab === 'inspect') body = h`
    <div class="sect"><h5>Block ${b.id}</h5><div style="display:flex;gap:4px;flex-wrap:wrap">${chip(b.prov, 'provenance: ' + b.prov)}${b.prov === 'proposed' ? chip('incomplete', 'approval: unreviewed') : chip('ok', 'approval: MK · rev 37')}${chip(b.claims.some((c) => c.s === 'mismatch') ? 'error' : 'ok', 'validation @ rev 42: ' + (b.claims.some((c) => c.s === 'mismatch') ? '1 finding' : 'pass'))}${chip(b.na ? 'na' : '', 'applicability: ' + (b.na ? 'N/A' : 'applies'))}</div>
      ${b.prov === 'proposed' ? h`<div class="toolbar" style="margin:10px 0 0"><button class="btn sm primary" onclick="toast('Approved by BA at rev 43 · provenance stays proposed (mock)')">Approve</button><button class="btn sm">Edit</button><button class="btn sm danger">Reject</button><button class="btn sm ghost" onclick="toast('Why: adapted from Temtokibart P2b p. 52 by gpt-6-astra (prompt adapt-v3); rescue strategy kept from starter; Q6 confirmed composite')">Why?</button></div>` : ''}</div>
    <div class="sect"><h5>Bound objects</h5><dl class="kv">${b.bind.map((x) => h`<dt class="mono">${x}</dt><dd>${{ 'EST-01': 'Primary estimand · EP-02 · POP-01 · rescue: composite · discontinuation: treatment policy · risk difference', 'EV-03': 'Intercurrent event: rescue treatment (linked rule RL-03 — no policy ⇢ R11)', 'EP-02': 'EASI-75 at Week 16 · responder · binary', 'OBJ-01': 'Primary objective', 'EST-02': 'Estimand for EP-04 — population summary missing', 'OBJ-02': 'Secondary objectives', 'EP-03': 'EASI-90 W16', 'EP-04': 'IGA 0/1 W16', 'EP-05': 'PP-NRS ≥4 W16' }[x] || ''}</dd>`).join('') || '<dd class="muted">none</dd>'}</dl></div>
    <div class="sect"><h5>Sentence claims</h5>${b.claims.map((c) => h`<div class="finding"><span class="sev ${c.s === 'mismatch' ? 'error' : c.s === 'unbound' ? 'incomplete' : 'info'}" style="${c.s === 'checked' ? 'background:var(--state-ok)' : ''}"></span><div class="msg"><b class="mono tiny">${c.s}</b> · ${esc(c.t)}${c.s === 'mismatch' ? '<div class="acts"><button class="btn sm" onclick="toast(\'Command set_field EST-01.event_strategies[discontinuation]=hypothetical @ expected_revision 42 → R22 impact: §1, §10 (mock)\')">Update model</button><button class="btn sm ghost">Revert text</button></div>' : ''}</div></div>`).join('') || '<div class="muted tiny">No claims</div>'}</div>
    <div class="sect"><h5>Source evidence</h5><div class="evidence"><div class="thumb"><i></i></div><div class="tiny"><b>Temtokibart P2b protocol v3.0</b><br>p. 52 · §3.1.2 Estimand<br><span class="muted">"Participants who receive rescue … will be considered non-responders."</span><br>${chip('source', 'observed')} ${chip('', 'text layer')}</div></div></div>`;
  if (state.itab === 'findings') body = h`<div class="sect"><h5>Findings · rev 42 · all checks current</h5><div class="tiny muted" style="margin-bottom:6px">${FINDINGS.filter((f) => f.sev === 'error').length} blocking · ${FINDINGS.filter((f) => f.sev === 'warning').length} warnings · candidates need adjudication</div>
    ${FINDINGS.map((f) => h`<div class="finding"><span class="sev ${f.sev}"></span><div class="msg"><span class="mono tiny">${f.rule}</span> · §${f.sec} ${f.candidate ? chip('warning', 'candidate') : ''}<br>${esc(f.msg)}<div class="acts"><button class="btn sm" onclick="selectSection(${f.sec})">Go to §${f.sec}</button>${f.candidate ? '<button class="btn sm">Accept</button><button class="btn sm ghost">Dismiss</button>' : ''}<button class="btn sm ghost" onclick="askAbout(null,'${f.id}')">Ask</button></div></div></div>`).join('')}</div>`;
  if (state.itab === 'ask') body = askHtml();
  if (state.itab === 'compare') body = compareHtml();
  if (state.itab === 'history') body = h`<div class="sect"><h5>Revisions (this block)</h5>${[['rev 42', 'MK', 'edited narrative (claim → mismatch)', '2 min ago'], ['rev 41', 'BA', 'set EP-02.time_reference W12→W16', '14 min ago'], ['rev 37', 'MK', 'approved block', 'yesterday'], ['rev 12', 'pipeline', 'inserted proposal (adapt-v3, gpt-6-astra)', '3 d ago']].map((r) => h`<div class="finding"><span class="sev info"></span><div class="msg"><span class="mono tiny">${r[0]}</span> · ${r[1]} · ${r[2]}<div class="tiny muted">${r[3]}</div></div></div>`).join('')}</div>
    <div class="sect"><h5>Versions</h5>${[['v0.2', 'draft quality', '3 d ago'], ['v0.1', 'draft quality', '9 d ago']].map((v) => h`<div class="finding"><span class="sev info"></span><div class="msg"><b>${v[0]}</b> · ${v[1]} <div class="tiny muted">${v[2]} · frozen at one revision: model + AST + PDF/DOCX + findings + dispositions</div></div></div>`).join('')}</div>`;
  return h`<aside class="inspector">${head}<div style="flex:1;overflow:auto;display:flex;flex-direction:column">${body}</div></aside>`;
}
function compareHtml() {
  return h`<div class="sect"><h5>Criterion (§5.2 IN-03)</h5><div class="crit">EASI ≥ 16 at screening and baseline</div><div class="tiny muted" style="margin-top:4px">predicate: EASI ≥ 16 @ {screening, baseline}</div></div>
    <div class="sect"><h5>Similar criteria · 6 AD studies</h5>${CRITERIA_SIMILAR.map((c) => h`<div class="finding"><span class="sev info" style="background:${c.diff.length ? 'var(--state-warning)' : 'var(--state-ok)'}"></span><div class="msg"><b>${esc(c.study)}</b> ${chip('source', 'p. ' + c.page)}${c.ocr ? chip('warning', 'OCR ' + c.ocr) : ''}<div class="crit diff" style="font-size:13px">${diffText(c.text)}</div>${c.diff.length ? h`<div class="tiny">${c.diff.map((d) => chip('warning', d)).join(' ')}</div>` : '<div class="tiny muted">identical</div>'}<div class="acts"><button class="btn sm ghost" onclick="toast('Adopted as proposed block with provenance ' + ${JSON.stringify(esc(c.study))} + ' p. ${c.page} (mock)')">Adopt wording</button></div></div></div>`).join('')}</div>`;
}
function diffText(t) {
  return esc(t).replace(/≥ 12/g, '<mark>≥ 12</mark>').replace(/IGA ≥ 3/g, '<ins>IGA ≥ 3</ins>').replace(/BSA ≥ 10%/g, '<ins>BSA ≥ 10%</ins>').replace(/at baseline(?!,)/g, 'at <del>screening and </del>baseline');
}

/* Ask thread */
function askHtml() {
  const b = BLOCKS_S3.find((x) => x.id === state.block) || BLOCKS_S3[3];
  return h`<div class="ask"><div class="msgs" id="askmsgs">
    <div class="tiny muted">Context: block <span class="mono">${b.id}</span> · ${b.bind.join(', ') || 'no bindings'} · 1 finding · source p. 52. Data class: <b>confidential</b> → only providers approved for confidential are listed.</div>
    ${state.ask.map((m) => m.role === 'user' ? h`<div class="msg user">${esc(m.text)}</div>` : h`<div class="msg model"><div class="who">${chip('accent', m.model)}<span>${m.ms ? m.ms + ' ms · ' + m.tok + ' tok · $' + m.cost : 'streaming…'}</span></div><div class="${m.done ? '' : 'cursor'}">${m.html}</div>${m.proposal ? h`<div class="proposal">${m.proposal}<div class="acts"><button class="btn sm primary" onclick="toast('Inserted as proposed block (unapproved) at rev 43 — Approve is a separate action (mock)')">Insert as proposal</button><button class="btn sm">Edit</button><button class="btn sm ghost">Dismiss</button></div></div>` : ''}${m.done ? h`<details><summary>Context sent (${m.ctx})</summary>EST-01, EV-03, RL-03 · finding F-2 · source p. 52 excerpt · E9(R1) strategy definitions · prompt explain-finding-v2</details>` : ''}</div>`).join('')}
    </div><div class="composer"><div class="chips">${['Explain this finding', 'Draft rationale', 'Rewrite for composite strategy', 'Compare with Dupilumab SOLO 1'].map((c) => h`<span class="chip" onclick="askSend(${JSON.stringify(c)})">${c}</span>`).join('')}</div>
    <div class="in"><select onchange="state.askModel=this.value"><option value="gpt-6-astra">GPT-6 Astra</option><option value="grok-4" disabled>Grok 4 — not approved for confidential</option></select><input id="askin" placeholder="Ask about this block…" onkeydown="if(event.key==='Enter')askSend(this.value)"><button class="btn primary sm" onclick="askSend($('#askin').value)">Send</button></div></div></div>`;
}
const ASK_ANSWERS = {
  default: { html: 'Finding <b>R14</b> flags that analysis AN-04 changes the <i>estimand</i> (hypothetical → treatment policy) while being labelled a <i>sensitivity</i> analysis. Per ICH E9(R1) §A.5.2, a sensitivity analysis targets the <b>same estimand</b> under different assumptions (e.g. missing-data mechanisms); an analysis of a different estimand is <b>supplementary</b>. Two options: relabel AN-04 as supplementary (model command, no text change elsewhere), or keep it as sensitivity and change its event strategy to match EST-01. I would relabel: the SAP §4.3 already describes it as addressing a different question.', ctx: '6 objects' },
  rewrite: { html: 'Here is a version aligned with EST-01 as currently modelled (rescue: composite; discontinuation: <b>treatment policy</b>, which is what the model holds — your text says hypothetical, hence the mismatch):', proposal: 'Rescue treatment for atopic dermatitis will be handled using a composite strategy: participants who receive rescue treatment before Week 16 will be considered non-responders. Discontinuation of trial intervention for other reasons will be handled using a treatment policy strategy; the observed Week 16 value will be used regardless of discontinuation.', ctx: '7 objects' },
  compare: { html: 'Dupilumab SOLO 1 (FDA review p. 28) used a composite strategy for rescue (rescue = non-responder) and treatment policy for discontinuation — the same combination as EST-01 in the model. It also excluded participants who used TCS within 1 week of baseline, which your §5 does not; if you rely on SOLO 1 placebo rates in the calculator, that difference is flagged in the comparability filter.', ctx: '9 objects' },
};
function askSend(text) {
  if (!text) return;
  state.ask.push({ role: 'user', text });
  const key = /rewrite/i.test(text) ? 'rewrite' : /compare/i.test(text) ? 'compare' : 'default';
  const a = ASK_ANSWERS[key];
  const m = { role: 'model', model: state.askModel, html: '', done: false, ctx: a.ctx };
  state.ask.push(m);
  state.itab = 'ask'; render();
  const words = a.html.split(' '); let i = 0;
  const tick = setInterval(() => {
    m.html = words.slice(0, ++i).join(' ');
    if (i >= words.length) { clearInterval(tick); m.done = true; m.ms = 1840; m.tok = 612; m.cost = '0.012'; if (a.proposal) m.proposal = a.proposal; }
    render(); const el = $('#askmsgs'); if (el) el.scrollTop = el.scrollHeight;
  }, 35);
}
function askAbout(blockId, findingId) { if (blockId) state.block = blockId; state.itab = 'ask'; render(); }
function selectBlock(id) { if (state.block === id) return; state.block = id; if (state.itab === 'findings') state.itab = 'inspect'; render(); }
function selectSection(n) { state.section = n; render(); }
function setTab(t) { state.itab = t; render(); }

/* ---------- Calculator ---------- */
function sampleSize(p0, p1, alpha, power, ratio) {
  // Two-proportion, normal approximation, unequal allocation (k = ratio active:placebo). Illustrative.
  const z = (p) => { // inverse normal (Acklam approximation)
    const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
    const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
    const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
    const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
    const pl = 0.02425; let q, r;
    if (p < pl) { q = Math.sqrt(-2 * Math.log(p)); return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    if (p <= 1 - pl) { q = p - 0.5; r = q * q; return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1); }
    q = Math.sqrt(-2 * Math.log(1 - p)); return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  };
  const za = z(1 - alpha / 2), zb = z(power);
  const k = ratio; const pbar = (p0 + k * p1) / (1 + k);
  const n0 = Math.pow(za * Math.sqrt((1 + 1 / k) * pbar * (1 - pbar)) + zb * Math.sqrt(p0 * (1 - p0) + p1 * (1 - p1) / k), 2) / Math.pow(p1 - p0, 2);
  return { n0: Math.ceil(n0), n1: Math.ceil(n0 * k) };
}
function calcRows() {
  return HIST.filter((r) => r.endpoint === 'EASI-75').map((r) => ({ ...r, s: STUDIES.find((y) => y.id === r.study) }));
}
function calcIncluded() {
  if (!state.calc.include) state.calc.include = new Set(HIST.filter((r) => r.arm === 'placebo' && r.comparable).map((r) => r.study));
  return state.calc.include;
}
function calcPooled() {
  const inc = calcRows().filter((r) => r.arm === 'placebo' && calcIncluded().has(r.study));
  if (!inc.length) return null;
  return { pct: inc.reduce((a, r) => a + r.pct * r.n, 0) / inc.reduce((a, r) => a + r.n, 0), n: inc.length, lo: Math.min(...inc.map((x) => x.pct)), hi: Math.max(...inc.map((x) => x.pct)) };
}
function calcToggle(studyId) {
  const inc = calcIncluded(); inc.has(studyId) ? inc.delete(studyId) : inc.add(studyId);
  if (state.calc.pool) { const p = calcPooled(); if (p) state.calc.p0 = +(p.pct / 100).toFixed(3); }
  render();
}
function calcPool(on) { state.calc.pool = on; if (on) { const p = calcPooled(); if (p) state.calc.p0 = +(p.pct / 100).toFixed(3); } render(); }
/* Slider/number edits update only the outputs, so the thumb never loses the drag. */
function calcSet(k, v) {
  state.calc[k] = +v; if (k === 'p0') state.calc.pool = false;
  const fmt = CALC_FIELDS.find((f) => f[0] === k)[5];
  const lab = $('#lab-' + k); if (lab) lab.textContent = fmt(state.calc[k]);
  const num = $('#num-' + k); if (num && document.activeElement !== num) num.value = fmt(state.calc[k]).replace(/[%:1]/g, '');
  const rng = $('#rng-' + k); if (rng && document.activeElement !== rng) rng.value = state.calc[k];
  const out = $('#calc-out'); if (out) out.innerHTML = calcOutHtml();
  const pool = $('#pool-box'); if (pool) pool.checked = state.calc.pool;
  const ch = $('#hist-chart'); if (ch) ch.innerHTML = histChartHtml(); // user row / reference line tracks the sliders
}
const CALC_FIELDS = [
  ['p0', 'Placebo response at Week 16', 0.05, 0.4, 0.005, (v) => (v * 100).toFixed(1) + '%', 100],
  ['p1', 'Anticipated SRK-201 response at Week 16', 0.2, 0.9, 0.005, (v) => (v * 100).toFixed(1) + '%', 100],
  ['alpha', 'Significance level α (two-sided)', 0.01, 0.1, 0.005, (v) => v.toFixed(3), 1],
  ['power', 'Power (1 − β)', 0.7, 0.95, 0.01, (v) => (v * 100).toFixed(0) + '%', 100],
  ['ratio', 'Allocation ratio SRK-201 : placebo', 1, 3, 1, (v) => v + ':1', 1],
  ['dropout', 'Expected dropout (inflates N)', 0, 0.3, 0.01, (v) => (v * 100).toFixed(0) + '%', 100],
];
function calcOutHtml() {
  const c = state.calc;
  const r = sampleSize(c.p0, c.p1, c.alpha, c.power, c.ratio);
  const evaluable = r.n0 + r.n1, total = Math.ceil(evaluable / (1 - c.dropout));
  const grid = [1, 2, 3].map((k) => [-0.05, 0, 0.05].map((d) => { const x = sampleSize(c.p0, c.p1 + d, c.alpha, c.power, k); return Math.ceil((x.n0 + x.n1) / (1 - c.dropout)); }));
  const p = calcPooled();
  return h`<div class="headline"><div class="big">${total}</div><div class="lead">Enrol <b>${total} participants</b> (${Math.ceil(r.n1 / (1 - c.dropout))} SRK-201 : ${Math.ceil(r.n0 / (1 - c.dropout))} placebo) to have <b>${(c.power * 100).toFixed(0)}% power</b> to show SRK-201 is superior to placebo on <b>EASI-75 at Week 16</b>, if the true response rates are <b>${(c.p1 * 100).toFixed(0)}% vs ${(c.p0 * 100).toFixed(0)}%</b>, at two-sided α = ${c.alpha}, allowing ${(c.dropout * 100).toFixed(0)}% dropout.
      <div class="tiny">Placebo assumption source: ${c.pool && p ? `pooled from ${p.n} included historical records (n-weighted ${p.pct.toFixed(1)}%, range ${p.lo}–${p.hi}%)` : 'entered manually — tick "Use pooled" to derive it from the evidence on the left'}. Method: two-proportion normal approximation.</div></div></div>
    <div class="split"><div><div class="v">${evaluable}</div><div class="l">evaluable participants needed</div></div><div><div class="v">${r.n1} : ${r.n0}</div><div class="l">SRK-201 : placebo (evaluable)</div></div><div><div class="v">${((c.p1 - c.p0) * 100).toFixed(0)} pts</div><div class="l">absolute difference detected</div></div></div>
    <h5 class="muted" style="margin:6px 0 4px;font-size:11px;text-transform:uppercase;letter-spacing:.06em">What if my assumptions are off? — total N to enrol</h5>
    <div class="howto"><b>How to read:</b> rows change the allocation ratio; columns assume the true SRK-201 response is 5 points lower or higher than you entered. The <b>outlined cell</b> is your current inputs; darker cells need more participants. A small effect (left column) is what drives N up.</div>
    <table class="heat"><thead><tr><th>allocation ↓ / true effect →</th><th>SRK-201 ${((c.p1 - 0.05) * 100).toFixed(0)}% (worse)</th><th>SRK-201 ${(c.p1 * 100).toFixed(0)}% (as entered)</th><th>SRK-201 ${((c.p1 + 0.05) * 100).toFixed(0)}% (better)</th></tr></thead><tbody>${grid.map((row, i) => h`<tr><th>${i + 1}:1</th>${row.map((v, j) => h`<td class="${v > total * 1.3 ? 'h4' : v > total * 1.1 ? 'h3' : v > total * 0.9 ? 'h2' : 'h1'} ${i + 1 === c.ratio && j === 1 ? 'sel' : ''}">${v}</td>`).join('')}</tr>`).join('')}</tbody></table>
    <div class="tiny muted" style="margin-top:8px">Not modelled here (stated, never silently assumed): interim analyses, multiplicity across endpoints, Bayesian decision rules, precision-based sizing.</div>`;
}
/* ---------- Historical chart (SVG) ----------
   Encodings follow the data-analysis recommendation (docs/07_chart_recommendation.md):
   default = dumbbell (placebo → active per trial, user row pinned on top, pooled-placebo band,
   Δ + 95% CI on the connector); secondary = Δ forest and placebo lollipop. Ordering: user row,
   comparable trials with Δ (Δ desc), comparable placebo-only, divider, excluded. Marker AREA ∝ n. */
const Z95 = 1.959964;
function wilsonCi(pct, n) {
  const p = pct / 100, z2 = Z95 * Z95, den = 1 + z2 / n;
  const c = (p + z2 / (2 * n)) / den, half = Z95 * Math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / den;
  return [100 * (c - half), 100 * (c + half)];
}
function newcombeCi(p1, n1, p2, n2) { // active − placebo, percentage points
  const [l1, u1] = wilsonCi(p1, n1), [l2, u2] = wilsonCi(p2, n2), d = p1 - p2;
  return [d - Math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + Math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)];
}
const markR = (n) => 0.7 * Math.sqrt(30 + 0.55 * n); // radius in px so that area ∝ n
const fmtPts = (v) => (v >= 0 ? '+' : '') + v.toFixed(1);
/* One row per trial, tagged with inclusion (from the user's ticks) and sorted per the ordering rules. */
function histTrials() {
  const inc = calcIncluded(), by = {};
  calcRows().forEach((r) => { const g = (by[r.study] = by[r.study] || { s: r.s, tp: r.tp, study: r.study }); g[r.arm === 'placebo' ? 'pbo' : 'act'] = r; });
  const trials = Object.values(by).filter((g) => g.pbo).map((g) => {
    const t = { ...g, included: inc.has(g.study), why: g.pbo.why, pboCi: wilsonCi(g.pbo.pct, g.pbo.n) };
    if (g.act) { t.delta = g.act.pct - g.pbo.pct; t.deltaCi = newcombeCi(g.act.pct, g.act.n, g.pbo.pct, g.pbo.n); t.actCi = wilsonCi(g.act.pct, g.act.n); }
    return t;
  });
  const key = (t) => (t.act ? [0, -t.delta] : [1, -t.pbo.pct]);
  const cmp = (a, b) => { const ka = key(a), kb = key(b); return ka[0] - kb[0] || ka[1] - kb[1]; };
  return { included: trials.filter((t) => t.included).sort(cmp), excluded: trials.filter((t) => !t.included).sort(cmp) };
}
function histChartHtml() {
  const view = state.calc.view || 'study';
  const { included, excluded } = histTrials();
  const pooled = calcPooled();
  const pooledCi = pooled ? wilsonCi(pooled.pct, calcRows().filter((r) => r.arm === 'placebo' && calcIncluded().has(r.study)).reduce((a, r) => a + r.n, 0)) : null;
  const uP0 = state.calc.p0 * 100, uP1 = state.calc.p1 * 100, uD = uP1 - uP0;
  // Geometry (viewBox units; the SVG scales to the panel width)
  const W = 960, L = 290, ROW = 48, TOP = 36, GAP = 24;
  const R = view === 'study' ? 905 : 660; // forest + placebo views keep a numeric column right of the plot
  // x-domain per view: % scale for dumbbell, Δ pts for the forest, zoomed % scale for placebo (rates cluster at 10–25 %)
  const dom = view === 'delta' ? [-10, 80] : view === 'placebo' ? [0, 50] : [0, 100];
  const x = (v) => L + (v - dom[0]) / (dom[1] - dom[0]) * (R - L);
  const ys = []; let y = TOP + ROW / 2;
  ys.push(['user', y]); y += ROW * 1.2;
  included.forEach((t) => { ys.push([t, y]); y += ROW; });
  let divY = null; if (excluded.length) { divY = y - ROW / 2 + GAP / 2; y += GAP; excluded.forEach((t) => { ys.push([t, y]); y += ROW; }); }
  const H = y + 40;
  const C = { pbo: '#9CA3AF', pboText: '#374151', act: 'var(--accent-700)', jak: 'var(--prov-inherited)', user: 'var(--prov-proposed)', band: 'var(--accent-100)', exText: 'var(--state-incomplete)', sep: 'var(--slate-300)' };
  const label = (t, yy) => h`<text x="${L - 14}" y="${yy - 4}" text-anchor="end" class="hl-name" opacity="${t.included ? 1 : 0.6}">${esc(t.s.name.replace(/ \(.*\)/, ''))}</text>
    <text x="${L - 14}" y="${yy + 10}" text-anchor="end" class="hl-sub">${esc((t.act ? t.act.arm.replace(/^\S+\s/, '') + ' · ' : '') + t.s.moa + ' · Phase ' + t.s.phase + ' · ' + t.tp)}</text>
    ${!t.included && t.why ? h`<text x="${L - 14}" y="${yy + 23}" text-anchor="end" class="hl-ex">excluded: ${esc(t.why)}</text>` : t.included && t.why ? h`<text x="${L - 14}" y="${yy + 23}" text-anchor="end" class="hl-warn">included despite: ${esc(t.why)}</text>` : ''}
    <text x="${915}" y="${yy + 4}" class="hl-page" onclick="toast('Open ${esc(t.s.name)} p. ${t.pbo.page} (mock)')">p.${t.pbo.page}</text>`;
  const marker = (cx, cy, r, fill, { jak, open, faded } = {}) => jak
    ? h`<polygon points="${cx},${cy - r} ${cx + r},${cy} ${cx},${cy + r} ${cx - r},${cy}" fill="${open ? '#fff' : fill}" stroke="${fill}" stroke-width="2" opacity="${faded ? 0.45 : 1}"/>`
    : h`<circle cx="${cx}" cy="${cy}" r="${r}" fill="${open ? '#fff' : fill}" stroke="${open ? fill : '#fff'}" stroke-width="${open ? 2 : 1.5}" opacity="${faded ? 0.45 : 1}"/>`;
  const axis = (ticks, unit, title) => h`<line x1="${L}" x2="${R}" y1="${H - 34}" y2="${H - 34}" stroke="${C.sep}"/>
    ${ticks.map((v) => h`<line x1="${x(v)}" x2="${x(v)}" y1="${H - 34}" y2="${H - 30}" stroke="${C.sep}"/><text x="${x(v)}" y="${H - 18}" text-anchor="middle" class="hl-tick">${v}${unit}</text>`).join('')}
    <text x="${(L + R) / 2}" y="${H - 3}" text-anchor="middle" class="hl-axis">${title}</text>`;
  const grid = (ticks) => ticks.map((v) => h`<line x1="${x(v)}" x2="${x(v)}" y1="${TOP - 6}" y2="${H - 34}" stroke="var(--slate-100)"/>`).join('');
  const divider = divY === null ? '' : h`<line x1="${L}" x2="${R}" y1="${divY}" y2="${divY}" stroke="${C.sep}" stroke-dasharray="3 3"/><text x="${L}" y="${divY - 5}" class="hl-ex" font-weight="600">EXCLUDED FROM POOLING — shown for context, not equivalent</text>`;
  let body = '';
  /* --- Default: dumbbell --- */
  if (view === 'study') {
    const band = pooled ? h`<rect x="${x(pooled.lo)}" y="${TOP - 6}" width="${Math.max(2, x(pooled.hi) - x(pooled.lo))}" height="${H - 28 - TOP}" fill="${C.band}" opacity=".7"/><line x1="${x(pooled.pct)}" x2="${x(pooled.pct)}" y1="${TOP - 6}" y2="${H - 34}" stroke="${C.act}" stroke-dasharray="2 3"/>
      <text x="${x(pooled.pct)}" y="${TOP - 12}" text-anchor="middle" class="hl-pooled">pooled placebo ${pooled.pct.toFixed(1)}% · ${pooled.n} included arm${pooled.n === 1 ? '' : 's'}, range ${pooled.lo}–${pooled.hi}%</text>` : '';
    const row = (t, yy) => {
      const a = t.included ? 1 : 0.45, col = t.act && t.act.jak ? C.jak : C.act;
      return h`${label(t, yy)}
        <line x1="${x(t.pboCi[0])}" x2="${x(t.pboCi[1])}" y1="${yy}" y2="${yy}" stroke="${C.pbo}" stroke-width="1.2" opacity="${a * 0.8}"/>
        ${t.act ? h`<line x1="${x(t.pbo.pct)}" x2="${x(t.act.pct)}" y1="${yy}" y2="${yy}" stroke="${col}" stroke-width="2.6" opacity="${a}" ${t.included ? '' : 'stroke-dasharray="6 4"'}/>
          <text x="${x((t.pbo.pct + t.act.pct) / 2)}" y="${yy - 9}" text-anchor="middle" class="hl-delta" opacity="${a}" font-weight="${t.included ? 600 : 400}">Δ ${fmtPts(t.delta)} pts  (95% CI ${fmtPts(t.deltaCi[0])} to ${fmtPts(t.deltaCi[1])})</text>
          ${marker(x(t.act.pct), yy, markR(t.act.n), col, { jak: t.act.jak, faded: !t.included })}
          <text x="${x(t.act.pct) + markR(t.act.n) + 5}" y="${yy + 4}" class="hl-val" fill="${col}" opacity="${a}">${t.act.pct.toFixed(1)}%  n=${t.act.n}</text>`
        : h`<text x="${x(t.pboCi[1]) + 8}" y="${yy + 4}" class="hl-note" opacity="${a}">active arm not yet extracted</text>`}
        ${marker(x(t.pbo.pct), yy, markR(t.pbo.n), C.pbo, { faded: !t.included })}
        ${t.pbo.pct < 13 && !t.act ? h`<text x="${x(t.pbo.pct)}" y="${yy - 12}" text-anchor="middle" class="hl-val" fill="${C.pboText}" opacity="${a}">${t.pbo.pct.toFixed(1)}%  n=${t.pbo.n}</text>` : h`<text x="${x(t.pbo.pct) - markR(t.pbo.n) - 5}" y="${yy + 4}" text-anchor="end" class="hl-val" fill="${C.pboText}" opacity="${a}">${t.pbo.pct.toFixed(1)}%  n=${t.pbo.n}</text>`}`;
    };
    const user = (yy) => h`<text x="${L - 14}" y="${yy - 4}" text-anchor="end" class="hl-name" fill="${C.user}">Your assumption · SRK-201</text><text x="${L - 14}" y="${yy + 10}" text-anchor="end" class="hl-sub" fill="${C.user}">placebo ${uP0.toFixed(1)}% → active ${uP1.toFixed(1)}%</text>
      <line x1="${x(uP0)}" x2="${x(uP1)}" y1="${yy}" y2="${yy}" stroke="${C.user}" stroke-width="2.6"/>
      <text x="${x((uP0 + uP1) / 2)}" y="${yy - 9}" text-anchor="middle" class="hl-delta" fill="${C.user}" font-weight="600">Δ ${fmtPts(uD)} pts</text>
      ${marker(x(uP0), yy, 7, C.user, { open: true })}${marker(x(uP1), yy, 7, C.user)}
      <text x="${x(uP0) - 12}" y="${yy + 4}" text-anchor="end" class="hl-val" fill="${C.user}" font-weight="600">${uP0.toFixed(1)}%</text><text x="${x(uP1) + 12}" y="${yy + 4}" class="hl-val" fill="${C.user}" font-weight="600">${uP1.toFixed(1)}%</text>`;
    body = grid([20, 40, 60, 80]) + band + ys.map(([t, yy]) => (t === 'user' ? user(yy) : row(t, yy))).join('') + divider + axis([0, 20, 40, 60, 80, 100], '%', 'Participants reaching EASI-75 (%) — grey dot = placebo arm, coloured dot = active arm, dot area ∝ arm size n');
  }
  /* --- Secondary: Δ forest --- */
  if (view === 'delta') {
    const row = (t, yy) => {
      const a = t.included ? 1 : 0.45, col = t.act && t.act.jak ? C.jak : C.act;
      return h`${label(t, yy)}${t.act ? h`
        <line x1="${x(t.deltaCi[0])}" x2="${x(t.deltaCi[1])}" y1="${yy}" y2="${yy}" stroke="${col}" stroke-width="2" opacity="${a}" ${t.included ? '' : 'stroke-dasharray="6 4"'}/>
        ${marker(x(t.delta), yy, markR(t.act.n + t.pbo.n), col, { jak: t.act.jak, faded: !t.included })}
        <text x="${R + 14}" y="${yy - 2}" class="hl-val" fill="${col}" opacity="${a}" font-weight="600">Δ ${fmtPts(t.delta)} pts  (${fmtPts(t.deltaCi[0])} to ${fmtPts(t.deltaCi[1])})</text><text x="${R + 14}" y="${yy + 12}" class="hl-val" fill="${C.pboText}" opacity="${a}">${t.act.pct}% (n=${t.act.n}) vs ${t.pbo.pct}% (n=${t.pbo.n})</text>`
        : h`<text x="${x(0) + 8}" y="${yy + 4}" class="hl-note" opacity="${a}">no Δ (active arm not extracted) — see Placebo only</text>`}`;
    };
    const user = (yy) => h`<text x="${L - 14}" y="${yy - 4}" text-anchor="end" class="hl-name" fill="${C.user}">Your assumption · SRK-201</text><text x="${L - 14}" y="${yy + 10}" text-anchor="end" class="hl-sub" fill="${C.user}">Δ ${fmtPts(uD)} pts (${uP1.toFixed(0)}% vs ${uP0.toFixed(0)}%)</text>
      <line x1="${x(uD)}" x2="${x(uD)}" y1="${TOP - 6}" y2="${H - 34}" stroke="${C.user}" stroke-dasharray="5 4" stroke-width="1.5"/>
      ${marker(x(uD), yy, 7, C.user)}<text x="${R + 14}" y="${yy + 4}" class="hl-val" fill="${C.user}" font-weight="600">Δ ${fmtPts(uD)} pts  (your entry)</text>
      <text x="${R + 14}" y="${TOP - 12}" class="hl-tick">Δ (95% CI) · active vs placebo</text>`;
    body = grid([0, 20, 40, 60]) + h`<line x1="${x(0)}" x2="${x(0)}" y1="${TOP - 6}" y2="${H - 34}" stroke="${C.sep}"/>` + ys.map(([t, yy]) => (t === 'user' ? user(yy) : row(t, yy))).join('') + divider + axis([-10, 0, 20, 40, 60, 80], '', 'Treatment effect: active − placebo (percentage points), 95% CI (Newcombe); marker area ∝ total n');
  }
  /* --- Secondary: placebo lollipop with pooled band --- */
  if (view === 'placebo') {
    const srt = (arr) => [...arr].sort((a, b) => b.pbo.pct - a.pbo.pct);
    const ys2 = []; let yy = TOP + ROW / 2; ys2.push(['user', yy]); yy += ROW * 1.2;
    srt(included).forEach((t) => { ys2.push([t, yy]); yy += ROW; });
    let dv = null; if (excluded.length) { dv = yy - ROW / 2 + GAP / 2; yy += GAP; srt(excluded).forEach((t) => { ys2.push([t, yy]); yy += ROW; }); }
    const band = pooled ? h`<rect x="${x(pooled.lo)}" y="${TOP - 6}" width="${Math.max(2, x(pooled.hi) - x(pooled.lo))}" height="${H - 28 - TOP}" fill="${C.band}" opacity=".5"/>
      <rect x="${x(pooledCi[0])}" y="${TOP - 6}" width="${x(pooledCi[1]) - x(pooledCi[0])}" height="${H - 28 - TOP}" fill="${C.act}" opacity=".12"/>
      <line x1="${x(pooled.pct)}" x2="${x(pooled.pct)}" y1="${TOP - 6}" y2="${H - 34}" stroke="${C.act}" stroke-dasharray="2 3"/>
      <text x="${x(pooled.pct)}" y="${TOP - 12}" text-anchor="middle" class="hl-pooled">pooled ${pooled.pct.toFixed(1)}% (95% CI ${pooledCi[0].toFixed(1)}–${pooledCi[1].toFixed(1)}) · light band = observed range ${pooled.lo}–${pooled.hi}%</text>` : h`<text x="${L}" y="${TOP - 12}" class="hl-ex">No placebo arms ticked — nothing to pool.</text>`;
    const row = (t, y0) => { const a = t.included ? 1 : 0.45; return h`${label(t, y0)}
      <line x1="${x(0)}" x2="${x(t.pbo.pct)}" y1="${y0}" y2="${y0}" stroke="${C.pbo}" stroke-width="1" opacity="${a * 0.5}" ${t.included ? '' : 'stroke-dasharray="4 3"'}/>
      <line x1="${x(t.pboCi[0])}" x2="${x(t.pboCi[1])}" y1="${y0}" y2="${y0}" stroke="${C.pboText}" stroke-width="2" opacity="${a}"/>
      ${marker(x(t.pbo.pct), y0, markR(t.pbo.n), C.pbo, { faded: !t.included })}
      <text x="${R + 14}" y="${y0 - 2}" class="hl-val" fill="${C.pboText}" opacity="${a}" font-weight="600">${t.pbo.pct.toFixed(1)}%  (95% CI ${t.pboCi[0].toFixed(1)}–${t.pboCi[1].toFixed(1)})</text><text x="${R + 14}" y="${y0 + 12}" class="hl-val" fill="${C.pboText}" opacity="${a}">n=${t.pbo.n} placebo</text>`; };
    const user = (y0) => h`<text x="${L - 14}" y="${y0 - 4}" text-anchor="end" class="hl-name" fill="${C.user}">Your placebo assumption</text><text x="${L - 14}" y="${y0 + 10}" text-anchor="end" class="hl-sub" fill="${C.user}">${state.calc.pool ? 'derived from pooled evidence' : 'entered manually'}</text>
      <line x1="${x(uP0)}" x2="${x(uP0)}" y1="${TOP - 6}" y2="${H - 34}" stroke="${C.user}" stroke-dasharray="5 4" stroke-width="1.5"/>
      ${marker(x(uP0), y0, 7, C.user, { open: true })}<text x="${R + 14}" y="${y0 + 4}" class="hl-val" fill="${C.user}" font-weight="600">${uP0.toFixed(1)}%${pooled && (uP0 < pooled.lo || uP0 > pooled.hi) ? ' — outside observed range' : ''}</text>
      <text x="${R + 14}" y="${TOP - 12}" class="hl-tick">placebo % (Wilson 95% CI)</text>`;
    const div2 = dv === null ? '' : h`<line x1="${L}" x2="${R}" y1="${dv}" y2="${dv}" stroke="${C.sep}" stroke-dasharray="3 3"/><text x="${L}" y="${dv - 5}" class="hl-ex" font-weight="600">EXCLUDED FROM POOLING — shown for context, not equivalent</text>`;
    body = grid([10, 20, 30, 40]) + band + ys2.map(([t, y0]) => (t === 'user' ? user(y0) : row(t, y0))).join('') + div2 + axis([0, 10, 20, 30, 40, 50], '%', 'Placebo participants reaching EASI-75 (%) with Wilson 95% CI; dot area ∝ arm size n');
  }
  const legend = h`<div class="legend"><span><i style="background:#9CA3AF;border-radius:50%"></i>placebo arm</span><span><i style="background:var(--accent-700);border-radius:50%"></i>active arm</span><span><i style="background:var(--prov-inherited);transform:rotate(45deg);border-radius:1px"></i>active arm, JAK-like profile</span><span><i style="border:2px solid var(--prov-proposed);border-radius:50%;background:#fff"></i>your assumption</span><span><i style="background:var(--accent-100)"></i>pooled placebo range</span><span style="opacity:.55">faded + dashed = excluded from pooling</span><span class="mono">p.# = source page (click to open)</span></div>`;
  return h`<svg class="hsvg" viewBox="0 0 ${W} ${H}" width="100%" style="display:block;height:auto;font-family:var(--ui)">${body}</svg>${legend}`;
}
function calculatorView() {
  const c = state.calc; calcIncluded();
  const comp = calcRows().filter((r) => r.arm === 'placebo');
  const p = calcPooled();
  const inp = ([k, label, min, max, step, fmt, scale]) => h`<div class="field"><label>${label} <span class="mono" id="lab-${k}" style="color:var(--accent-700);font-weight:600">${fmt(c[k])}</span></label>
    <div class="slider"><input type="range" id="rng-${k}" min="${min}" max="${max}" step="${step}" value="${c[k]}" oninput="calcSet('${k}',this.value)"><input type="number" id="num-${k}" step="${step * scale}" min="${min * scale}" max="${max * scale}" value="${+(c[k] * scale).toFixed(3)}" onchange="calcSet('${k}',this.value/${scale})"></div></div>`;
  const body = h`<div class="page"><h1>Trial calculator — sample size for superiority</h1><div class="sub">Pick the endpoint, ground the placebo assumption in reviewed historical evidence, set design assumptions → read the headline number on the right, then check how fragile it is.</div>
  <div class="calc"><div class="panel"><h3><span class="step">1</span>Endpoint</h3><div class="body">
    <div class="field"><label>Endpoint · timepoint</label><div class="row"><select><option>EASI-75 (responder, binary)</option><option>EASI-90</option><option>EASI change from baseline (continuous)</option><option>PP-NRS ≥4-point improvement</option></select><select><option>Week 16</option><option>Week 12</option></select></div></div></div>
    <h3><span class="step">2</span>Placebo assumption from evidence</h3><div class="body">
    <div class="tiny muted" style="margin-bottom:6px">Tick the historical placebo arms you consider comparable. Greyed rows failed the comparability filter (timepoint, background therapy, unreviewed OCR) — you may still include them deliberately.</div>
      <div class="tiny">${comp.map((x) => { const on = calcIncluded().has(x.study); return h`<div style="display:grid;grid-template-columns:18px 1fr auto auto;gap:2px 6px;align-items:center;padding:5px 0;border-bottom:1px dashed var(--slate-200);${x.comparable ? '' : 'color:var(--slate-600)'}"><input type="checkbox" ${on ? 'checked' : ''} onchange="calcToggle('${x.study}')" style="width:16px;height:16px;cursor:pointer"><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(x.s.name)}">${esc(x.s.name)} <span class="muted">${x.tp}</span></span><span class="mono" style="font-weight:600">${x.pct}%</span>${chip('source', 'p.' + x.page)}${x.why ? h`<span></span><span style="grid-column:2/5">${chip(on ? 'warning' : 'na', (on ? 'included despite: ' : 'not comparable: ') + x.why)}</span>` : ''}</div>`; }).join('')}</div>
      <div class="tiny" style="margin-top:8px;display:flex;gap:8px;align-items:center"><input type="checkbox" id="pool-box" ${c.pool ? 'checked' : ''} onchange="calcPool(this.checked)" style="width:16px;height:16px;cursor:pointer"><label for="pool-box"><b>Use pooled placebo rate</b> ${p ? `→ ${p.pct.toFixed(1)}% (n-weighted, ${p.n} record${p.n === 1 ? '' : 's'}; range ${p.lo}–${p.hi}%)` : '— no records included'}</label></div></div>
    <h3><span class="step">3</span>Design assumptions</h3><div class="body">${CALC_FIELDS.map(inp).join('')}</div></div>
  <div><div class="panel" style="margin-bottom:16px"><h3>Sample size — what you need to enrol <span class="grow"></span><button class="btn sm" onclick="toast('Saved to W-102 §10.11 as author-supplied sample_size with assumptions + evidence links (mock)')">Save to protocol §10.11</button></h3><div class="body" id="calc-out">${calcOutHtml()}</div></div>
  <div class="panel"><h3>Historical EASI-75 response — what other trials saw <span class="grow"></span><span class="seg">${[['study', 'By study'], ['delta', 'Treatment effect'], ['placebo', 'Placebo only']].map(([k, l]) => h`<a class="${(c.view || 'study') === k ? 'active' : ''}" onclick="state.calc.view='${k}';render()">${l}</a>`).join('')}</span></h3><div class="body">
    <div class="howto"><b>How to read:</b> ${{ study: 'one row per trial, grey dot = placebo arm → coloured dot = active arm; the connector length is Δ, the treatment effect (with 95% CI). Your assumption is the amber row on top, drawn the same way — compare its connector to the rows beneath. The teal band is the range of the placebo arms you ticked; dot area ∝ arm size. Faded, dashed rows below the divider are excluded from pooling.', delta: 'one row per trial = active minus placebo, in percentage points, with its 95% CI (Newcombe) as the whisker; marker area ∝ total n. The dashed amber line is the Δ you entered — if it sits inside a comparable trial\u2019s CI it is historically plausible; far to the right of every CI means optimistic.', placebo: 'placebo arms only, sorted high to low, each with its Wilson 95% CI. The pooled estimate (dotted line) and its CI (darker band) come only from the arms you ticked; the light band is their observed range. Your placebo assumption is the dashed amber line — a wide range here means it is fragile.' }[c.view || 'study']} Click <span class="mono">p.#</span> to open the source page a value was extracted from.</div>
    <div id="hist-chart">${histChartHtml()}</div>
    <div class="toolbar" style="margin-top:12px"><button class="btn" onclick="toast('Endpoint explorer (exploratory): profile JAK-like → endpoint × timepoint N alongside regulatory precedent + relevance (Pilot 4b)')">Open endpoint explorer (exploratory)</button><span class="tiny muted">Profile: <b>JAK-like</b> (saved object · 2 records · editable)</span></div>
  </div></div></div></div></div>`;
  return frame('calc', h`<b>Trial calculator</b><span class="sep">·</span><span class="muted">SRK-201 · EASI-75 · Week 16</span>`, body);
}

/* ---------- Admin ---------- */
function adminView(tab) {
  const tabs = ['users', 'works', 'usage', 'models', 'audit'];
  const nav = h`<div class="tabs">${tabs.map((t) => h`<a href="#/admin/${t}" class="${tab === t ? 'active' : ''}">${{ users: 'Users & access', works: 'Works & permissions', usage: 'Usage', models: 'Models & providers', audit: 'Audit log' }[t]}</a>`).join('')}</div>`;
  let body = '';
  if (tab === 'users') body = h`<div class="toolbar"><button class="btn primary" onclick="toast('Add user by email; role author/statistician/reviewer/admin (mock)')">Add user</button><button class="btn" onclick="toast('Domain rule @sarika.com → author (mock)')">Domain rule</button><div class="grow"></div>${chip('warning', '1 pending request: jon.smith@gmail.com')}</div>
    <div class="panel"><table class="grid"><thead><tr><th>User</th><th>Email</th><th>Role</th><th>Last active</th><th class="num">Works</th><th></th></tr></thead><tbody>${USERS.map((u) => h`<tr><td><b>${u.name}</b></td><td class="mono">${u.email}</td><td>${chip(u.role === 'admin' ? 'accent' : '', u.role)}</td><td>${u.last}</td><td class="num">${u.works}</td><td><button class="btn sm ghost">Edit</button><button class="btn sm ghost danger">Revoke</button></td></tr>`).join('')}</tbody></table></div>`;
  if (tab === 'works') body = h`<div class="panel"><table class="grid matrix"><thead><tr><th>Work</th>${USERS.map((u) => h`<th>${u.name.split(' ')[0]}</th>`).join('')}<th>Data class</th></tr></thead><tbody>${WORKS.map((w, i) => h`<tr><td><b>${esc(w.title)}</b></td>${USERS.map((u, j) => { const lv = [['owner', 'edit', 'edit', 'comment'], ['edit', 'owner', '—', 'view'], ['owner', 'view', 'edit', '—']][i][j]; return h`<td><span class="lvl ${lv}">${lv}</span></td>`; }).join('')}<td>${chip('', 'confidential')}</td></tr>`).join('')}</tbody></table></div>`;
  if (tab === 'usage') body = h`<div class="kpis"><div class="kpi"><div class="v">4</div><div class="l">active users (7 d)</div></div><div class="kpi"><div class="v">1,284</div><div class="l">edits (7 d)</div></div><div class="kpi"><div class="v">2.1M</div><div class="l">LLM tokens (7 d)</div></div><div class="kpi"><div class="v">$38.20</div><div class="l">LLM cost (7 d)</div></div></div>
    <div class="cards"><div class="card"><h4>Edits per day</h4><div class="bars">${[40, 65, 30, 80, 95, 20, 70].map((v) => h`<i style="height:${v}%"></i>`).join('')}</div></div><div class="card"><h4>LLM cost by provider</h4><table class="grid"><tr><td>OpenAI · gpt-6-astra</td><td class="num">$35.90</td></tr><tr><td>xAI · grok-4</td><td class="num">$2.30</td></tr></table></div><div class="card"><h4>LLM cost by task</h4><table class="grid"><tr><td>adapt</td><td class="num">$19.10</td></tr><tr><td>claims</td><td class="num">$8.40</td></tr><tr><td>ask</td><td class="num">$6.20</td></tr><tr><td>group / review</td><td class="num">$4.50</td></tr></table></div></div>`;
  if (tab === 'models') body = h`<div class="toolbar"><button class="btn primary" onclick="toast('Add provider: vendor · label · base URL (allow-listed) · API key (encrypted, shown once) → Test connection runs capability probes (mock)')">Add provider</button><div class="grow"></div><span class="tiny muted">Keys encrypted at rest (KMS); never returned to the browser. Providers start with no approved data classes.</span></div>
    ${PROVIDERS.map((p) => h`<div class="panel" style="margin-bottom:12px"><h3>${esc(p.label)} <span class="chip">${p.vendor}</span>${p.seeded ? chip('inherited', 'seeded from OPENAI_API_KEY') : ''}<span class="grow"></span><span class="tiny muted">key <span class="key">${p.key}</span></span><button class="btn sm" onclick="toast('Test connection: auth ✓ · models listed ✓ · structured output ✓ · streaming ✓ (mock)')">Test connection</button><button class="btn sm ghost">Rotate key</button><span class="switch ${p.enabled ? 'on' : ''}" onclick="toast('Toggled (mock)')"></span></h3>
      <div class="body"><dl class="kv"><dt>Base URL</dt><dd class="mono">${p.base}</dd><dt>Approved data classes</dt><dd>${['public', 'confidential', 'restricted'].map((cl) => h`<label style="margin-right:12px"><input type="checkbox" ${p.classes.includes(cl) ? 'checked' : ''} onchange="toast('Data class approval recorded in audit log (mock)')"> ${cl}</label>`).join('')}${p.classes.length === 0 ? chip('warning', 'fail-closed: receives nothing') : ''}</dd></dl>
      ${p.models.length ? h`<table class="grid" style="margin-top:10px"><thead><tr><th>Model</th><th>Capabilities (probed)</th><th>Enabled</th><th>Default for tasks</th><th></th></tr></thead><tbody>${p.models.map((m) => h`<tr><td class="mono">${m.id}</td><td>${m.caps.map((x) => chip(x.endsWith('?') ? 'warning' : 'mono', x)).join(' ')}</td><td><span class="switch ${m.enabled ? 'on' : ''}"></span></td><td>${m.defaults.map((x) => chip('accent', x)).join(' ') || '<span class="muted tiny">—</span>'}</td><td><button class="btn sm ghost" onclick="toast('Routing: pick tasks this model is default/fallback for; structured tasks require the structured capability (mock)')">Routing…</button></td></tr>`).join('')}</tbody></table>` : '<div class="empty tiny">No API key yet — add a key and run Test connection to list models.</div>'}</div></div>`).join('')}`;
  if (tab === 'audit') body = h`<div class="panel"><table class="grid"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead><tbody>${[['22:11', 'MK', 'edit_narrative', 'W-102 B-3-4', 'rev 42 · claim mismatch created'], ['21:57', 'BA', 'set_field', 'W-102 EP-02.time_reference', 'W12 → W16 · rev 41 · R22 impact 3 blocks'], ['21:40', 'pipeline', 'llm_call', 'ask · gpt-6-astra', '612 tok · $0.012 · data class confidential · approved'], ['20:02', 'BA', 'provider.approve_class', 'P-1 OpenAI', 'confidential'], ['19:48', 'BA', 'user.add', 'priya@sarika.com', 'role reviewer'], ['yesterday', 'system', 'llm_call.denied', 'ask · grok-4', 'provider not approved for confidential']].map((r) => h`<tr><td class="mono">${r[0]}</td><td>${r[1]}</td><td class="mono">${r[2]}</td><td class="mono">${r[3]}</td><td class="tiny">${r[4]}</td></tr>`).join('')}</tbody></table></div>`;
  return frame('admin', h`<b>Admin</b>`, h`<div class="page"><h1>Administration</h1>${nav}${body}</div>`);
}

/* ---------- Router ---------- */
function render() {
  const r = state.route;
  const root = $('#root');
  let html;
  if (r.startsWith('/login')) html = loginView(r.endsWith('denied'));
  else if (r.startsWith('/library/studies')) html = libraryView('studies');
  else if (r.startsWith('/library/master')) html = libraryView('master');
  else if (r.startsWith('/library/templates')) html = libraryView('templates');
  else if (r.startsWith('/library')) html = libraryView('works');
  else if (r.startsWith('/new')) html = wizardView(+(r.split('/')[2] || 1));
  else if (r.startsWith('/editor')) html = editorView(r.split('/')[2]);
  else if (r.startsWith('/calculator')) html = calculatorView();
  else if (r.startsWith('/admin')) html = adminView(r.split('/')[2] || 'users');
  else html = loginView(false);
  root.innerHTML = html + (state.hideNote ? '' : h`<div class="mocknote"><b>Phase-0 mock</b> · illustrative data · login → workspace → new-from-starter → editor (Inspect / Findings / Ask / Compare) → calculator → admin<a onclick="state.hideNote=true;render()">✕</a></div>`);
}
render();
