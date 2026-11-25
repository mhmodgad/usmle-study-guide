// Reader extras: reading progress bar, resume where you left off, prev/next
// section shortcuts, bookmark, remembered collapsed topics, and structure
// actions (add / move / delete topics, rename the section).
(function () {
  const root = document.querySelector('.reader-root'); if (!root) return;
  const SID = root.dataset.sectionId, LIB = root.dataset.libraryId;
  const isEmbed = document.documentElement.classList.contains('tempu-embed');
  const J = {'Content-Type': 'application/json'};
  const api = (m, u, b) => fetch(u, {method: m, headers: J, body: b ? JSON.stringify(b) : undefined}).then(r => r.json());
  const toast = m => (window.tempuToast ? window.tempuToast(m) : null);
  const articles = () => [...document.querySelectorAll('.topic-article')];
  const editing = () => document.documentElement.classList.contains('editing-content');

  // ---------- reading progress bar
  const bar = document.getElementById('read-progress');
  function progress() {
    const h = document.documentElement.scrollHeight - innerHeight;
    const r = h > 0 ? Math.min(1, Math.max(0, scrollY / h)) : 0;
    if (bar) bar.style.transform = `scaleX(${r})`;
    return r;
  }

  // ---------- remember where you are
  function currentTopic() {
    const y = 120;
    let cur = null;
    for (const a of articles()) { if (a.getBoundingClientRect().top <= y) cur = a; else break; }
    return cur || articles()[0];
  }
  let saveT = null, lastSaved = '';
  function savePos() {
    if (isEmbed) return;
    clearTimeout(saveT);
    saveT = setTimeout(() => {
      const a = currentTopic(); if (!a) return;
      const ratio = +progress().toFixed(3);
      const key = a.dataset.topicId + ':' + ratio;
      if (key === lastSaved) return; lastSaved = key;
      navigator.sendBeacon ? navigator.sendBeacon(`/api/sections/${SID}/state`, new Blob([JSON.stringify({last_topic_id: a.dataset.topicId, scroll_ratio: ratio})], {type: 'application/json'}))
        : api('POST', `/api/sections/${SID}/state`, {last_topic_id: a.dataset.topicId, scroll_ratio: ratio});
    }, 700);
  }
  addEventListener('scroll', () => { progress(); savePos(); }, {passive: true});
  addEventListener('pagehide', savePos);
  progress();

  // ---------- resume pill (only when the page wasn't opened at a specific place)
  const lastTopic = root.dataset.lastTopic, lastRatio = parseFloat(root.dataset.scroll || '0');
  const pill = document.getElementById('resume-pill');
  if (!isEmbed && !location.hash && lastTopic && lastRatio > 0.04 && document.getElementById('topic-' + lastTopic)) {
    const t = document.querySelector(`#topic-${lastTopic} .topic-title`)?.textContent || 'where you stopped';
    pill.className = 'resume-pill';
    pill.innerHTML = `<span>Continue where you left off — <b></b></span><button data-r="go">Resume</button><button data-r="x" aria-label="Dismiss">✕</button>`;
    pill.querySelector('b').textContent = t;
    pill.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.r === 'go') {
        const h = document.documentElement.scrollHeight - innerHeight;
        const el = document.getElementById('topic-' + lastTopic);
        const byRatio = lastRatio * h;
        const top = el.getBoundingClientRect().top + scrollY;
        scrollTo({top: Math.max(top - 80, Math.min(byRatio, top + el.offsetHeight - 200)), behavior: 'smooth'});
      }
      pill.remove();
    });
    setTimeout(() => pill && pill.remove(), 15000);
  }

  // ---------- keyboard: Alt+← / Alt+→ previous / next section
  addEventListener('keydown', e => {
    if (!e.altKey || editing() || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    if (e.key === 'ArrowLeft') { const a = document.getElementById('prev-section'); if (a) { e.preventDefault(); location.href = a.href; } }
    if (e.key === 'ArrowRight') { const a = document.getElementById('next-section'); if (a) { e.preventDefault(); location.href = a.href; } }
  });

  // ---------- bookmark
  const bm = document.getElementById('sec-bookmark');
  bm && bm.addEventListener('click', async () => {
    const on = !bm.classList.contains('is-on'); bm.classList.toggle('is-on', on);
    await api('POST', `/api/sections/${SID}/state`, {bookmarked: on});
    toast(on ? 'Section bookmarked' : 'Bookmark removed');
  });

  // ---------- remember collapsed topics per section
  const CK = 'tempu-collapsed:' + SID;
  let collapsed = new Set(); try { collapsed = new Set(JSON.parse(localStorage.getItem(CK) || '[]')); } catch (e) { /* */ }
  const target = (location.hash.match(/topic-([0-9a-f-]+)/) || [])[1];
  articles().forEach(a => {
    if (collapsed.has(a.dataset.topicId) && a.dataset.topicId !== target) {
      a.querySelector('.topic-body')?.classList.add('hidden');
      const ch = a.querySelector('.topic-chevron'); if (ch) ch.style.transform = 'rotate(-90deg)';
    }
  });
  const saveCollapsed = () => {
    const s = articles().filter(a => a.querySelector('.topic-body')?.classList.contains('hidden')).map(a => a.dataset.topicId);
    try { localStorage.setItem(CK, JSON.stringify(s)); } catch (e) { /* */ }
  };
  document.addEventListener('click', e => { if (e.target.closest('.topic-collapse, #collapse-all')) setTimeout(saveCollapsed, 0); });

  // ---------- structure actions
  async function addTopic(afterId) {
    const title = prompt('Title of the new topic:'); if (!title) return;
    const r = await api('POST', '/api/structure/topic', {parent_id: SID, title, after_id: afterId || undefined});
    sessionStorage.setItem('tempu-edit-after-load', r.id);
    location.hash = 'topic-' + r.id; location.reload();
  }
  document.getElementById('add-topic')?.addEventListener('click', () => addTopic(currentTopic()?.dataset.topicId));
  document.querySelectorAll('.add-topic-btn').forEach(b => b.addEventListener('click', () => addTopic(articles().slice(-1)[0]?.dataset.topicId)));
  // open a freshly created topic straight in the editor
  const fresh = sessionStorage.getItem('tempu-edit-after-load');
  if (fresh) {
    sessionStorage.removeItem('tempu-edit-after-load');
    const a = document.getElementById('topic-' + fresh);
    if (a && window.TempuContentEditor) setTimeout(() => window.TempuContentEditor.start(a), 150);
  }

  const menu = document.getElementById('topic-actions-menu');
  menu?.addEventListener('click', async e => {
    const b = e.target.closest('[data-sact]'); if (!b) return;
    const tid = menu.dataset.currentTopic; if (!tid) return;
    menu.classList.add('hidden');
    const art = document.getElementById('topic-' + tid);
    const ids = articles().map(a => a.dataset.topicId);
    const i = ids.indexOf(tid);
    if (b.dataset.sact === 'add-below') return addTopic(tid);
    if (b.dataset.sact === 'up' || b.dataset.sact === 'down') {
      const j = b.dataset.sact === 'up' ? i - 1 : i + 1; if (j < 0 || j >= ids.length) return;
      const other = document.getElementById('topic-' + ids[j]);
      if (b.dataset.sact === 'up') other.before(art); else other.after(art);
      await api('PATCH', `/api/structure/topic/${tid}`, {parent_id: SID, order: articles().map(a => a.dataset.topicId)});
      art.scrollIntoView({block: 'start', behavior: 'smooth'});
      return toast('Topic moved');
    }
    if (b.dataset.sact === 'delete') {
      const title = art.querySelector('.topic-title')?.textContent;
      if (!confirm(`Move the topic “${title}” to the trash?\nYou can restore it from Organize → Trash.`)) return;
      await api('DELETE', `/api/structure/topic/${tid}`);
      art.remove(); return toast('Topic moved to trash');
    }
    if (b.dataset.sact === 'move') return openMovePicker(tid);
  });

  // move-to-section picker
  async function openMovePicker(tid) {
    const tree = await api('GET', `/api/structure/tree/${LIB}`);
    const opts = [];
    tree.forEach(c => c.sections.forEach(s => opts.push({id: s.id, title: s.title, ch: c.title})));
    let dlg = document.getElementById('move-topic-dlg');
    if (!dlg) {
      dlg = document.createElement('div'); dlg.id = 'move-topic-dlg';
      dlg.className = 'fixed inset-0 z-[85] flex items-center justify-center bg-black/50 p-4';
      dlg.innerHTML = `<div class="flex max-h-[80vh] w-full max-w-md flex-col overflow-hidden rounded-2xl border bg-card shadow-2xl">
        <div class="flex items-center justify-between border-b px-5 py-3"><h3 class="font-semibold">Move topic to…</h3><button data-x class="rounded-md p-2 hover:bg-accent">✕</button></div>
        <div class="border-b p-3"><input type="search" placeholder="Search sections…" class="h-9 w-full rounded-lg border bg-background px-3 text-sm outline-none"></div>
        <div class="mt-list flex-1 overflow-auto p-2"></div></div>`;
      document.body.appendChild(dlg);
    }
    dlg.classList.remove('hidden');
    const q = dlg.querySelector('input'), list = dlg.querySelector('.mt-list');
    const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
    const draw = () => {
      const v = q.value.trim().toLowerCase();
      list.innerHTML = opts.filter(o => o.id !== SID && (!v || (o.title + ' ' + o.ch).toLowerCase().includes(v))).slice(0, 300)
        .map(o => `<button class="org-move-opt" data-id="${o.id}"><span>${esc(o.title)}</span><small>${esc(o.ch)}</small></button>`).join('');
    };
    q.value = ''; draw(); q.focus(); q.oninput = draw;
    dlg.onclick = async e => {
      if (e.target === dlg || e.target.closest('[data-x]')) { dlg.classList.add('hidden'); return; }
      const b = e.target.closest('.org-move-opt'); if (!b) return;
      await api('PATCH', `/api/structure/topic/${tid}`, {parent_id: b.dataset.id});
      dlg.classList.add('hidden');
      document.getElementById('topic-' + tid)?.remove();
      toast('Topic moved — it is now in “' + b.querySelector('span').textContent + '”');
    };
  }

  // rename the section (double-click its title)
  const h1 = document.getElementById('section-title');
  h1 && h1.addEventListener('click', () => {
    if (!document.documentElement.classList.contains('edit-mode') || h1.isContentEditable) return;
    const old = h1.textContent;
    h1.contentEditable = 'true'; h1.focus();
    const r = document.createRange(); r.selectNodeContents(h1); getSelection().removeAllRanges(); getSelection().addRange(r);
    const done = async save => {
      h1.contentEditable = 'false'; h1.onkeydown = h1.onblur = null;
      const v = h1.textContent.trim();
      if (!save || !v || v === old) { h1.textContent = old; return; }
      await api('PATCH', `/api/structure/section/${SID}`, {title: v});
      document.title = v + ' | TEMP-U'; toast('Section renamed');
    };
    h1.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); done(true); } if (e.key === 'Escape') done(false); };
    h1.onblur = () => done(true);
  });
})();
