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
    if (!article || article.classList.contains('is-editing')) { hideToolbar(); return; }
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

  // ---- per-topic flashcards dialog (live-app layout: fixed size, quick review) ----
  const fcModal = document.getElementById('fc-modal');
  const KBD = k => `<kbd class="fc-kbd">${k}</kbd>`;
  const ARROW_L = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>';
  const ARROW_R = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>';
  let fc = null;   // {all, deck, i, revealed, results:{id:'got'|'miss'}}
  function fcClose() {
    if (!fcModal) return;
    fcModal.classList.add('hidden'); fcModal.setAttribute('aria-hidden', 'true');
    document.documentElement.classList.remove('fc-open');
    fc = null;
  }
  function fcRender() {
    const stage = document.getElementById('fc-stage'), foot = document.getElementById('fc-foot');
    const top = document.getElementById('fc-top');
    const n = fc.deck.length;
    const got = Object.values(fc.results).filter(v => v === 'got').length;
    const miss = Object.values(fc.results).filter(v => v === 'miss').length;
    document.getElementById('fc-got').textContent = got;
    document.getElementById('fc-miss').textContent = miss;
    document.getElementById('fc-end').disabled = !(got + miss);
    document.querySelector('.fc-body').scrollTop = 0;
    if (fc.done || !n) {
      top.classList.add('hidden');
      stage.innerHTML = !n ? '<div class="fc-empty">No flashcards for this topic.</div>' :
        `<div class="fc-summary"><p class="text-sm font-medium uppercase tracking-widest text-muted-foreground">Session complete</p>
          <p class="mt-3 text-4xl font-semibold tabular-nums">${got}<span class="text-xl text-muted-foreground"> / ${got + miss}</span></p>
          <p class="mt-1 text-sm text-muted-foreground">cards you got right</p>
          <div class="mt-6 flex justify-center gap-2"><span class="fc-pill fc-pill-got">✓ Got ${got}</span><span class="fc-pill fc-pill-miss">↺ Missed ${miss}</span></div></div>`;
      foot.innerHTML = !n ? '' : `<div class="grid gap-2 ${miss ? 'grid-cols-2' : ''}">
          ${miss ? `<button class="fc-btn fc-btn-primary" data-fc="missed">Review missed (${miss})</button>` : ''}
          <button class="fc-btn ${miss ? 'fc-btn-outline' : 'fc-btn-primary'}" data-fc="again">Start over</button></div>
          <div class="flex justify-center"><button class="fc-btn fc-btn-ghost" data-fc="close">Close</button></div>`;
      return;
    }
    top.classList.remove('hidden');
    const c = fc.deck[fc.i];
    document.getElementById('fc-idx').textContent = fc.i + 1;
    document.getElementById('fc-of').textContent = 'of ' + n;
    document.getElementById('fc-bar').style.transform = `scaleX(${(fc.i) / n})`;
    stage.innerHTML = `<div class="fc-card-wrap">${fc.revealed ? c.back_html : c.front_html}</div>`;
    if (fc.revealed) { const lbl = stage.querySelector('.card-surface .uppercase span'); if (lbl) lbl.textContent = 'Answer'; }
    foot.innerHTML = (fc.revealed
        ? `<div class="grid grid-cols-2 gap-2" role="group" aria-label="How did it go?">
             <button class="fc-btn fc-btn-miss" data-fc="miss">↺ Missed it ${KBD('1')}</button>
             <button class="fc-btn fc-btn-got" data-fc="got">✓ Got it ${KBD('2')}</button></div>`
        : `<button class="fc-btn fc-btn-primary fc-btn-lg" data-fc="reveal">Reveal answer ${KBD('Space')}</button>`) +
      `<div class="flex items-center justify-between">
         <button class="fc-btn fc-btn-ghost" data-fc="prev" ${fc.i === 0 ? 'disabled' : ''}>${KBD(ARROW_L)} Previous</button>
         <button class="fc-btn fc-btn-ghost" data-fc="next">Next ${KBD(ARROW_R)}</button></div>`;
  }
  function fcAct(a) {
    if (!fc) return;
    if (a === 'close') return fcClose();
    if (a === 'reveal') { fc.revealed = true; return fcRender(); }
    if (a === 'got' || a === 'miss') { if (!fc.revealed) return; fc.results[fc.deck[fc.i].id] = a; return fcAct('next'); }
    if (a === 'next') { if (fc.i + 1 >= fc.deck.length) { fc.done = true; } else { fc.i++; fc.revealed = false; } return fcRender(); }
    if (a === 'prev') { if (fc.i > 0) { fc.i--; fc.revealed = false; fcRender(); } return; }
    if (a === 'end') { fc.done = true; return fcRender(); }
    if (a === 'again') { fc.deck = fc.all.slice(); fc.i = 0; fc.revealed = false; fc.done = false; fc.results = {}; return fcRender(); }
    if (a === 'missed') { const m = fc.deck.filter(c => fc.results[c.id] === 'miss'); fc.deck = m; fc.i = 0; fc.revealed = false; fc.done = false; fc.results = {}; return fcRender(); }
    if (a === 'shuffle') { const d = fc.deck.slice(fc.i); for (let k = d.length - 1; k > 0; k--) { const j = Math.floor(Math.random() * (k + 1)); [d[k], d[j]] = [d[j], d[k]]; } fc.deck = fc.deck.slice(0, fc.i).concat(d); fc.revealed = false; return fcRender(); }
  }
  async function openCards(topicId, title) {
    const r = await fetch('/api/cards?scope=topic&id=' + encodeURIComponent(topicId));
    const d = await r.json();
    const cards = d.cards || [];
    document.getElementById('fc-title').textContent = title;
    fc = {all: cards, deck: cards.slice(), i: 0, revealed: false, done: false, results: {}};
    fcRender();
    fcModal.classList.remove('hidden'); fcModal.setAttribute('aria-hidden', 'false');
    document.documentElement.classList.add('fc-open');
    fcModal.querySelector('.fc-dialog').focus?.();
  }
  window.tempuOpenCards = openCards;
  if (fcModal) {
    fcModal.addEventListener('click', e => {
      if (e.target === fcModal) return fcClose();                       // click outside the dialog
      const b = e.target.closest('[data-fc]'); if (b && !b.disabled) return fcAct(b.dataset.fc);
      if (e.target.closest('#fc-close')) return fcClose();
      if (e.target.closest('#fc-end')) return fcAct('end');
      if (e.target.closest('#fc-shuffle')) return fcAct('shuffle');
      if (e.target.closest('#fc-restart')) return fcAct('again');
    });
  }
  document.querySelectorAll('.topic-cards-btn').forEach(b => b.addEventListener('click', () => openCards(b.dataset.topic, b.dataset.title)));
  document.addEventListener('keydown', e => {
    if (!fc || !fcModal || fcModal.classList.contains('hidden')) return;
    if (/INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
    if (e.key === ' ') { e.preventDefault(); if (!fc.done && !fc.revealed) fcAct('reveal'); }
    else if (e.key === '1') fcAct('miss');
    else if (e.key === '2') fcAct('got');
    else if (e.key === 'ArrowRight') { e.preventDefault(); fcAct('next'); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); fcAct('prev'); }
    else if (e.key === 'Escape') { e.stopPropagation(); fcClose(); }
  });

  // ---- image lightbox: click any image in the reader to open it full-screen ----
  const lb = document.createElement('div');
  lb.id = 'img-lightbox';
  lb.innerHTML = '<button class="lb-close" aria-label="Close">&times;</button><img alt=""><p class="lb-cap"></p>';
  document.body.appendChild(lb);
  const lbImg = lb.querySelector('img'), lbCap = lb.querySelector('.lb-cap');
  let lbScale = 1;
  function openLightbox(img) {
    lbImg.src = img.currentSrc || img.src;
    const fig = img.closest('figure');
    const cap = fig && fig.querySelector('figcaption');
    lbCap.textContent = cap ? cap.textContent : '';
    lbScale = 1; lbImg.style.transform = '';
    lb.classList.add('open');
    document.documentElement.style.overflow = 'hidden';
  }
  function closeLightbox() {
    lb.classList.remove('open');
    document.documentElement.style.overflow = '';
  }
  window.tempuOpenLightbox = openLightbox;
  document.addEventListener('click', e => {
    if (document.documentElement.classList.contains('editing-content') && e.target.closest('.topic-article.is-editing')) return;
    const frame = e.target.closest('.bn-editor [data-content-type=image], .bn-editor img:not(.ProseMirror-separator)');
    if (!frame) return;
    const img = frame.tagName === 'IMG' ? frame : frame.querySelector('img.bn-visual-media, img');
    if (!img) return;
    e.preventDefault(); e.stopPropagation();
    openLightbox(img);
  });
  lb.addEventListener('click', e => { if (e.target !== lbImg) closeLightbox(); });
  lbImg.addEventListener('click', e => {           // click the open image to zoom in/out
    lbScale = lbScale === 1 ? 2 : 1;
    lbImg.style.transform = lbScale === 1 ? '' : 'scale(2)';
    lbImg.style.cursor = lbScale === 1 ? 'zoom-in' : 'zoom-out';
  });
  lb.addEventListener('wheel', e => {
    if (!lb.classList.contains('open')) return;
    e.preventDefault();
    lbScale = Math.min(5, Math.max(1, lbScale * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    lbImg.style.transform = lbScale === 1 ? '' : `scale(${lbScale})`;
  }, {passive: false});
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && lb.classList.contains('open')) closeLightbox(); });

  // ================= cross-reference links + split view =================
  const isEmbed = document.documentElement.classList.contains('tempu-embed');
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

  function toast(msg) {
    let t = document.getElementById('tempu-toast');
    if (!t) { t = document.createElement('div'); t.id = 'tempu-toast'; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 3200);
  }
  window.tempuToast = toast;

  function findTarget(hash) {
    if (!hash || hash.length < 2) return null;
    const h = decodeURIComponent(hash.slice(1));
    if (h.startsWith('topic-')) return document.getElementById(h);
    const id = h.startsWith('block-') ? h.slice(6) : h;
    if (!UUID.test(id)) return null;
    return document.querySelector(`.bn-block-outer[data-id="${id}"]`) || document.getElementById('topic-' + id);
  }
  function scrollToTarget(hash, smooth = true) {
    const el = findTarget(hash);
    if (!el) return false;
    const art = el.closest('.topic-article');
    if (art && art.querySelector('.topic-body.hidden')) setCollapsed(art, false);
    // open any collapsed toggle blocks that contain the target
    let p = el.parentElement;
    while (p) {
      if (p.matches && p.matches('.bn-block') ) {
        const tw = p.querySelector(':scope > .bn-block-content .bn-toggle-wrapper[data-show-children="false"]');
        if (tw) { tw.setAttribute('data-show-children', 'true'); }
      }
      p = p.parentElement;
    }
    el.scrollIntoView({behavior: smooth ? 'smooth' : 'auto', block: el.classList.contains('topic-article') ? 'start' : 'center'});
    if (!el.classList.contains('topic-article')) {
      el.classList.remove('xref-flash'); void el.offsetWidth; el.classList.add('xref-flash');
    }
    return true;
  }
  window.tempuScrollToTarget = scrollToTarget;

  // --- split pane (left: this section, right: the linked section) ---
  function buildSplit() {
    let pane = document.getElementById('split-pane');
    if (pane) return pane;
    const root = document.querySelector('.reader-root');
    const wrap = document.createElement('div');
    wrap.id = 'split-wrap';
    root.parentNode.insertBefore(wrap, root);
    wrap.appendChild(root);
    pane = document.createElement('aside');
    pane.id = 'split-pane';
    pane.innerHTML = `
      <div class="split-head">
        <div class="min-w-0"><p class="split-kicker">Split view</p><p class="split-title truncate">Loading…</p></div>
        <div class="split-actions">
          <button data-split="swap" title="Swap primary and secondary sections" aria-label="Swap primary and secondary sections"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 3 4 4-4 4"/><path d="M20 7H4"/><path d="m8 21-4-4 4-4"/><path d="M4 17h16"/></svg></button>
          <button data-split="open" title="Open this section in a new tab and close the split view" aria-label="Open in new tab"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg></button>
          <button data-split="close" title="Close split view" aria-label="Close split view"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>
        </div>
      </div>
      <iframe class="split-frame" title="Linked section"></iframe>`;
    wrap.appendChild(pane);
    const frame = pane.querySelector('iframe');
    frame.addEventListener('load', () => {
      try {
        const d = frame.contentDocument;
        pane.querySelector('.split-title').textContent = (d.querySelector('.reader-root h1')?.textContent || d.title || '').trim();
      } catch (e) { /* ignore */ }
    });
    pane.addEventListener('click', e => {
      const b = e.target.closest('[data-split]'); if (!b) return;
      const sid = pane.dataset.section;
      if (b.dataset.split === 'close') closeSplit();
      else if (b.dataset.split === 'open') { window.open('/sections/' + sid + (pane.dataset.hash || ''), '_blank'); closeSplit(); }
      else if (b.dataset.split === 'swap') { location.href = '/sections/' + sid + '?split=' + sectionId; }
    });
    return pane;
  }
  function setUrlSplit(sid) {
    const u = new URL(location.href);
    u.searchParams.delete('splitSectionId');
    if (sid) u.searchParams.set('split', sid); else u.searchParams.delete('split');
    history.replaceState(null, '', u.pathname + (u.search ? u.search : '') + u.hash);
  }
  function openSplit(sid, hash) {
    const pane = buildSplit();
    pane.dataset.section = sid; pane.dataset.hash = hash || '';
    const frame = pane.querySelector('iframe');
    const src = '/sections/' + sid + '?embed=1' + (hash || '');
    // same section already showing -> just scroll inside it
    if (frame.dataset.section === sid && frame.contentWindow && frame.contentWindow.tempuScrollToTarget) {
      frame.contentWindow.tempuScrollToTarget(hash || '');
    } else {
      frame.dataset.section = sid;
      frame.src = src;
    }
    document.documentElement.classList.add('split-open');
    setUrlSplit(sid);
  }
  function closeSplit() {
    const wrap = document.getElementById('split-wrap'); if (!wrap) return;
    const root = wrap.querySelector('.reader-root');
    wrap.parentNode.insertBefore(root, wrap); wrap.remove();
    document.documentElement.classList.remove('split-open');
    setUrlSplit(null);
  }

  // Links that point at the live app (https://app.tempusmle.com/...) -> local
  // paths on this server; xrefs and section links become split-view links.
  const LIVE_HOST = /^(app\.|www\.)?tempusmle\.com$/i;
  const XREF_PATH = /^\/r\/(t|b)\/([0-9a-f-]{36})(?:\/([0-9a-f-]{36}))?/;
  const SECTION_PATH = /\/sections\/([0-9a-f-]{36})/;
  function localizeLink(a) {
    if (a.dataset.localized) return;
    const raw = a.getAttribute('href') || '';
    let u; try { u = new URL(raw, location.href); } catch (e) { return; }
    const live = LIVE_HOST.test(u.hostname);
    if (!live && u.origin !== location.origin) return;
    a.dataset.localized = '1';
    if (!live && a.classList.contains('tempu-xref')) return;
    const m = XREF_PATH.exec(u.pathname);
    const sm = !m && SECTION_PATH.exec(u.pathname);
    if (live || m || sm) { a.removeAttribute('target'); a.removeAttribute('rel'); a.classList.remove('tempu-extlink'); }
    if (m) {
      a.classList.add('tempu-xref');
      a.dataset.refTopic = m[2]; a.dataset.refBlock = m[3] || '';
      a.setAttribute('href', '/r/' + m[1] + '/' + m[2] + (m[3] ? '/' + m[3] : ''));
    } else if (sm) {
      a.classList.add('tempu-xref');
      a.dataset.refSection = sm[1]; a.dataset.refHash = u.hash || '';
      a.setAttribute('href', u.pathname + u.hash);
    } else if (live) {
      a.classList.add('tempu-locallink');
      a.setAttribute('href', u.pathname + u.search.replace(/([?&])workspace=[^&]*&?/, '$1').replace(/[?&]$/, '') + u.hash);
    }
  }
  function localizeLinks(root) {
    (root || document).querySelectorAll('.reader-root .bn-editor a[href]').forEach(localizeLink);
  }
  localizeLinks();
  window.tempuLocalizeLinks = localizeLinks;

  async function openXref(a) {
    let info, hash;
    if (a.dataset.refSection) {
      info = {found: true, section_id: a.dataset.refSection};
      hash = a.dataset.refHash || '';
    } else {
      const tid = a.dataset.refTopic, bid = a.dataset.refBlock;
      hash = bid ? '#block-' + bid : '#topic-' + tid;
      try { info = await fetch('/api/xref/' + tid).then(r => r.json()); } catch (e) { info = {found: false}; }
    }
    if (!info.found) {
      a.classList.add('is-missing');
      toast('“' + a.textContent.trim() + '” isn’t in your offline library yet.');
      return;
    }
    if (info.section_id === sectionId) { scrollToTarget(hash); return; }
    if (isEmbed && window.parent !== window) {
      window.parent.postMessage({type: 'tempu-split', section: info.section_id, hash}, location.origin);
      return;
    }
    openSplit(info.section_id, hash);
  }
  document.addEventListener('click', e => {
    // only links inside the topic content; nav (prev/next, breadcrumbs) navigates normally
    const link = e.target.closest('.reader-root .bn-editor a[href]');
    if (link) localizeLink(link);          // catches content inserted after load (edits, toggles)
    const a = e.target.closest('.reader-root .bn-editor a.tempu-xref');
    if (!a) return;
    if (a.closest('.topic-article.is-editing')) { e.preventDefault(); return; }
    if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return;   // new tab: server resolves /r/...
    e.preventDefault();
    openXref(a);
  });
  window.addEventListener('message', e => {
    if (e.origin !== location.origin || !e.data || e.data.type !== 'tempu-split') return;
    if (e.data.section === sectionId) scrollToTarget(e.data.hash); else openSplit(e.data.section, e.data.hash);
  });

  // initial state: ?split=<sectionId> (or the live app's ?splitSectionId=)
  {
    const q = new URLSearchParams(location.search);
    const sid = q.get('split') || q.get('splitSectionId');
    if (sid && !isEmbed && UUID.test(sid)) openSplit(sid, '');
  }
  // scroll to #topic-… / #block-… / #<blockId>
  if (location.hash) setTimeout(() => scrollToTarget(location.hash, false), 60);
})();
