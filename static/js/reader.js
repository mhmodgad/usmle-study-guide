// Reader: completion, topic notes (rich editor), highlights + inline notes,
// edit/delete popover, and an annotations side panel.
(function () {
  const post = (u, b) => fetch(u, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)});
  const patch = (u, b) => fetch(u, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)});
  const del = (u) => fetch(u, {method: 'DELETE'});
  const HL = {yellow: '#fef08a', green: '#bbf7d0', blue: '#bfdbfe', pink: '#fbcfe8', orange: '#fed7aa'};

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
    if (ann.kind === 'highlight') { span.style.background = HL[ann.color] || ann.color; span.style.color = '#111827'; }
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
  if (annToggle) annToggle.addEventListener('click', () => {
    const open = panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !open); panel.classList.toggle('flex', open);
  });
  document.getElementById('ann-panel-close').addEventListener('click', () => { panel.classList.add('hidden'); panel.classList.remove('flex'); });
  renderPanel();

  // scroll to hash topic
  if (location.hash.startsWith('#topic-')) {
    const el = document.getElementById(location.hash.slice(1));
    if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
})();
