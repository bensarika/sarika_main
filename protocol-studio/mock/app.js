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
function rail(active) {
  const item = (k, path, title) => h`<a href="#${path}" class="${active === k ? 'active' : ''}" title="${title}">${ICONS[k]}</a>`;
  return h`<nav class="rail"><div class="logo">P</div>
    ${item('works', '/library', 'Workspace')}
    ${item('library', '/library/studies', 'Library')}
    ${item('calc', '/calculator', 'Trial calculator')}
    ${item('admin', '/admin/users', 'Admin')}
    <div class="spacer"></div><div class="avatar" title="Ben Altman · admin">BA</div></nav>`;
}
function topbar(crumbs, right = '') {
  return h`<header class="topbar"><div class="crumbs">${crumbs}</div><div class="grow"></div>${right}</header>`;
}
function frame(active, crumbs, body, right = '') {
  return h`<div class="app">${rail(active)}${topbar(crumbs, right)}<main class="main">${body}</main></div>`;
}
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
  return h`<div class="app">${rail('works')}${topbar(h`<a href="#/library">Workspace</a><span class="sep">/</span><b>New protocol from starter</b>`)}<main class="main"><div class="wizard">${side}<div class="wbody">${body}</div></div></main></div>`;
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
  const outline = h`<aside class="outline"><div class="hdr">Outline · ICH M11</div>
    ${OUTLINE.map((s) => h`<div class="sec ${s.n === state.section ? 'active' : ''} ${s.n === 0 ? 'section0' : ''}" onclick="selectSection(${s.n})" title="${s.m11}"><span class="n">${s.n}</span><span class="t">${esc(s.title)}</span><span class="pct">${s.pct}%${dots(s)}</span></div>`).join('')}
    <div class="foot"><div class="tiny muted" style="margin-bottom:4px">Overall</div>${progress(w.pct, h`<a href="#" onclick="setTab('findings');return false">what's left</a>`)}<div class="tiny muted" style="margin-top:6px">Design-ready ✓ · Operationally specified ✗ (R04, R11) · Formal review ✗</div></div></aside>`;

  const canvas = state.section === 3 ? BLOCKS_S3.map(blockHtml).join('') : h`<h2>${esc(sec.m11)}</h2><div class="gen-note">Mock: only Section 3 is populated in this clickable mock. Other sections show the same block model.</div>${state.section === 8 ? soaHtml() : h`<div class="block author"><span class="ph">Section ${sec.n} content …</span></div>`}`;
  const canvasWrap = h`<section class="canvas-wrap"><article class="canvas"><h1>${esc(sec.m11)} <span class="heading-tag">Section ${sec.n} · ${sec.pct}% · ${sec.err} blocking</span></h1>${canvas}</article></section>`;

  return h`<div class="app">${rail('works')}${topbar(h`<a href="#/library">Workspace</a><span class="sep">/</span><b>${esc(w.title)}</b><span class="sep">·</span><span class="mono">${w.version} · rev 42</span>`,
    h`<span class="save-status"><i></i>Saved 8 s ago</span><div class="presence"><span style="background:#3A4B5E">BA</span><span style="background:#6E4BC4">MK</span></div><button class="btn sm" onclick="toast('History: autosave snapshots + versions (mock)')">History</button><button class="btn sm" onclick="toast('Create version: semantic diff vs v0.2 shown; readiness predicate lists failing clauses (mock)')">Create version</button><button class="btn sm primary" onclick="toast('Export → PDF (LaTeX/Tectonic) · DOCX; job queued (mock)')">Export</button>`)}
    <main class="main"><div class="editor">${outline}${canvasWrap}${inspector()}</div></main></div>`;
}
function blockHtml(b) {
  if (b.kind === 'h2') return h`<h2>${b.text}</h2>`;
  const sel = b.id === state.block ? 'selected' : '';
  return h`<div class="block ${b.prov} ${sel} ${b.gen ? 'generated' : ''}" onclick="selectBlock('${b.id}')">${b.text}
    <span class="bmenu"><button class="btn sm ghost" onclick="event.stopPropagation();askAbout('${b.id}')">Ask</button><button class="btn sm ghost" onclick="event.stopPropagation();toast('Comment thread (mock)')">Comment</button></span>
    <span class="btags">${chip(b.prov, b.prov)}${b.na ? chip('na', 'not applicable') : ''}${b.prov === 'proposed' ? chip('incomplete', 'unapproved') : chip('ok', 'approved · rev 37')}${b.bind.map((x) => chip('mono', x)).join('')}</span></div>`;
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
function selectBlock(id) { state.block = id; if (state.itab === 'findings') state.itab = 'inspect'; render(); }
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
function calculatorView() {
  const c = state.calc;
  const comp = HIST.filter((r) => r.arm === 'placebo' && r.endpoint === 'EASI-75');
  const inc = comp.filter((r) => r.comparable);
  const pooled = inc.reduce((a, r) => a + r.pct * r.n, 0) / inc.reduce((a, r) => a + r.n, 0);
  const r = sampleSize(c.p0, c.p1, c.alpha, c.power, c.ratio);
  const total = Math.ceil((r.n0 + r.n1) / (1 - c.dropout));
  const grid = [1, 2, 3].map((k) => [-0.05, 0, 0.05].map((d) => { const x = sampleSize(c.p0, c.p1 + d, c.alpha, c.power, k); return Math.ceil((x.n0 + x.n1) / (1 - c.dropout)); }));
  const inp = (k, label, min, max, step, fmt) => h`<div class="field"><label>${label} <span class="mono muted">${fmt(c[k])}</span></label><input type="range" min="${min}" max="${max}" step="${step}" value="${c[k]}" oninput="state.calc.${k}=+this.value;render()"></div>`;
  const body = h`<div class="page"><h1>Trial calculator</h1><div class="sub">Sample size for superiority · EASI-75 at Week 16 · two-proportion, normal approximation (formula documented in packages/stats; verified against published tables before Pilot D ships)</div>
  <div class="calc"><div class="panel"><h3>Inputs</h3><div class="body">
    <div class="field"><label>Endpoint · timepoint</label><div class="row"><select><option>EASI-75 (responder)</option><option>EASI-90</option><option>EASI CFB (continuous)</option><option>PP-NRS ≥4</option></select><select><option>Week 16</option><option>Week 12</option></select></div></div>
    <div class="field"><label>Comparator (placebo) — from reviewed historical records</label>
      <div class="tiny">${comp.map((x) => { const s = STUDIES.find((y) => y.id === x.study); return h`<div style="display:grid;grid-template-columns:16px 1fr auto auto;gap:2px 6px;align-items:center;padding:4px 0;border-bottom:1px dashed var(--slate-200)"><input type="checkbox" ${x.comparable ? 'checked' : 'disabled'}><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(s.name)}">${esc(s.name)} <span class="muted">${x.tp}</span></span><span class="mono">${x.pct}%</span>${chip('source', 'p.' + x.page)}${x.why ? h`<span></span><span style="grid-column:2/5">${chip('na', 'excluded: ' + x.why)}</span>` : ''}</div>`; }).join('')}</div>
      <div class="tiny" style="margin-top:6px"><label><input type="checkbox" ${c.pool ? 'checked' : ''} onchange="state.calc.pool=this.checked;state.calc.p0=${(pooled / 100).toFixed(3)};render()"> Pool included records (n-weighted) → ${pooled.toFixed(1)}%; between-study range ${Math.min(...inc.map((x) => x.pct))}–${Math.max(...inc.map((x) => x.pct))}%</label></div></div>
    ${inp('p0', 'Placebo response', 0.05, 0.4, 0.005, (v) => (v * 100).toFixed(1) + '%')}
    ${inp('p1', 'Anticipated SRK-201 response', 0.2, 0.9, 0.005, (v) => (v * 100).toFixed(1) + '%')}
    ${inp('alpha', 'α (two-sided)', 0.01, 0.1, 0.005, (v) => v.toFixed(3))}
    ${inp('power', 'Power', 0.7, 0.95, 0.01, (v) => (v * 100).toFixed(0) + '%')}
    ${inp('ratio', 'Allocation ratio active:placebo', 1, 3, 1, (v) => v + ':1')}
    ${inp('dropout', 'Dropout', 0, 0.3, 0.01, (v) => (v * 100).toFixed(0) + '%')}
  </div></div>
  <div><div class="panel" style="margin-bottom:16px"><h3>Result <span class="grow"></span><button class="btn sm" onclick="toast('Saved to work W-102 §10.11 as author-supplied sample_size with these assumptions (mock)')">Save to protocol §10.11</button></h3><div class="body">
    <div class="result-head"><div><div class="big">${total}</div><div class="lbl">total participants (incl. ${(c.dropout * 100).toFixed(0)}% dropout)</div></div><div><div class="big">${r.n1}</div><div class="lbl">SRK-201 (evaluable)</div></div><div><div class="big">${r.n0}</div><div class="lbl">placebo (evaluable)</div></div><div><div class="big">${((c.p1 - c.p0) * 100).toFixed(0)}</div><div class="lbl">pts absolute difference</div></div></div>
    <div class="tiny muted">Assumptions: p₀ ${(c.p0 * 100).toFixed(1)}% (${c.pool ? 'pooled ' + inc.length + ' records' : 'manual'}), p₁ ${(c.p1 * 100).toFixed(1)}%, α ${c.alpha}, power ${(c.power * 100).toFixed(0)}%, ratio ${c.ratio}:1. Unsupported here: Bayesian decision rules, precision-based N — stated, not forced.</div>
    <h5 class="muted" style="margin:16px 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:.06em">Sensitivity — total N by allocation ratio × anticipated effect</h5>
    <table class="heat"><thead><tr><th></th><th>p₁ −5 pts</th><th>p₁</th><th>p₁ +5 pts</th></tr></thead><tbody>${grid.map((row, i) => h`<tr><th>${i + 1}:1</th>${row.map((v, j) => h`<td class="${v > total * 1.3 ? 'h4' : v > total * 1.1 ? 'h3' : v > total * 0.9 ? 'h2' : 'h1'} ${i + 1 === c.ratio && j === 1 ? 'sel' : ''}">${v}</td>`).join('')}</tr>`).join('')}</tbody></table>
  </div></div>
  <div class="panel"><h3>Historical performance · EASI-75 · Week 12–16 <span class="grow"></span><span class="tiny muted">click a point to open its source page</span></h3><div class="body">
    <div class="strip">${[0, 25, 50, 75].map((y) => h`<span class="yl" style="bottom:${y}%">${y}%</span>`).join('')}
      ${HIST.filter((x) => x.endpoint === 'EASI-75').map((x, i) => { const s = STUDIES.find((y) => y.id === x.study); const left = 8 + (STUDIES.indexOf(s)) * 13; return h`<span class="dot ${x.arm === 'placebo' ? 'pbo' : x.jak ? 'jak' : 'act'}" style="left:${left}%;bottom:${x.pct}%" title="${esc(s.name)} · ${x.arm} · ${x.pct}% (n=${x.n}) · p. ${x.page}${x.why ? ' · excluded: ' + x.why : ''}" onclick="toast('Open ${esc(s.name)} p. ${x.page} (mock)')"></span>`; }).join('')}
      ${STUDIES.map((s, i) => h`<span class="xl" style="left:${8 + i * 13}%">${s.drug.slice(0, 9)}</span>`).join('')}</div>
    <div class="legend"><span><i style="background:var(--slate-400)"></i>placebo</span><span><i style="background:var(--accent-700)"></i>active</span><span><i style="background:var(--prov-inherited)"></i>JAK-like profile source</span></div>
    <div class="toolbar" style="margin-top:12px"><button class="btn" onclick="toast('Endpoint explorer (exploratory): profile JAK-like → endpoint × timepoint N alongside regulatory precedent + relevance (Pilot 4b)')">Open endpoint explorer (exploratory)</button><span class="tiny muted">Profile: <b>JAK-like</b> (saved object · 2 records · editable)</span></div>
  </div></div></div></div></div>`;
  return frame('calc', h`<b>Trial calculator</b>`, body);
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
