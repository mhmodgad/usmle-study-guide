// Library page: search across chapters/sections/topics, status filters,
// expand/collapse (remembered), bookmarks.
(function () {
  const acc = document.getElementById('lib-acc');
  if (!acc) return;
  const libId = location.pathname.split('/')[2];
  const input = document.getElementById('lib-search');
  const count = document.getElementById('lib-count');
  const empty = document.getElementById('lib-empty');
  const chips = [...document.querySelectorAll('.lib-chip')];
  const chapters = [...acc.querySelectorAll('details.chapter-acc')];
  const index = {};
  try { JSON.parse(document.getElementById('lib-index').textContent).forEach(x => index[x.s] = x); } catch (e) { /* */ }
  const KEY = 'tempu-lib-open:' + libId;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const norm = s => (s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
  let filter = 'all';

  // remember which chapters are open
  let openSet = new Set();
  try { openSet = new Set(JSON.parse(localStorage.getItem(KEY) || '[]')); } catch (e) { /* */ }
  chapters.forEach(d => { if (openSet.has(d.dataset.chapter)) d.open = true; });
  const saveOpen = () => { try { localStorage.setItem(KEY, JSON.stringify(chapters.filter(d => d.open && !d.classList.contains('is-pinned')).map(d => d.dataset.chapter))); } catch (e) { /* */ } };
  chapters.forEach(d => d.addEventListener('toggle', () => {
    if (searching()) return;
    if (d.open) openSet.add(d.dataset.chapter); else openSet.delete(d.dataset.chapter);
    saveOpen();
  }));

  const searching = () => (input.value.trim() !== '' || filter !== 'all');

  function matchFilter(sec) {
    const d = sec.dataset;
    switch (filter) {
      case 'new': return d.status === 'new';
      case 'progress': return d.status === 'progress';
      case 'studied': return d.status === 'studied';
      case 'revise': return d.status === 'studied' && +d.revised === 0 || d.status === 'progress';
      case 'bookmarked': return d.bookmarked === '1';
      case 'notes': return +d.notes > 0;
      case 'edited': return +d.edited > 0;
      case 'empty': return d.status === 'empty';
      default: return true;
    }
  }

  function apply() {
    const q = norm(input.value.trim());
    const terms = q.split(/\s+/).filter(Boolean);
    const active = searching();
    let shownSecs = 0;
    chapters.forEach(ch => {
      const chTitle = norm(ch.dataset.title);
      const chHit = terms.length && terms.every(t => chTitle.includes(t));
      let any = 0;
      ch.querySelectorAll('.lib-sec').forEach(sec => {
        const hits = sec.querySelector('.lib-topic-hits');
        hits.innerHTML = ''; hits.classList.add('hidden');
        let ok = matchFilter(sec);
        if (ok && terms.length) {
          const secTitle = norm(sec.dataset.title);
          const secHit = terms.every(t => secTitle.includes(t));
          const ix = index[sec.dataset.section];
          const topicHits = [];
          if (ix) ix.t.forEach((title, i) => { if (terms.every(t => norm(title).includes(t))) topicHits.push([ix.ti[i], title]); });
          ok = chHit || secHit || topicHits.length > 0;
          if (topicHits.length && !secHit) {
            const href = sec.querySelector('.lib-sec-link').getAttribute('href');
            hits.innerHTML = topicHits.slice(0, 8).map(([id, t]) =>
              `<a href="${href}#topic-${id}" class="lib-topic-hit">↳ ${esc(t)}</a>`).join('') +
              (topicHits.length > 8 ? `<span class="text-xs text-muted-foreground"> +${topicHits.length - 8} more</span>` : '');
            hits.classList.remove('hidden');
          }
        }
        sec.classList.toggle('hidden', !ok);
        if (ok) { any++; shownSecs++; }
      });
      const show = active ? (any > 0 || (chHit && filter === 'all')) : !ch.classList.contains('is-pinned');
      ch.classList.toggle('hidden', !show);
      if (active) ch.open = any > 0;
    });
    if (!active) chapters.forEach(d => d.open = openSet.has(d.dataset.chapter));
    document.querySelectorAll('.lib-pinned-grid').forEach(g => g.classList.toggle('hidden', active));
    empty.classList.toggle('hidden', !active || shownSecs > 0);
    count.textContent = active ? `${shownSecs} section${shownSecs === 1 ? '' : 's'}` : '';
  }

  let t;
  input.addEventListener('input', () => { clearTimeout(t); t = setTimeout(apply, 80); });
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') { input.value = ''; apply(); input.blur(); }
    if (e.key === 'Enter') { const a = acc.querySelector('.lib-sec:not(.hidden) .lib-topic-hit, .lib-sec:not(.hidden) .lib-sec-link'); if (a) location.href = a.href; }
  });
  document.addEventListener('keydown', e => {
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !document.activeElement.isContentEditable) {
      e.preventDefault(); input.focus();
    }
  });
  chips.forEach(c => c.addEventListener('click', () => {
    filter = c.dataset.filter;
    chips.forEach(x => x.classList.toggle('is-on', x === c));
    apply();
  }));
  document.getElementById('lib-expand').addEventListener('click', () => {
    chapters.forEach(d => { if (!d.classList.contains('hidden')) d.open = true; });
    if (!searching()) { openSet = new Set(chapters.filter(d => !d.classList.contains('is-pinned')).map(d => d.dataset.chapter)); saveOpen(); }
  });
  document.getElementById('lib-collapse').addEventListener('click', () => {
    chapters.forEach(d => d.open = false);
    if (!searching()) { openSet = new Set(); saveOpen(); }
  });

  // bookmarks
  acc.addEventListener('click', async e => {
    const b = e.target.closest('.bm-btn'); if (!b) return;
    e.preventDefault();
    const on = !b.classList.contains('is-on');
    b.classList.toggle('is-on', on); b.setAttribute('aria-pressed', on);
    b.closest('.lib-sec').dataset.bookmarked = on ? '1' : '0';
    await fetch(`/api/sections/${b.dataset.section}/state`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({bookmarked: on})});
  });

  apply();
})();
