// In-place structure editing on library pages (chapter page cards + header):
// rename, change icon (icon library or upload), reorder by dragging, move to
// another chapter, add after, delete. Works on any element carrying
// data-ed-kind / data-ed-id / data-ed-parent.
(function () {
  const J = {'Content-Type': 'application/json'};
  const api = (m, u, b) => fetch(u, {method: m, headers: J, body: b ? JSON.stringify(b) : undefined}).then(r => r.json());
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const toast = m => { let t = document.getElementById('tempu-toast'); if (!t) { t = document.createElement('div'); t.id = 'tempu-toast'; document.body.appendChild(t); } t.textContent = m; t.classList.add('show'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2400); };
  const host = el => el.closest('[data-ed-kind]');
  const editing = () => document.documentElement.classList.contains('edit-mode');
  const LIB = location.pathname.split('/')[2];

  // ---------------------------------------------------------------- rename
  function rename(h) {
    const t = h.querySelector('.ed-title'); if (!t || t.isContentEditable) return;
    const old = t.textContent.trim();
    t.classList.add('ed-editing'); t.contentEditable = 'true'; t.focus();
    const r = document.createRange(); r.selectNodeContents(t); getSelection().removeAllRanges(); getSelection().addRange(r);
    const done = async save => {
      t.contentEditable = 'false'; t.classList.remove('ed-editing'); t.onkeydown = t.onblur = null;
      const v = t.textContent.trim();
      if (!save || !v || v === old) { t.textContent = old; return; }
      await api('PATCH', `/api/structure/${h.dataset.edKind}/${h.dataset.edId}`, {title: v});
      if (h.dataset.title !== undefined) h.dataset.title = v.toLowerCase();
      if (h.dataset.edKind === 'chapter') document.title = v + ' | TEMP-U';
      toast('Renamed');
    };
    t.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); done(true); } if (e.key === 'Escape') done(false); };
    t.onblur = () => done(true);
  }

  // ---------------------------------------------------------------- icon picker
  let icons = null, pickFor = null;
  const dlg = document.createElement('div');
  dlg.id = 'icon-picker'; dlg.className = 'ip-overlay hidden';
  dlg.innerHTML = `<div class="ip-box" role="dialog" aria-label="Choose an icon">
    <div class="ip-head"><b>Choose an icon</b><span class="ip-for"></span><button class="ip-x" aria-label="Close">✕</button></div>
    <div class="ip-tools"><input class="ip-q" type="search" placeholder="Search icons (heart, lung, kidney…)">
      <button class="ip-upload">⤒ Upload image…</button><button class="ip-remove">Remove icon</button></div>
    <div class="ip-grid"></div>
    <input type="file" accept="image/*" class="hidden ip-file"></div>`;
  document.body.appendChild(dlg);
  const grid = dlg.querySelector('.ip-grid'), q = dlg.querySelector('.ip-q');
  async function openPicker(h) {
    pickFor = h;
    dlg.querySelector('.ip-for').textContent = '— ' + (h.querySelector('.ed-title')?.textContent.trim() || '');
    dlg.classList.remove('hidden');
    if (!icons) { grid.innerHTML = '<p class="ip-empty">Loading…</p>'; icons = await api('GET', '/api/structure/icons'); }
    q.value = ''; draw(); q.focus();
  }
  function draw() {
    const v = q.value.trim().toLowerCase();
    const list = icons.filter(i => !v || i.name.toLowerCase().includes(v));
    const groups = {};
    list.forEach(i => (groups[i.group] = groups[i.group] || []).push(i));
    grid.innerHTML = Object.entries(groups).map(([g, items]) =>
      `<p class="ip-group">${esc(g)} <span>${items.length}</span></p><div class="ip-items">` +
      items.map(i => `<button class="ip-item" data-url="${esc(i.url)}" title="${esc(i.name)}"><img src="${esc(i.url)}" alt="" loading="lazy" onerror="this.parentElement.remove()"><span>${esc(i.name)}</span></button>`).join('') + '</div>'
    ).join('') || '<p class="ip-empty">No icons match. Upload your own image instead.</p>';
  }
  q.addEventListener('input', draw);
  const closePicker = () => { dlg.classList.add('hidden'); pickFor = null; };
  async function setIcon(url) {
    const h = pickFor; if (!h) return;
    await api('PATCH', `/api/structure/${h.dataset.edKind}/${h.dataset.edId}`, {icon_path: url});
    const box = h.querySelector('.ed-icon');
    box.querySelectorAll('img').forEach(i => i.remove());
    if (!url && h.dataset.edDefaultIcon) url = null;
    if (url) {
      const img = document.createElement('img'); img.src = url; img.alt = '';
      img.className = h.dataset.edIconClass || (h.dataset.edKind === 'chapter' ? 'size-10 object-contain' : 'object-contain size-16');
      box.prepend(img);
    }
    closePicker(); toast(url ? 'Icon updated' : 'Icon removed');
  }
  dlg.addEventListener('click', async e => {
    if (e.target === dlg || e.target.closest('.ip-x')) return closePicker();
    const it = e.target.closest('.ip-item'); if (it) return setIcon(it.dataset.url);
    if (e.target.closest('.ip-remove')) return setIcon(null);
    if (e.target.closest('.ip-upload')) dlg.querySelector('.ip-file').click();
  });
  dlg.querySelector('.ip-file').addEventListener('change', async e => {
    const f = e.target.files[0]; e.target.value = ''; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    const r = await fetch('/api/uploads', {method: 'POST', body: fd}).then(r => r.json());
    if (!r.url) return toast(r.error || 'Upload failed');
    icons = null;               // refresh "Your uploads" next time
    setIcon(r.url);
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !dlg.classList.contains('hidden')) closePicker(); });

  // ---------------------------------------------------------------- menu
  const menu = document.createElement('div');
  menu.className = 'ed-menu hidden';
  menu.innerHTML = `<button data-m="rename">✎ Rename</button><button data-m="icon">🖼 Change icon</button>
    <button data-m="add">＋ Add section after</button><button data-m="move">⇄ Move to another chapter…</button>
    <button data-m="up">↑ Move earlier</button><button data-m="down">↓ Move later</button>
    <div class="ed-menu-sep"></div><button data-m="delete" class="ed-danger">🗑 Delete section</button>`;
  document.body.appendChild(menu);
  let menuFor = null;
  function openMenu(h, btn) {
    menuFor = h;
    const r = btn.getBoundingClientRect();
    menu.style.top = (r.bottom + 6) + 'px'; menu.style.left = Math.max(8, Math.min(innerWidth - 240, r.left)) + 'px';
    menu.classList.remove('hidden');
  }
  document.addEventListener('click', e => { if (!menu.contains(e.target) && !e.target.closest('.ed-menu-btn')) menu.classList.add('hidden'); });

  async function del(h) {
    const kind = h.dataset.edKind, title = h.querySelector('.ed-title')?.textContent.trim();
    const what = kind === 'chapter' ? 'this chapter with all its sections and topics' : 'this section with all its topics';
    if (!confirm(`Move ${what} to the trash?\n\n“${title}”\n\nRestore it any time from Organize → Trash.`)) return;
    await api('DELETE', `/api/structure/${kind}/${h.dataset.edId}`);
    if (kind === 'chapter') { location.href = '/libraries/' + LIB; return; }
    h.remove(); toast('Moved to trash');
  }
  async function saveOrder() {
    const gridEl = document.getElementById('ch-grid'); if (!gridEl) return;
    const order = [...gridEl.querySelectorAll(':scope > [data-ed-kind="section"]')].map(x => x.dataset.edId);
    if (!order.length) return;
    await api('PATCH', `/api/structure/section/${order[0]}`, {parent_id: gridEl.dataset.chapter, order});
    toast('Order saved');
  }
  async function moveToChapter(h) {
    const tree = await api('GET', `/api/structure/tree/${LIB}`);
    const cur = h.dataset.edParent;
    const opts = tree.filter(c => c.id !== cur);
    const names = opts.map((c, i) => `${i + 1}. ${c.title}`).join('\n');
    const pick = prompt('Move this section to which chapter?\n\n' + names + '\n\nType the number:');
    const i = parseInt(pick, 10) - 1; if (!(i >= 0 && opts[i])) return;
    await api('PATCH', `/api/structure/section/${h.dataset.edId}`, {parent_id: opts[i].id});
    h.remove(); toast('Moved to “' + opts[i].title + '”');
  }
  menu.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b || !menuFor) return;
    const h = menuFor; menu.classList.add('hidden');
    const m = b.dataset.m;
    if (m === 'rename') return rename(h);
    if (m === 'icon') return openPicker(h);
    if (m === 'delete') return del(h);
    if (m === 'move') return moveToChapter(h);
    if (m === 'up' || m === 'down') {
      const sib = m === 'up' ? h.previousElementSibling : h.nextElementSibling;
      if (!sib || !sib.dataset.edKind) return;
      if (m === 'up') sib.before(h); else sib.after(h);
      return saveOrder();
    }
    if (m === 'add') {
      const title = prompt('Name of the new section:'); if (!title) return;
      const r = await api('POST', '/api/structure/section', {parent_id: h.dataset.edParent, title, after_id: h.dataset.edId});
      location.href = r.url || location.href;
    }
  });

  // ---------------------------------------------------------------- clicks
  document.addEventListener('click', e => {
    const h = host(e.target); if (!h || !editing()) return;
    if (e.target.closest('.ed-title') && !e.target.closest('.ed-title.ed-editing')) { e.preventDefault(); e.stopPropagation(); return rename(h); }
    if (e.target.closest('.ed-icon')) { e.preventDefault(); e.stopPropagation(); return openPicker(h); }
    if (e.target.closest('.ed-menu-btn')) { e.preventDefault(); e.stopPropagation(); return openMenu(h, e.target.closest('.ed-menu-btn')); }
    if (e.target.closest('.ed-rename')) { e.preventDefault(); return rename(h); }
    if (e.target.closest('.ed-del')) { e.preventDefault(); return del(h); }
    if (e.target.closest('.ed-title.ed-editing')) { e.preventDefault(); }   // typing a new name, not following the link
  }, true);
  document.addEventListener('dblclick', e => {
    const t = e.target.closest('.ed-title'); if (!t || !editing()) return;
    e.preventDefault(); rename(host(t));
  });

  document.addEventListener('tempu-edit-mode', ev => {
    if (!ev.detail) { document.querySelectorAll('.ed-title.ed-editing').forEach(t => t.blur()); closePicker(); menu.classList.add('hidden'); }
  });
  // library cards / headers: in edit mode a click on the card must not navigate
  document.addEventListener('click', e => {
    if (!editing()) return;
    const h = host(e.target);
    if (h && h.dataset.edKind === 'library' && e.target.closest('a') && !e.target.closest('.ed-nav-ok')) e.preventDefault();
  });
  // ---------------------------------------------------------------- drag to reorder cards
  const gridEl = document.getElementById('ch-grid');
  if (gridEl) {
    let dragEl = null;
    gridEl.addEventListener('dragstart', e => {
      const g = e.target.closest('.ed-grip'); if (!g || !editing()) return;
      dragEl = host(g); dragEl.classList.add('ed-dragging');
      e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragEl.dataset.edId);
      try { e.dataTransfer.setDragImage(dragEl, 40, 40); } catch (_) { /* */ }
    });
    gridEl.addEventListener('dragover', e => {
      if (!dragEl) return;
      e.preventDefault();
      const over = host(e.target);
      if (!over || over === dragEl || over.parentElement !== gridEl) return;
      const r = over.getBoundingClientRect();
      const before = (e.clientX - r.left) < r.width / 2;
      if (before) over.before(dragEl); else over.after(dragEl);
    });
    gridEl.addEventListener('drop', e => { if (dragEl) e.preventDefault(); });
    gridEl.addEventListener('dragend', () => { if (!dragEl) return; dragEl.classList.remove('ed-dragging'); dragEl = null; saveOrder(); });
  }
})();
