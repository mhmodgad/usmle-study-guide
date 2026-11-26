// Flashcard review/study session: fetch cards for scope, reveal, rate (1-4 -> SRS).
(function () {
  const root = document.getElementById('review-root');
  const scope = root.dataset.scope, scopeId = root.dataset.scopeId;
  const mount = document.getElementById('card-mount');
  const revealBtn = document.getElementById('reveal-btn');
  const ratingRow = document.getElementById('rating-row');
  const progress = document.getElementById('review-progress');
  const bar = document.getElementById('review-bar');
  const stage = document.getElementById('review-stage');
  const controls = document.getElementById('review-controls');
  const doneEl = document.getElementById('review-done');
  const openWrap = document.getElementById('open-topic-wrap');
  const openLink = document.getElementById('open-topic');

  let cards = [], i = 0, revealed = false, known = 0, missed = 0, busy = false;
  // new layout only: a card answered "Again" comes back at the end of the session
  const requeueAgain = !!window.TempuRequeueAgain;

  async function load() {
    const url = '/api/cards?scope=' + encodeURIComponent(scope) + '&id=' + encodeURIComponent(scopeId);
    const r = await fetch(url);
    const d = await r.json();
    cards = d.cards || [];
    if (!cards.length) {
      mount.innerHTML = window.TempuEmptyReview ? window.TempuEmptyReview(scope)
        : '<p class="text-center text-muted-foreground">No cards here yet.</p>';
      controls.classList.add('hidden');
      return;
    }
    i = 0; known = 0; missed = 0;
    show();
  }

  function show() {
    revealed = false;
    const c = cards[i];
    mount.innerHTML = c.front_html;
    revealBtn.classList.remove('hidden');
    ratingRow.classList.add('hidden'); ratingRow.classList.remove('grid');
    openWrap.classList.add('hidden'); openWrap.classList.remove('flex');
    progress.textContent = (i + 1) + ' of ' + cards.length;
    bar.style.width = Math.round(100 * i / cards.length) + '%';
  }

  function reveal() {
    if (revealed || busy || i >= cards.length) return;        // nothing left to show
    revealed = true;
    const c = cards[i];
    mount.innerHTML = c.back_html;
    revealBtn.classList.add('hidden');
    // interval previews per rating
    const pv = c.previews || {};
    ratingRow.querySelectorAll('.rate-btn').forEach(b => {
      const s = b.querySelector('.rate-ivl');
      if (s) s.textContent = pv[b.dataset.rating] || '';
    });
    ratingRow.classList.remove('hidden'); ratingRow.classList.add('grid');
    // open source topic
    if (c.topic_href) {
      openLink.href = c.topic_href;
      openWrap.classList.remove('hidden'); openWrap.classList.add('flex');
    }
  }

  async function rate(r) {
    // one rating per card: a double click or a held key used to rate it twice
    if (busy || !revealed || i >= cards.length) return;
    busy = true; revealed = false;
    const c = cards[i];
    if (r <= 1) missed++; else known++;
    try {
      const resp = await fetch('/api/review', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({card_id: c.id, rating: r})});
      const d = await resp.json().catch(() => ({}));
      if (requeueAgain && r <= 1 && !c.requeued) {
        cards.push(Object.assign({}, c, {previews: d.previews || c.previews, requeued: true}));
      }
    } catch (e) { /* keep going offline */ }
    finally { busy = false; }
    i++;
    if (i >= cards.length) return finish();
    show();
  }

  function finish() {
    stage.classList.add('hidden'); controls.classList.add('hidden');
    doneEl.classList.remove('hidden'); doneEl.classList.add('flex');
    document.getElementById('done-known').textContent = known;
    document.getElementById('done-missed').textContent = missed;
    bar.style.width = '100%';
  }

  revealBtn.addEventListener('click', reveal);
  ratingRow.querySelectorAll('.rate-btn').forEach(b =>
    b.addEventListener('click', () => { if (revealed) rate(+b.dataset.rating); }));

  document.getElementById('shuffle-btn').addEventListener('click', () => {
    // shuffle only the cards still to come; the ones already answered stay answered
    if (busy || i >= cards.length - 1) return;
    for (let j = cards.length - 1; j > i; j--) { const k = i + Math.floor(Math.random() * (j - i + 1)); [cards[j], cards[k]] = [cards[k], cards[j]]; }
    show();
  });
  const restart = document.getElementById('restart-btn');
  if (restart) restart.addEventListener('click', () => {
    doneEl.classList.add('hidden'); doneEl.classList.remove('flex');
    stage.classList.remove('hidden'); controls.classList.remove('hidden');
    i = 0; known = 0; missed = 0; show();
  });

  const fsBtn = document.getElementById('fs-btn');
  if (fsBtn) fsBtn.addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen && document.documentElement.requestFullscreen();
  });

  document.addEventListener('keydown', e => {
    if (e.key === ' ') { e.preventDefault(); if (!revealed) reveal(); }
    else if (revealed && ['1', '2', '3', '4'].includes(e.key)) { e.preventDefault(); rate(+e.key); }
    else if (e.key === 'Escape') { window.location.href = root.dataset.back || '/flashcards'; }
  });

  load();
})();
