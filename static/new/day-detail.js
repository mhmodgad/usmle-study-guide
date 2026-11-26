// New layout: click a day in the consistency heatmap to see what you did that day.
(function () {
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const plural = (n, w) => `<b>${n}</b> ${w}${n === 1 ? '' : 's'}`;
  let cur = null;
  document.addEventListener('click', async e => {
    const c = e.target.closest('.hm-cell[data-day]');
    const box = document.getElementById('day-detail');
    if (!c || !c.dataset.day || !box) return;
    document.querySelectorAll('.hm-cell.on').forEach(x => x.classList.remove('on')); c.classList.add('on');
    const day = c.dataset.day; cur = day;
    box.classList.remove('hidden'); box.innerHTML = '<p class="th-muted">Loading ' + esc(day) + '…</p>';
    let d;
    try { d = await (await fetch('/api/day/' + encodeURIComponent(day))).json(); } catch (err) { box.innerHTML = '<p class="th-muted">Could not load this day.</p>'; return; }
    if (cur !== day) return;
    const when = new Date(day + 'T12:00:00').toLocaleDateString(undefined, {weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'});
    const parts = [`<div class="dd-stats"><span><b>${d.minutes}</b> min studied</span><span>${plural(d.completed.length, 'topic')} completed</span><span>${plural(d.cards_last_reviewed, 'card')} last reviewed</span><span>${plural(d.n_changes, 'edit')}</span></div>`];
    if (d.completed.length) parts.push('<h3>Completed</h3><ul>' + d.completed.map(t => `<li><a href="${esc(t.href)}">${esc(t.title)}</a> <span class="th-muted">· ${esc(t.where)}</span></li>`).join('') + '</ul>');
    if (d.changes.length) parts.push('<h3>Changes</h3><ul>' + d.changes.map(l => `<li>${esc(l)}</li>`).join('') + '</ul>' + (d.n_changes > d.changes.length ? `<a href="/settings/history">See all ${d.n_changes} in History</a>` : ''));
    if (!d.minutes && !d.completed.length && !d.n_changes && !d.cards_last_reviewed) parts.push('<p class="th-muted">Nothing recorded on this day.</p>');
    box.innerHTML = `<div class="dd-head"><h2>${esc(when)}</h2><button type="button" class="dd-x" aria-label="Close">×</button></div>` + parts.join('');
    box.querySelector('.dd-x').onclick = () => { box.classList.add('hidden'); c.classList.remove('on'); cur = null; };
  });
})();
