// Reader: completion, topic notes (rich editor), highlights + inline notes,
// edit/delete popover, and an annotations side panel.
(function () {
  const post = (u, b) => fetch(u, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)});
  const patch = (u, b) => fetch(u, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)});
  const del = (u) => fetch(u, {method: 'DELETE'});
  // translucent washes matching the live app (overlay, text keeps its theme color)
  const HL = {yellow: 'rgba(255,205,75,0.24)', green: 'rgba(108,255,172,0.18)',
              blue: 'rgba(96,175,255,0.20)', pink: 'rgba(255,128,191,0.20)',
              orange: 'rgba(255,150,70,0.20)'};

  const secEl = document.querySelector('[data-section-id]');
  const sectionId = secEl && secEl.dataset.sectionId;
  if (sectionId) post('/api/progress/open', {section_id: sectionId});

  // ---------- completion ----------
  function refreshSecCount() {
    const total = document.querySelectorAll('.topic-complete').length;
    const done = document.querySelectorAll('.topic-complete:checked').length;
    const el = document.getElementById('sec-done'); if (el) el.textContent = done;
    const lbl = document.getElementById('section-complete-label');
    if (lbl) lbl.textContent = (done === total && total) ? 'Section complete' : 'Mark whole section complete';
  }
  document.querySelectorAll('.topic-complete').forEach(cb => cb.addEventListener('change', async () => {
    await post('/api/progress/topic', {topic_id: cb.dataset.topic, completed: cb.checked});
    const lbl = cb.closest('label').querySelector('.complete-label');
    if (lbl) lbl.textContent = cb.checked ? 'Completed' : 'Mark complete';
    refreshSecCount();
  }));
  const secBtn = document.getElementById('section-complete');
  if (secBtn) secBtn.addEventListener('click', async () => {
    const target = document.querySelectorAll('.topic-complete:not(:checked)').length !== 0;
    await post('/api/progress/section', {section_id: secBtn.dataset.section, completed: target});
    document.querySelectorAll('.topic-complete').forEach(cb => {
      cb.checked = target;
      const lbl = cb.closest('label').querySelector('.complete-label');
      if (lbl) lbl.textContent = target ? 'Completed' : 'Mark complete';
    });
    refreshSecCount();
  });

  // ---------- topic notes (shared rich editor) ----------
  document.querySelectorAll('.topic-note-btn').forEach(b => b.addEventListener('click', () =>
    window.TempuNoteEditor.open(b.dataset.topic, b.dataset.title)));
  document.addEventListener('note-saved', e => {
    const btn = document.querySelector(`.topic-note-btn[data-topic="${e.detail.topic}"]`);
    if (btn) btn.classList.toggle('text-primary', e.detail.hasText);
  });

  // ================= annotations =================
  const anns = [];                       // {id, kind, color, note, topic, title, selected, spans[]}
  const toolbar = document.getElementById('selection-toolbar');
  const inPop = document.getElementById('inline-note-pop');
  const annPop = document.getElementById('ann-pop');
  let pending = null, active = null;

  const articleOf = n => (n.nodeType === 1 ? n : n.parentNode)?.closest?.('.topic-article');
  const textOf = a => a.querySelector('.bn-editor') || a;
  const titleOf = a => a.querySelector('h2')?.textContent || 'Topic';

  function quoteContext(article, range) {
    const full = textOf(article).innerText, sel = range.toString();
    const idx = full.indexOf(sel);
    return {prefix: idx > 0 ? full.slice(Math.max(0, idx - 20), idx) : '',
            suffix: idx >= 0 ? full.slice(idx + sel.length, idx + sel.length + 20) : ''};
  }

  // ---- selection -> create ----
  document.addEventListener('mouseup', e => {
    if (toolbar.contains(e.target) || inPop.contains(e.target) || annPop.contains(e.target)) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) { hideToolbar(); return; }
    const range = sel.getRangeAt(0), article = articleOf(range.commonAncestorContainer);
    if (!article) { hideToolbar(); return; }
    const {prefix, suffix} = quoteContext(article, range);
    pending = {article, topic: article.dataset.topicId, title: titleOf(article),
               range: range.cloneRange(), selected: sel.toString(), prefix, suffix};
    const r = range.getBoundingClientRect();
    toolbar.style.left = Math.max(8, r.left + r.width / 2 - 90) + 'px';
    toolbar.style.top = (r.top - 46) + 'px';
    toolbar.classList.remove('hidden'); toolbar.classList.add('flex');
  });
  const hideToolbar = () => { toolbar.classList.add('hidden'); toolbar.classList.remove('flex'); };

  toolbar.querySelectorAll('button').forEach(b => b.addEventListener('mousedown', e => e.preventDefault()));
  toolbar.querySelectorAll('.hl-swatch').forEach(s => s.addEventListener('click', async () => {
    if (!pending) return;
    const id = crypto.randomUUID(), color = s.dataset.color;
    const ann = {id, kind: 'highlight', color, note: null, topic: pending.topic,
                 title: pending.title, selected: pending.selected};
    ann.spans = wrap(pending.range.cloneRange(), ann);
    anns.push(ann); renderPanel();
    await post('/api/highlights', {id, topic_id: pending.topic, color,
      selected_text: pending.selected, prefix_text: pending.prefix, suffix_text: pending.suffix});
    window.getSelection().removeAllRanges(); hideToolbar(); pending = null;
  }));
  document.getElementById('st-note').addEventListener('click', () => {
    if (!pending) return;
    document.getElementById('inp-quote').textContent = pending.selected;
    document.getElementById('inp-text').value = '';
    const r = pending.range.getBoundingClientRect();
    inPop.style.left = Math.max(8, Math.min(window.innerWidth - 300, r.left)) + 'px';
    inPop.style.top = (r.bottom + 8) + 'px';
    inPop.classList.remove('hidden'); hideToolbar();
    setTimeout(() => document.getElementById('inp-text').focus(), 0);
  });
  document.getElementById('inp-cancel').addEventListener('click', () => { inPop.classList.add('hidden'); pending = null; });
  document.getElementById('inp-save').addEventListener('click', async () => {
    if (!pending) return;
    const text = document.getElementById('inp-text').value.trim(); if (!text) return;
    const id = crypto.randomUUID();
    const ann = {id, kind: 'inline', color: null, note: text, topic: pending.topic,
                 title: pending.title, selected: pending.selected};
    ann.spans = wrap(pending.range.cloneRange(), ann);
    anns.push(ann); renderPanel();
    await post('/api/inline-notes', {id, topic_id: pending.topic, note_text: text,
      selected_text: pending.selected, prefix_text: pending.prefix, suffix_text: pending.suffix});
    inPop.classList.add('hidden'); window.getSelection().removeAllRanges(); pending = null;
  });

  // ---- wrap a range; returns the created spans ----
  function wrap(range, ann) {
    const texts = [], walker = document.createTreeWalker(range.commonAncestorContainer, NodeFilter.SHOW_TEXT);
    let n; while ((n = walker.nextNode())) { if (range.intersectsNode(n)) texts.push(n); }
    if (!texts.length && range.startContainer.nodeType === 3) texts.push(range.startContainer);
    const spans = [];
    texts.forEach(tn => {
      const s = (tn === range.startContainer) ? range.startOffset : 0;
      const e = (tn === range.endContainer) ? range.endOffset : tn.length;
      if (e <= s) return;
      const mid = tn.splitText(s); mid.splitText(e - s);
      const span = document.createElement(ann.kind === 'highlight' ? 'mark' : 'span');
      span.className = 'tempu-highlight' + (ann.kind === 'inline' ? ' tempu-inline-anchor' : '');
      span.dataset.annId = ann.id;
      style(span, ann);
      mid.parentNode.replaceChild(span, mid); span.appendChild(mid);
      spans.push(span);
    });
    return spans;
  }
  function style(span, ann) {
    if (ann.kind === 'highlight') { span.style.background = HL[ann.color] || ann.color; }
    if (ann.note) span.title = ann.note;
  }

  // ---- click an existing annotation -> popover ----
  document.addEventListener('click', e => {
    const span = e.target.closest?.('.tempu-highlight'); if (!span) return;
    const ann = anns.find(a => a.id === span.dataset.annId); if (!ann) return;
    openAnnPop(ann, span);
  });
  function openAnnPop(ann, span) {
    active = ann;
    const wrapEl = document.getElementById('ap-note-wrap');
    const ta = document.getElementById('ap-note');
    if (ann.kind === 'inline') { wrapEl.classList.remove('hidden'); ta.value = ann.note || ''; }
    else wrapEl.classList.add('hidden');
    annPop.querySelectorAll('.ap-color').forEach(c => c.style.display = ann.kind === 'highlight' ? '' : 'none');
    const r = span.getBoundingClientRect();
    annPop.style.left = Math.max(8, Math.min(window.innerWidth - 272, r.left)) + 'px';
    annPop.style.top = (r.bottom + 6) + 'px';
    annPop.classList.remove('hidden');
  }
  annPop.querySelectorAll('.ap-color').forEach(c => c.addEventListener('click', async () => {
    if (!active) return;
    active.color = c.dataset.color;
    if (active.kind !== 'highlight') return;  // recolor only highlights
    active.spans.forEach(s => style(s, active));
    await patch('/api/highlights/' + active.id, {color: active.color});
    renderPanel(); annPop.classList.add('hidden');
  }));
  document.getElementById('ap-remove').addEventListener('click', async () => {
    if (!active) return;
    active.spans.forEach(s => { const parent = s.parentNode; while (s.firstChild) parent.insertBefore(s.firstChild, s); parent.removeChild(s); parent.normalize(); });
    await del((active.kind === 'highlight' ? '/api/highlights/' : '/api/inline-notes/') + active.id);
    anns.splice(anns.indexOf(active), 1); renderPanel(); annPop.classList.add('hidden'); active = null;
  });
  document.getElementById('ap-note-save').addEventListener('click', async () => {
    if (!active) return;
    active.note = document.getElementById('ap-note').value.trim();
    active.spans.forEach(s => s.title = active.note);
    await patch('/api/inline-notes/' + active.id, {note_text: active.note});
    renderPanel(); annPop.classList.add('hidden');
  });
  document.addEventListener('mousedown', e => {
    if (!annPop.contains(e.target) && !e.target.closest?.('.tempu-highlight')) annPop.classList.add('hidden');
    if (!toolbar.contains(e.target) && !inPop.contains(e.target) && inPop.classList.contains('hidden')) hideToolbar();
  });

  // ---- re-apply saved annotations on load (text-quote anchoring) ----
  function findRange(article, selected, prefix) {
    const root = textOf(article), hay = root.innerText;
    let at = -1;
    if (prefix) { const p = hay.indexOf(prefix + selected); if (p >= 0) at = p + prefix.length; }
    if (at < 0) at = hay.indexOf(selected);
    if (at < 0) return null;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let pos = 0, sN = null, sO = 0, eN = null, eO = 0, node; const end = at + selected.length;
    while ((node = walker.nextNode())) {
      const len = node.length;
      if (!sN && pos + len > at) { sN = node; sO = at - pos; }
      if (pos + len >= end) { eN = node; eO = end - pos; break; }
      pos += len;
    }
    if (!sN || !eN) return null;
    const r = document.createRange();
    try { r.setStart(sN, sO); r.setEnd(eN, eO); } catch (e) { return null; }
    return r;
  }
  const data = (() => { try { return JSON.parse(document.getElementById('annotations-data').textContent); } catch (e) { return {}; } })();
  document.querySelectorAll('.topic-article').forEach(article => {
    const a = data[article.dataset.topicId]; if (!a) return;
    const title = titleOf(article), topic = article.dataset.topicId;
    (a.highlights || []).forEach(h => {
      const r = findRange(article, h.selected_text, h.prefix_text); if (!r) return;
      const ann = {id: h.id, kind: 'highlight', color: h.color, note: null, topic, title, selected: h.selected_text};
      ann.spans = wrap(r, ann); anns.push(ann);
    });
    (a.inlineNotes || []).forEach(nn => {
      const r = findRange(article, nn.selected_text, nn.prefix_text); if (!r) return;
      const ann = {id: nn.id, kind: 'inline', color: null, note: nn.note_text, topic, title, selected: nn.selected_text};
      ann.spans = wrap(r, ann); anns.push(ann);
    });
  });

  // ---- annotations side panel ----
  const panel = document.getElementById('ann-panel');
  const panelBody = document.getElementById('ann-panel-body');
  const countEl = document.getElementById('ann-count');
  function renderPanel() {
    countEl.textContent = anns.length || '';
    if (!anns.length) { panelBody.innerHTML = '<p class="p-4 text-sm text-muted-foreground">Select text in a topic to highlight it or attach a note.</p>'; return; }
    panelBody.innerHTML = anns.map((a, i) => `
      <button data-i="${i}" class="ann-item mb-2 block w-full rounded-lg border bg-background p-3 text-left hover:border-primary/40">
        <div class="flex items-center gap-2 text-xs text-muted-foreground">
          ${a.kind === 'highlight' ? `<span class="h-3 w-3 rounded-full" style="background:${HL[a.color] || a.color}"></span>Highlight` :
            `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.4 2.6a2 2 0 0 1 3 3L9 18l-4 1 1-4Z"></path></svg>Note`}
          <span class="ml-auto truncate">${a.title}</span>
        </div>
        <p class="mt-1 line-clamp-2 text-sm ${a.kind === 'highlight' ? '' : 'italic text-muted-foreground'}">${escapeHtml(a.selected)}</p>
        ${a.note ? `<p class="mt-1 line-clamp-2 text-sm">${escapeHtml(a.note)}</p>` : ''}
      </button>`).join('');
    panelBody.querySelectorAll('.ann-item').forEach(el => el.addEventListener('click', () => {
      const a = anns[+el.dataset.i], sp = a.spans && a.spans[0];
      if (sp) { sp.scrollIntoView({behavior: 'smooth', block: 'center'});
        sp.animate([{filter: 'brightness(1.6)'}, {filter: 'brightness(1)'}], {duration: 900}); }
    }));
  }
  function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
  const annToggle = document.getElementById('annotations-toggle');
  const isModern = () => document.documentElement.classList.contains('look-modern');
  function setDocked(on) {
    document.documentElement.classList.toggle('ann-docked', on);
    panel.classList.toggle('hidden', !on); panel.classList.toggle('flex', on);
    try { localStorage.setItem('tempu-ann-docked', on ? '1' : '0'); } catch (e) {}
  }
  if (annToggle) annToggle.addEventListener('click', () => {
    if (isModern() && window.matchMedia('(min-width: 1280px)').matches) {
      setDocked(!document.documentElement.classList.contains('ann-docked'));
    } else {
      const open = panel.classList.contains('hidden');
      panel.classList.toggle('hidden', !open); panel.classList.toggle('flex', open);
    }
  });
  document.getElementById('ann-panel-close').addEventListener('click', () => {
    document.documentElement.classList.remove('ann-docked');
    panel.classList.add('hidden'); panel.classList.remove('flex');
    try { localStorage.setItem('tempu-ann-docked', '0'); } catch (e) {}
  });
  // restore docked sidebar in modern look on wide screens
  try {
    if (isModern() && localStorage.getItem('tempu-ann-docked') === '1' &&
        window.matchMedia('(min-width: 1280px)').matches) setDocked(true);
  } catch (e) {}
  renderPanel();

  // ---- collapse topics (per-topic + collapse all) ----
  function setCollapsed(article, collapsed) {
    const body = article.querySelector('.topic-body');
    const chev = article.querySelector('.topic-chevron');
    if (body) body.classList.toggle('hidden', collapsed);
    if (chev) chev.style.transform = collapsed ? 'rotate(-90deg)' : '';
  }
  document.querySelectorAll('.topic-collapse').forEach(btn => btn.addEventListener('click', () => {
    const art = btn.closest('.topic-article');
    setCollapsed(art, !art.querySelector('.topic-body').classList.contains('hidden'));
  }));
  const collapseAll = document.getElementById('collapse-all');
  if (collapseAll) collapseAll.addEventListener('click', () => {
    const arts = [...document.querySelectorAll('.topic-article')];
    const anyOpen = arts.some(a => !a.querySelector('.topic-body').classList.contains('hidden'));
    arts.forEach(a => setCollapsed(a, anyOpen));
    document.getElementById('collapse-all-label').textContent = anyOpen ? 'Expand all' : 'Collapse all';
  });

  // ---- breadcrumb sibling dropdowns ----
  document.querySelectorAll('.crumb-btn').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const menu = btn.nextElementSibling;
    const wasOpen = !menu.classList.contains('hidden');
    document.querySelectorAll('.crumb-menu').forEach(m => m.classList.add('hidden'));
    menu.classList.toggle('hidden', wasOpen);
  }));
  document.addEventListener('click', e => {
    if (!e.target.closest?.('.crumb-btn') && !e.target.closest?.('.crumb-menu'))
      document.querySelectorAll('.crumb-menu').forEach(m => m.classList.add('hidden'));
  });

  // ---- table of contents ----
  const tocBtn = document.getElementById('toc-btn'), tocPanel = document.getElementById('toc-panel');
  if (tocBtn) tocBtn.addEventListener('click', e => { e.stopPropagation(); tocPanel.classList.toggle('hidden'); });
  tocPanel?.querySelectorAll('.toc-item').forEach(a => a.addEventListener('click', e => {
    e.preventDefault();
    const el = document.getElementById(a.getAttribute('href').slice(1));
    if (el) { setCollapsed(el, false); el.scrollIntoView({behavior: 'smooth', block: 'start'}); }
    tocPanel.classList.add('hidden');
  }));
  document.addEventListener('click', e => {
    if (tocPanel && !tocPanel.contains(e.target) && e.target !== tocBtn && !tocBtn?.contains(e.target)) tocPanel.classList.add('hidden');
  });

  // ---- topic actions menu ----
  const actMenu = document.getElementById('topic-actions-menu');
  let actTopic = null, actTitle = null;
  document.querySelectorAll('.topic-actions-btn').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    actTopic = btn.dataset.topic; actTitle = btn.dataset.title;
    const r = btn.getBoundingClientRect();
    actMenu.style.top = (r.bottom + 6) + 'px';
    actMenu.style.left = Math.max(8, r.right - 208) + 'px';
    actMenu.classList.remove('hidden');
  }));
  document.addEventListener('click', e => { if (actMenu && !actMenu.contains(e.target)) actMenu.classList.add('hidden'); });
  actMenu?.querySelectorAll('button[data-act]').forEach(b => b.addEventListener('click', async () => {
    actMenu.classList.add('hidden');
    if (b.dataset.act === 'note') { window.TempuNoteEditor?.open(actTopic, actTitle); }
    else if (b.dataset.act === 'annotate') { location.href = actMenu.dataset.annotateBase + actTopic + '/annotate'; }
    else if (b.dataset.act === 'copy') {
      const url = location.origin + location.pathname + '#topic-' + actTopic;
      try { await navigator.clipboard.writeText(url); } catch (e) {}
    } else if (b.dataset.act === 'collection') { openCollectionPicker(actTopic, actTitle); }
  }));

  // ---- save-to-collection picker ----
  const collModal = document.getElementById('coll-modal');
  let collTopic = null;
  async function renderCollections() {
    const list = document.getElementById('coll-list');
    const d = await (await fetch('/api/collections')).json();
    const cols = d.collections || [];
    list.innerHTML = cols.length ? cols.map(c =>
      `<button class="coll-pick flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm hover:bg-accent" data-id="${c.id}">
         <span class="truncate">${escapeHtml(c.title)}</span><span class="text-xs text-muted-foreground">${c.item_count} items</span></button>`
    ).join('') : '<p class="px-3 py-4 text-center text-sm text-muted-foreground">No collections yet — create one below.</p>';
    list.querySelectorAll('.coll-pick').forEach(el => el.addEventListener('click', () => addToCollection(el.dataset.id)));
  }
  async function addToCollection(cid) {
    await fetch('/api/collections/' + cid + '/items', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({item_type: 'topic', topic_id: collTopic})}).catch(() => {});
    collModal.classList.add('hidden'); collModal.classList.remove('flex');
  }
  function openCollectionPicker(topicId, title) {
    collTopic = topicId;
    document.getElementById('coll-sub').textContent = 'Topic: ' + title;
    document.getElementById('coll-new').value = '';
    renderCollections();
    collModal.classList.remove('hidden'); collModal.classList.add('flex');
  }
  document.getElementById('coll-close')?.addEventListener('click', () => { collModal.classList.add('hidden'); collModal.classList.remove('flex'); });
  document.getElementById('coll-create')?.addEventListener('click', async () => {
    const title = document.getElementById('coll-new').value.trim();
    if (!title) return;
    const r = await (await fetch('/api/collections', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title})})).json();
    if (r.id) await addToCollection(r.id);
  });

  // ---- per-topic flashcards dialog ----
  const fcModal = document.getElementById('fc-modal');
  async function openCards(topicId, title) {
    const r = await fetch('/api/cards?scope=topic&id=' + encodeURIComponent(topicId));
    const d = await r.json();
    const cards = d.cards || [];
    document.getElementById('fc-title').textContent = title;
    const stage = document.getElementById('fc-stage'), foot = document.getElementById('fc-foot');
    let i = 0, revealed = false;
    function show() {
      if (i >= cards.length) { stage.innerHTML = '<p class="py-10 text-center text-muted-foreground">Done — ' + cards.length + ' cards reviewed.</p>'; foot.innerHTML = ''; return; }
      revealed = false;
      stage.innerHTML = cards[i].front_html;
      document.getElementById('fc-progress').textContent = (i + 1) + ' / ' + cards.length;
      foot.innerHTML = '<button id="fc-reveal" class="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-primary-foreground">Reveal answer · Space</button>';
      foot.querySelector('#fc-reveal').onclick = reveal;
    }
    function reveal() {
      revealed = true; stage.innerHTML = cards[i].back_html;
      const pv = cards[i].previews || {};
      foot.innerHTML = '<div class="grid grid-cols-4 gap-2">' +
        [['1','Again','text-tag-orange'],['2','Hard',''],['3','Good','text-status-success'],['4','Easy','text-status-info']]
        .map(([n,l,c]) => '<button class="fc-rate rounded-xl border py-2 text-xs hover:bg-accent" data-r="'+n+'"><div class="font-semibold '+c+'">'+l+'</div><div class="text-[10px] text-muted-foreground">'+(pv[n]||'')+'</div></button>').join('') + '</div>';
      foot.querySelectorAll('.fc-rate').forEach(b => b.onclick = () => rate(+b.dataset.r));
    }
    async function rate(n) {
      try { await fetch('/api/review', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({card_id: cards[i].id, rating: n})}); } catch(e){}
      i++; show();
    }
    fcModal._reveal = () => { if (!revealed) reveal(); };
    fcModal._rate = (n) => { if (revealed) rate(n); };
    if (!cards.length) { stage.innerHTML = '<p class="py-10 text-center text-muted-foreground">No cards for this topic.</p>'; foot.innerHTML=''; }
    else show();
    fcModal.classList.remove('hidden'); fcModal.classList.add('flex');
  }
  document.querySelectorAll('.topic-cards-btn').forEach(b => b.addEventListener('click', () => openCards(b.dataset.topic, b.dataset.title)));
  document.getElementById('fc-close')?.addEventListener('click', () => { fcModal.classList.add('hidden'); fcModal.classList.remove('flex'); });
  document.addEventListener('keydown', e => {
    if (fcModal && !fcModal.classList.contains('hidden')) {
      if (e.key === ' ') { e.preventDefault(); fcModal._reveal?.(); }
      else if (['1','2','3','4'].includes(e.key)) fcModal._rate?.(+e.key);
      else if (e.key === 'Escape') { fcModal.classList.add('hidden'); fcModal.classList.remove('flex'); }
    }
  });

  // ---- image lightbox (modern look only) ----
  let zoomBackdrop = null;
  function closeZoom() {
    document.querySelectorAll('img.modern-zoomed').forEach(i => i.classList.remove('modern-zoomed'));
    if (zoomBackdrop) { zoomBackdrop.remove(); zoomBackdrop = null; }
  }
  document.querySelectorAll('.bn-editor img').forEach(img => img.addEventListener('click', () => {
    if (!document.documentElement.classList.contains('look-modern')) return;
    if (img.classList.contains('modern-zoomed')) { closeZoom(); return; }
    closeZoom();
    zoomBackdrop = document.createElement('div');
    zoomBackdrop.className = 'modern-zoom-backdrop';
    zoomBackdrop.addEventListener('click', closeZoom);
    document.body.appendChild(zoomBackdrop);
    img.classList.add('modern-zoomed');
  }));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeZoom(); });

  // scroll to hash topic
  if (location.hash.startsWith('#topic-')) {
    const el = document.getElementById(location.hash.slice(1));
    if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
})();
