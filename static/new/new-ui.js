/* New layout only (templates_new/base.html loads it after history.js).
 *  - "?" keyboard-shortcut sheet + a ? button in the header
 *  - page shortcuts registered by other new-layout scripts via window.TempuShortcuts
 */
(function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const GLOBAL_KEYS = [['Ctrl + K', 'Search everything'], ['Ctrl + Z', 'Undo the last change'],
    ['Ctrl + Shift + Z', 'Redo'], ['?', 'Show this list'], ['Esc', 'Close a dialog / leave edit mode']];
  if (/^\/libraries\/[^/]+$/.test(location.pathname)) {
    window.TempuShortcuts = (window.TempuShortcuts || []).concat([['/', 'Find a chapter, section or topic']]);
  }
  function showShortcuts() {
    if (document.getElementById('th-keys')) return;
    const page = window.TempuShortcuts || [];
    const rows = list => list.map(([k, d]) => `<tr><td><kbd class="th-kbd">${esc(k)}</kbd></td><td>${esc(d)}</td></tr>`).join('');
    const m = document.createElement('div');
    m.className = 'th-modal'; m.id = 'th-keys';
    m.innerHTML = `<div class="th-panel" style="width:min(32rem,100%)" role="dialog" aria-label="Keyboard shortcuts">
      <div class="th-head"><h2>Keyboard shortcuts</h2><button class="th-x" data-close aria-label="Close">×</button></div>
      <div style="padding:1rem 1.2rem;overflow:auto">
        ${page.length ? `<p class="th-muted" style="margin:0 0 .4rem">On this page</p><table class="th-keys">${rows(page)}</table>` : ''}
        <p class="th-muted" style="margin:.9rem 0 .4rem">Everywhere</p><table class="th-keys">${rows(GLOBAL_KEYS)}</table>
      </div></div>`;
    document.body.appendChild(m);
    const close = () => { m.remove(); removeEventListener('keydown', onEsc); };
    const onEsc = e => { if (e.key === 'Escape') close(); };
    m.addEventListener('click', e => { if (e.target === m || e.target.closest('[data-close]')) close(); });
    addEventListener('keydown', onEsc);
  }
  addEventListener('keydown', e => {
    if (e.key !== '?' || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    e.preventDefault(); showShortcuts();
  });
  addEventListener('DOMContentLoaded', () => {
    const anchor = document.getElementById('th-chip') || document.getElementById('profile-btn');
    if (anchor && !document.querySelector('.th-help-btn')) {
      const help = document.createElement('button');
      help.type = 'button'; help.className = 'th-help-btn'; help.textContent = '?';
      help.title = 'Keyboard shortcuts (?)'; help.setAttribute('aria-label', 'Keyboard shortcuts');
      help.addEventListener('click', showShortcuts);
      anchor.parentNode.insertBefore(help, anchor.nextSibling);
    }
  });
  // header search (Ctrl+K and the search box): add "search notes & cards too" under the results
  function addSeeAll(box, input) {
    if (!box || !input) return;
    new MutationObserver(() => {
      const q = input.value.trim();
      if (!q || box.querySelector('.srch-all-link')) return;
      const a = document.createElement('a');
      a.className = 'srch-all-link';
      a.href = '/search?' + new URLSearchParams({q, kind: 'all'});
      a.textContent = 'Search your notes, highlights and flashcards too →';
      box.appendChild(a);
    }).observe(box, {childList: true});
  }
  addEventListener('DOMContentLoaded', () => {
    addSeeAll(document.getElementById('sd-results'), document.getElementById('sd-input'));
    addSeeAll(document.getElementById('search-results'), document.getElementById('global-search'));
  });

  window.TempuNewUI = {showShortcuts};
})();
