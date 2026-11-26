/* Study flow in the section reader:
 *  - "Complete & next" at the end of every topic
 *  - the end-of-section panel stays in step with your progress
 *  - keys: J / K next / previous topic, M mark the current topic complete,
 *          N open its note, E edit it  (press ? for the full list)
 */
(function () {
  'use strict';
  const arts = [...document.querySelectorAll('.topic-article')];
  if (!arts.length) return;
  const typing = t => t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  const editing = () => document.querySelector('.topic-article.is-editing');

  function cb(art) { return art.querySelector('.topic-complete'); }
  function setComplete(art, on) {
    const c = cb(art);
    if (!c || c.checked === on) return;
    c.checked = on;
    c.dispatchEvent(new Event('change', {bubbles: true}));   // reader.js saves it
  }
  function expand(art) {
    if (art.querySelector('.topic-body.hidden')) art.querySelector('.topic-collapse')?.click();
  }
  function goTo(art) {
    if (!art) { document.getElementById('section-end')?.scrollIntoView({behavior: 'smooth', block: 'center'}); return; }
    expand(art);
    art.scrollIntoView({behavior: 'smooth', block: 'start'});
    history.replaceState(null, '', '#topic-' + art.dataset.topicId);
  }
  function current() {
    // the topic whose header is nearest the top of the screen
    let best = arts[0], bestTop = -Infinity;
    for (const a of arts) {
      const top = a.getBoundingClientRect().top;
      if (top <= 120 && top > bestTop) { best = a; bestTop = top; }
    }
    return best;
  }

  // "Complete & next" at the bottom of each topic
  arts.forEach((art, i) => {
    const body = art.querySelector('.topic-body');
    if (!body) return;
    const bar = document.createElement('div');
    bar.className = 'topic-next-bar';
    const next = arts[i + 1];
    const label = () => cb(art)?.checked ? (next ? 'Next topic ↓' : 'Finish section ↓') : (next ? 'Complete & next topic ↓' : 'Complete & finish section ↓');
    bar.innerHTML = `<button type="button" class="tnb-btn"></button><span class="tnb-hint">${next ? 'Next: ' + (next.querySelector('.topic-title')?.textContent || '') : ''}</span>`;
    const btn = bar.querySelector('.tnb-btn');
    btn.textContent = label();
    btn.addEventListener('click', () => { setComplete(art, true); btn.textContent = label(); goTo(next); });
    cb(art)?.addEventListener('change', () => { btn.textContent = label(); refreshEnd(); });
    body.appendChild(bar);
  });

  // end-of-section panel
  const seState = document.getElementById('se-state'), seBtn = document.getElementById('se-complete');
  const title = document.getElementById('section-title')?.textContent.trim() || 'this section';
  function refreshEnd() {
    if (!seState) return;
    const total = arts.length, done = arts.filter(a => cb(a)?.checked).length;
    seState.textContent = done === total ? `You finished “${title}”` : `${done} of ${total} topics complete`;
    if (seBtn) seBtn.hidden = done === total;
  }
  seBtn?.addEventListener('click', () => { document.getElementById('section-complete')?.click(); setTimeout(refreshEnd, 300); });
  document.getElementById('section-complete')?.addEventListener('click', () => setTimeout(refreshEnd, 300));

  // keys
  addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || editing()) return;
    if (document.querySelector('.th-modal, #note-modal:not(.hidden), #img-lightbox.open')) return;
    const k = e.key.toLowerCase();
    const cur = current(), i = arts.indexOf(cur);
    if (k === 'j') { e.preventDefault(); goTo(arts[i + 1] || null); }
    else if (k === 'k') { e.preventDefault(); goTo(arts[Math.max(0, i - 1)]); }
    else if (k === 'm') { e.preventDefault(); setComplete(cur, !cb(cur)?.checked); window.TempuHistory?.toast(cb(cur)?.checked ? 'Marked complete' : 'Marked not complete'); }
    else if (k === 'n') { e.preventDefault(); cur.querySelector('.topic-note-btn')?.click(); }
    else if (k === 'e') { e.preventDefault(); cur.querySelector('.topic-edit-btn')?.click(); }
  });
  window.TempuShortcuts = (window.TempuShortcuts || []).concat([
    ['J / K', 'Next / previous topic'], ['M', 'Mark the current topic complete (again to undo)'],
    ['N', 'Open the note for the current topic'], ['E', 'Edit the current topic'],
    ['Alt + ← / →', 'Previous / next section']]);
})();
