// Organizer: drag-and-drop tree of chapters > sections > topics.
// Add, rename (double-click), change icon, move (drag or "Move to…"),
// reorder, delete to trash, restore. Every change hits /api/structure/*.
(function () {
  const root = document.querySelector('.org-root'); if (!root) return;
  const LIB = root.dataset.library;
  const tree = document.getElementById('org-tree');
  const J = {'Content-Type': 'application/json'};
  // every call reports the server's reason when it refuses (e.g. "'Cardio' is in the trash. Restore it first.")
  const api = (method, url, body) => fetch(url, {method, headers: J, body: body ? JSON.stringify(body) : undefined})
    .then(r => r.json().catch(() => ({error: 'Something went wrong (' + r.status + ')'})))
    .then(d => { if (d && d.error) toast(d.error); return d; });
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const toast = m => { let t = document.getElementById('tempu-toast'); if (!t) { t = document.createElement('div'); t.id = 'tempu-toast'; document.body.appendChild(t); } t.textContent = m; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2600); };
  const OPEN_KEY = 'tempu-org-open:' + LIB;
  let open = new Set(); try { open = new Set(JSON.parse(localStorage.getItem(OPEN_KEY) || '[]')); } catch (e) { /* */ }
  const saveOpen = () => { try { localStorage.setItem(OPEN_KEY, JSON.stringify([...open])); } catch (e) { /* */ } };
  let data = [];
  const PARENT_KIND = {section: 'chapter', topic: 'section'};
  const CHILD_KIND = {chapter: 'section', section: 'topic'};

  const I = {
    grip: '⋮⋮',
    add: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
    edit: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.4 3.6a2.1 2.1 0 0 1 3 3L7.4 18.6 3 20l1.4-4.4Z"/></svg>',
    img: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/></svg>',
    move: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 9l-3 3 3 3M9 5l3-3 3 3M15 19l-3 3-3-3M19 9l3 3-3 3M2 12h20M12 2v20"/></svg>',
    open: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>',
    del: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    up: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m18 15-6-6-6 6"/></svg>',
    down: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m6 9 6 6 6-6"/></svg>',
  };

  // ---------------------------------------------------------------- render
  function row(kind, item, parentId, extra) {
    const kids = kind === 'chapter' ? item.sections : kind === 'section' ? item.topics : null;
    const isOpen = open.has(item.id);
    const href = kind === 'section' ? `/libraries/${LIB}/chapters/${parentId}/sections/${item.id}`
      : kind === 'topic' ? `/sections/${parentId}#topic-${item.id}`
      : `/libraries/${LIB}/chapters/${item.id}`;
    const icon = kind !== 'topic' ? `<span class="org-icon">${item.icon ? `<img src="${esc(item.icon)}" alt="" onerror="this.remove()">` : ''}</span>` : '';
    return `
    <div class="org-node org-${kind}" data-kind="${kind}" data-id="${item.id}" data-parent="${parentId}" id="${kind}-${item.id}">
      <div class="org-row" draggable="false" tabindex="0">
        <span class="org-grip" draggable="true" title="Drag to move">${I.grip}</span>
        ${kids ? `<button class="org-tog ${isOpen ? 'is-open' : ''}" title="Expand">▸</button>` : '<span class="org-tog-sp"></span>'}
        ${icon}
        <span class="org-title" title="Double-click to rename">${esc(item.title)}</span>
        ${item.mine ? '<span class="lib-badge">mine</span>' : ''}
        ${kids ? `<span class="org-count">${kids.length} ${kind === 'chapter' ? 'sections' : 'topics'}</span>` : ''}
        <span class="org-actions">
          ${CHILD_KIND[kind] ? `<button data-a="add" title="Add a ${CHILD_KIND[kind]} inside">${I.add}</button>` : ''}
          <button data-a="sibling" title="Add a ${kind} after this one">${I.add}<small>${kind[0].toUpperCase()}</small></button>
          <button data-a="rename" title="Rename">${I.edit}</button>
          ${kind !== 'topic' ? `<button data-a="icon" title="Change icon">${I.img}</button>` : ''}
          <button data-a="up" title="Move up">${I.up}</button>
          <button data-a="down" title="Move down">${I.down}</button>
          ${kind !== 'chapter' ? `<button data-a="move" title="Move to another ${PARENT_KIND[kind]}…">${I.move}</button>` : ''}
          <a href="${href}" title="Open" target="${kind === 'chapter' ? '_self' : '_self'}">${I.open}</a>
          <button data-a="delete" class="org-danger" title="Delete (to trash)">${I.del}</button>
        </span>
      </div>
      ${kids ? `<div class="org-kids ${isOpen ? '' : 'hidden'}">${kids.map(k => row(CHILD_KIND[kind], k, item.id)).join('')}${kids.length ? '' : `<p class="org-empty">Empty — drop a ${CHILD_KIND[kind]} here or use + to add one.</p>`}</div>` : ''}
    </div>`;
  }
  function render() {
    tree.innerHTML = data.length ? data.map(c => row('chapter', c, LIB)).join('')
      : '<p class="p-6 text-center text-sm text-muted-foreground">No chapters. Add one with “+ New chapter”.</p>';
    applyFilter();
  }
  async function load(focus) {
    data = await api('GET', `/api/structure/tree/${LIB}`);
    render();
    refreshTrashCount();
    if (focus) {
      const el = document.getElementById(focus);
      if (el) { el.scrollIntoView({block: 'center'}); el.classList.add('org-flash'); setTimeout(() => el.classList.remove('org-flash'), 1600); }
    }
  }

  // ---------------------------------------------------------------- helpers
  const nodeOf = el => el.closest('.org-node');
  const siblingsOf = node => [...node.parentElement.children].filter(x => x.classList.contains('org-node'));
  function openNode(id, on = true) { if (on) open.add(id); else open.delete(id); saveOpen(); }
  async function saveOrder(kind, parentId, container) {
    const order = [...container.children].filter(x => x.classList.contains('org-node') && x.dataset.kind === kind).map(x => x.dataset.id);
    return order;
  }

  // ---------------------------------------------------------------- actions
  tree.addEventListener('click', async e => {
    const tog = e.target.closest('.org-tog');
    const node = nodeOf(e.target); if (!node) return;
    const {kind, id, parent} = node.dataset;
    if (tog) {
      const kids = node.querySelector(':scope > .org-kids');
      const nowOpen = kids.classList.toggle('hidden') === false;
      tog.classList.toggle('is-open', nowOpen); openNode(id, nowOpen);
      return;
    }
    const b = e.target.closest('button[data-a]'); if (!b) return;
    const a = b.dataset.a;
    if (a === 'add' || a === 'sibling') {
      const k = a === 'add' ? CHILD_KIND[kind] : kind;
      const title = prompt(`Name of the new ${k}:`); if (!title) return;
      const body = a === 'add' ? {parent_id: id, title} : {parent_id: parent, title, after_id: id};
      const r = await api('POST', `/api/structure/${k}`, body);
      if (a === 'add') openNode(id, true);
      toast(`${k[0].toUpperCase() + k.slice(1)} added`);
      return load(`${k}-${r.id}`);
    }
    if (a === 'rename') return startRename(node);
    if (a === 'icon') { pendingIcon = node; document.getElementById('org-icon-file').click(); return; }
    if (a === 'up' || a === 'down') {
      const sibs = siblingsOf(node); const i = sibs.indexOf(node);
      const j = a === 'up' ? i - 1 : i + 1; if (j < 0 || j >= sibs.length) return;
      if (a === 'up') sibs[j].before(node); else sibs[j].after(node);
      const order = siblingsOf(node).map(x => x.dataset.id);
      await api('PATCH', `/api/structure/${kind}/${id}`, {parent_id: parent, order});
      node.querySelector('.org-row').focus();
      return;
    }
    if (a === 'move') return openMove(node);
    if (a === 'delete') {
      const what = kind === 'chapter' ? 'this chapter and all its sections and topics' : kind === 'section' ? 'this section and all its topics' : 'this topic';
      if (!confirm(`Move ${what} to the trash?\n\n“${node.querySelector('.org-title').textContent}”\n\nYou can restore it from Trash.`)) return;
      await api('DELETE', `/api/structure/${kind}/${id}`);
      toast('Moved to trash');
      return load();
    }
  });
  tree.addEventListener('dblclick', e => { const t = e.target.closest('.org-title'); if (t) startRename(nodeOf(t)); });
  function startRename(node) {
    const t = node.querySelector(':scope > .org-row .org-title');
    const old = t.textContent;
    t.contentEditable = 'true'; t.classList.add('is-editing'); t.focus();
    const r = document.createRange(); r.selectNodeContents(t); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    const done = async (save) => {
      t.contentEditable = 'false'; t.classList.remove('is-editing');
      t.removeEventListener('keydown', key); t.removeEventListener('blur', blur);
      const v = t.textContent.trim();
      if (!save || !v || v === old) { t.textContent = old; return; }
      await api('PATCH', `/api/structure/${node.dataset.kind}/${node.dataset.id}`, {title: v});
      toast('Renamed');
    };
    const key = e => { if (e.key === 'Enter') { e.preventDefault(); done(true); } if (e.key === 'Escape') done(false); };
    const blur = () => done(true);
    t.addEventListener('keydown', key); t.addEventListener('blur', blur);
  }

  // keyboard on a focused row: Alt+↑/↓ reorder, F2 rename, Delete
  tree.addEventListener('keydown', e => {
    const rowEl = e.target.closest('.org-row'); if (!rowEl || e.target.isContentEditable) return;
    const node = nodeOf(rowEl);
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); node.querySelector(`:scope > .org-row button[data-a="${e.key === 'ArrowUp' ? 'up' : 'down'}"]`).click(); }
    else if (e.key === 'F2') { e.preventDefault(); startRename(node); }
    else if (e.key === 'Delete') { e.preventDefault(); node.querySelector(':scope > .org-row button[data-a="delete"]').click(); }
  });

  // icons
  let pendingIcon = null;
  document.getElementById('org-icon-file').addEventListener('change', async e => {
    const f = e.target.files[0]; e.target.value = ''; if (!f || !pendingIcon) return;
    const fd = new FormData(); fd.append('file', f);
    const r = await fetch('/api/uploads', {method: 'POST', body: fd}).then(r => r.json());
    if (!r.url) { toast(r.error || 'Upload failed'); return; }
    await api('PATCH', `/api/structure/${pendingIcon.dataset.kind}/${pendingIcon.dataset.id}`, {icon_path: r.url});
    toast('Icon updated'); load(`${pendingIcon.dataset.kind}-${pendingIcon.dataset.id}`);
  });

  // ---------------------------------------------------------------- drag & drop
  let drag = null;       // {node, kind}
  const line = document.createElement('div'); line.className = 'org-drop-line'; document.body.appendChild(line);
  tree.addEventListener('dragstart', e => {
    const g = e.target.closest('.org-grip'); if (!g) return;
    const node = nodeOf(g);
    drag = {node, kind: node.dataset.kind};
    node.classList.add('org-dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', node.dataset.id);
    try { e.dataTransfer.setDragImage(node.querySelector('.org-row'), 12, 12); } catch (_) { /* */ }
  });
  tree.addEventListener('dragend', () => { if (drag) drag.node.classList.remove('org-dragging'); drag = null; clearDrop(); });
  let target = null;
  function clearDrop() { line.classList.remove('show'); tree.querySelectorAll('.org-into').forEach(x => x.classList.remove('org-into')); target = null; }
  function computeTarget(e) {
    const rowEl = e.target.closest('.org-row'); if (!rowEl) return null;
    const node = nodeOf(rowEl);
    if (!drag || node === drag.node || drag.node.contains(node)) return null;
    const k = node.dataset.kind, r = rowEl.getBoundingClientRect();
    if (k === drag.kind) return {mode: e.clientY < r.top + r.height / 2 ? 'before' : 'after', node, r};
    if (k === PARENT_KIND[drag.kind]) return {mode: 'into', node, r};
    // dropping a topic on a chapter / section on a topic: use the closest valid ancestor
    if (drag.kind === 'topic' && k === 'chapter') return null;
    if (drag.kind === 'section' && k === 'topic') { const sec = nodeOf(node.parentElement); return {mode: e.clientY < r.top + r.height / 2 ? 'before' : 'after', node: sec, r: sec.querySelector('.org-row').getBoundingClientRect()}; }
    if (drag.kind === 'chapter') { let up = node; while (up && up.dataset.kind !== 'chapter') up = nodeOf(up.parentElement); if (!up || up === drag.node) return null; const rr = up.querySelector('.org-row').getBoundingClientRect(); return {mode: e.clientY < rr.top + rr.height / 2 ? 'before' : 'after', node: up, r: rr}; }
    return null;
  }
  tree.addEventListener('dragover', e => {
    if (!drag) return;
    const t = computeTarget(e);
    clearDrop();
    if (!t) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    target = t;
    if (t.mode === 'into') t.node.querySelector('.org-row').classList.add('org-into');
    else {
      line.style.left = t.r.left + 'px'; line.style.width = t.r.width + 'px';
      line.style.top = (t.mode === 'before' ? t.r.top : t.r.bottom) - 2 + 'px';
      line.classList.add('show');
    }
  });
  tree.addEventListener('drop', async e => {
    if (!drag || !target) return;
    e.preventDefault();
    const {node} = drag, kind = drag.kind;
    let parentId, container;
    if (target.mode === 'into') {
      parentId = target.node.dataset.id;
      container = target.node.querySelector(':scope > .org-kids');
      container.querySelector(':scope > .org-empty')?.remove();
      container.appendChild(node);
      container.classList.remove('hidden'); openNode(parentId, true);
      target.node.querySelector(':scope > .org-row .org-tog')?.classList.add('is-open');
    } else {
      parentId = target.node.dataset.parent;
      if (target.mode === 'before') target.node.before(node); else target.node.after(node);
      container = node.parentElement;
    }
    node.dataset.parent = parentId;
    const order = [...container.children].filter(x => x.classList?.contains('org-node')).map(x => x.dataset.id);
    const id = node.dataset.id;
    clearDrop(); node.classList.remove('org-dragging'); drag = null;
    await api('PATCH', `/api/structure/${kind}/${id}`, {parent_id: parentId, order});
    toast('Moved');
    load(`${kind}-${id}`);
  });

  // ---------------------------------------------------------------- move dialog
  const mv = document.getElementById('org-move'), mvList = document.getElementById('org-move-list'), mvQ = document.getElementById('org-move-q');
  let mvNode = null;
  function openMove(node) {
    mvNode = node;
    const kind = node.dataset.kind;
    document.getElementById('org-move-title').textContent = `Move “${node.querySelector('.org-title').textContent}” to…`;
    const opts = [];
    data.forEach(c => {
      if (kind === 'section') opts.push({id: c.id, label: c.title, sub: `${c.sections.length} sections`});
      else c.sections.forEach(s => opts.push({id: s.id, label: s.title, sub: c.title}));
    });
    mv._opts = opts; mvQ.value = ''; drawMove(); mv.classList.remove('hidden'); mv.classList.add('flex'); mvQ.focus();
  }
  function drawMove() {
    const q = mvQ.value.trim().toLowerCase();
    mvList.innerHTML = mv._opts.filter(o => !q || o.label.toLowerCase().includes(q) || o.sub.toLowerCase().includes(q)).slice(0, 300)
      .map(o => `<button class="org-move-opt ${o.id === mvNode.dataset.parent ? 'is-current' : ''}" data-id="${o.id}"><span>${esc(o.label)}</span><small>${esc(o.sub)}</small></button>`).join('')
      || '<p class="p-4 text-sm text-muted-foreground">No match</p>';
  }
  mvQ.addEventListener('input', drawMove);
  const closeMove = () => { mv.classList.add('hidden'); mv.classList.remove('flex'); };
  document.getElementById('org-move-close').addEventListener('click', closeMove);
  mv.addEventListener('click', async e => {
    if (e.target === mv) return closeMove();
    const b = e.target.closest('.org-move-opt'); if (!b) return;
    const {kind, id} = mvNode.dataset;
    await api('PATCH', `/api/structure/${kind}/${id}`, {parent_id: b.dataset.id});
    openNode(b.dataset.id, true); closeMove(); toast('Moved'); load(`${kind}-${id}`);
  });

  // ---------------------------------------------------------------- trash
  const trashP = document.getElementById('org-trash');
  async function refreshTrashCount() {
    const t = await api('GET', '/api/structure/trash');
    document.getElementById('org-trash-n').textContent = t.length ? `(${t.length})` : '';
    return t;
  }
  async function drawTrash() {
    const t = await refreshTrashCount();
    document.getElementById('org-trash-list').innerHTML = t.length ? t.map(x => `
      <div class="org-trash-item" data-kind="${x.kind}" data-id="${x.id}">
        <div class="min-w-0"><p class="truncate font-medium">${esc(x.title)}</p>
        <p class="text-xs text-muted-foreground">${x.kind} · ${Object.entries(x.contains).map(([k, v]) => `${v} ${k}`).join(', ')} · ${new Date(x.deleted_at).toLocaleString()}</p></div>
        <div class="flex shrink-0 gap-1"><button data-t="restore" class="org-tbtn">Restore</button><button data-t="purge" class="org-tbtn org-danger">Delete forever</button></div>
      </div>`).join('') : '<p class="p-6 text-center text-sm text-muted-foreground">Trash is empty.</p>';
  }
  document.getElementById('org-trash-btn').addEventListener('click', () => { trashP.classList.remove('hidden'); trashP.classList.add('flex'); drawTrash(); });
  document.getElementById('org-trash-close').addEventListener('click', () => { trashP.classList.add('hidden'); trashP.classList.remove('flex'); });
  trashP.addEventListener('click', async e => {
    const b = e.target.closest('[data-t]'); if (!b) return;
    const it = b.closest('.org-trash-item');
    if (b.dataset.t === 'purge' && !confirm('Delete forever? This cannot be undone.')) return;
    const res = await api('POST', `/api/structure/${it.dataset.kind}/${it.dataset.id}/${b.dataset.t}`);
    if (!res || res.error || res.ok === false) return;          // the reason was shown already
    toast(b.dataset.t === 'restore' ? 'Restored' : 'Deleted forever');
    drawTrash(); load(b.dataset.t === 'restore' ? `${it.dataset.kind}-${it.dataset.id}` : null);
  });

  // ---------------------------------------------------------------- toolbar
  document.getElementById('org-add-chapter').addEventListener('click', async () => {
    const title = prompt('Name of the new chapter:'); if (!title) return;
    const r = await api('POST', '/api/structure/chapter', {parent_id: LIB, title});
    openNode(r.id, true); toast('Chapter added'); load(`chapter-${r.id}`);
  });
  document.getElementById('org-expand').addEventListener('click', () => {
    tree.querySelectorAll('.org-chapter, .org-section').forEach(n => open.add(n.dataset.id)); saveOpen(); render();
  });
  document.getElementById('org-collapse').addEventListener('click', () => { open.clear(); saveOpen(); render(); });
  const filt = document.getElementById('org-filter');
  function applyFilter() {
    const q = filt.value.trim().toLowerCase();
    tree.querySelectorAll('.org-node').forEach(n => n.classList.remove('org-hide', 'org-hit'));
    if (!q) return;
    const nodes = [...tree.querySelectorAll('.org-node')];
    nodes.forEach(n => n.classList.add('org-hide'));
    nodes.forEach(n => {
      if (n.querySelector(':scope > .org-row .org-title').textContent.toLowerCase().includes(q)) {
        n.classList.add('org-hit');
        let p = n; while (p) { p.classList.remove('org-hide'); p.querySelector(':scope > .org-kids')?.classList.remove('hidden'); p = nodeOf(p.parentElement); }
        n.querySelectorAll('.org-node').forEach(x => x.classList.remove('org-hide'));
      }
    });
  }
  filt.addEventListener('input', applyFilter);

  const hash = location.hash.slice(1);
  if (hash.startsWith('chapter-')) open.add(hash.slice(8));
  load(hash || null);
})();
