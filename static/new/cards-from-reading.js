/* New layout: turn what you read into flashcards.
 * Select text (or click a highlight) -> "Make card" -> a fill-in-the-blank card
 * is suggested: the sentence with your selection blanked out on the front and the
 * selection as the answer. Edit both, save: it goes to the "From reading" deck,
 * is backed up with your data and can be undone. */
(function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const H = () => window.TempuHistory;

  function blockText(node) {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    const block = el && el.closest('.bn-block-content, li, p, td, th');
    return (block ? block.innerText : '').replace(/\s+/g, ' ').trim();
  }
  function suggest(sentence, sel) {
    sel = sel.replace(/\s+/g, ' ').trim();
    if (sentence && sentence.includes(sel) && sentence.length > sel.length + 3) {
      return {front: sentence.replace(sel, '_____'), back: sel};
    }
    return {front: sel, back: ''};
  }
  function topicOf(node) {
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    const art = el && el.closest('.topic-article');
    return art ? {id: art.dataset.topicId, title: art.querySelector('.topic-title')?.textContent.trim()} : {};
  }

  function open({front, back, quote, topic}) {
    const m = document.createElement('div');
    m.className = 'th-modal';
    m.innerHTML = `<div class="th-panel" style="width:min(36rem,100%)" role="dialog" aria-label="Make a flashcard">
      <div class="th-head"><h2>Make a flashcard</h2><button class="th-x" data-close aria-label="Close">×</button></div>
      <form style="padding:1rem 1.2rem;display:grid;gap:.75rem">
        ${topic.title ? `<p class="th-muted" style="margin:0">From “${esc(topic.title)}” · saved to your <b>From reading</b> deck</p>` : ''}
        <label style="display:grid;gap:.3rem"><span class="text-sm font-medium">Front (question)</span>
          <textarea name="front" rows="3" class="th-input" style="resize:vertical">${esc(front)}</textarea></label>
        <label style="display:grid;gap:.3rem"><span class="text-sm font-medium">Back (answer)</span>
          <textarea name="back" rows="2" class="th-input" style="resize:vertical" placeholder="The answer">${esc(back)}</textarea></label>
        <p class="th-muted" style="margin:0">Tip: the blank “_____” on the front is what you'll have to recall.</p>
        <div class="th-actions" style="justify-content:flex-end"><button type="button" class="th-btn" data-close>Cancel</button>
          <button type="submit" class="th-btn primary">Save card</button></div>
      </form></div>`;
    document.body.appendChild(m);
    const close = () => m.remove();
    m.addEventListener('click', e => { if (e.target === m || e.target.closest('[data-close]')) close(); });
    m.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    const f = m.querySelector('form');
    setTimeout(() => f.back.value ? f.front.focus() : f.back.focus(), 30);
    f.addEventListener('submit', async e => {
      e.preventDefault();
      if (!f.front.value.trim() || !f.back.value.trim()) { (f.front.value.trim() ? f.back : f.front).focus(); return; }
      const r = await fetch('/api/my-cards', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({topic_id: topic.id, front: f.front.value, back: f.back.value, quote, source: 'selection'})});
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { H()?.toast(d.error || 'Could not save the card'); return; }
      close();
      H()?.toast('Card saved to “From reading”', [{label: 'Review deck', run: () => location.href = '/flashcards/review?scope=deck&id=from-reading&title=From%20reading'}]);
    });
  }

  document.getElementById('st-card')?.addEventListener('click', () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return;
    const text = sel.toString(), node = sel.getRangeAt(0).commonAncestorContainer;
    const s = suggest(blockText(node), text);
    const tb = document.getElementById('selection-toolbar');
    if (tb) { tb.classList.add('hidden'); tb.classList.remove('flex'); }
    sel.removeAllRanges();
    open({...s, quote: text.trim(), topic: topicOf(node)});
  });
  document.getElementById('st-card')?.addEventListener('mousedown', e => e.preventDefault());   // keep the selection

  let lastSpan = null;
  document.addEventListener('click', e => { const sp = e.target.closest?.('.tempu-highlight'); if (sp) lastSpan = sp; }, true);
  document.getElementById('ap-card')?.addEventListener('click', () => {
    if (!lastSpan) return;
    const id = lastSpan.dataset.annId;
    const parts = [...document.querySelectorAll(`.tempu-highlight[data-ann-id="${CSS.escape(id)}"]`)];
    const text = parts.map(p => p.textContent).join('');
    document.getElementById('ann-pop')?.classList.add('hidden');
    open({...suggest(blockText(lastSpan), text), quote: text.trim(), topic: topicOf(lastSpan)});
  });
})();
