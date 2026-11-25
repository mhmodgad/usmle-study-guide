// Deck create / delete / remove-card + pin chapter.
(function () {
  const post = (u, b) => fetch(u, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)});

  const nd = document.getElementById('new-deck');
  if (nd) nd.addEventListener('click', async () => {
    const name = prompt('Deck name'); if (!name) return;
    const r = await post('/api/decks', {name});
    if (r.ok) location.reload();
  });

  document.querySelectorAll('.del-deck').forEach(b => b.addEventListener('click', async e => {
    e.preventDefault();
    if (!confirm('Delete this deck?')) return;
    await fetch('/api/decks/' + b.dataset.deck, {method: 'DELETE'});
    location.reload();
  }));

  document.querySelectorAll('.del-card').forEach(b => b.addEventListener('click', async () => {
    await fetch('/api/decks/' + b.dataset.deck + '/cards/' + b.dataset.card, {method: 'DELETE'});
    location.reload();
  }));

  // add a scope (chapter/section/topic) of official cards to a deck
  document.querySelectorAll('.add-to-deck').forEach(b => b.addEventListener('click', async e => {
    e.preventDefault(); e.stopPropagation();
    const decks = await (await fetch('/api/decks')).json();
    let deckId;
    if (!decks.length) {
      const name = prompt('New deck name', 'My deck'); if (!name) return;
      deckId = (await (await post('/api/decks', {name})).json()).id;
    } else {
      const names = decks.map((d, i) => `${i + 1}. ${d.name}`).join('\n');
      const pick = prompt('Add to which deck?\n' + names + '\n\n(or type a new deck name)', '1');
      if (!pick) return;
      const idx = parseInt(pick, 10);
      if (idx >= 1 && idx <= decks.length) deckId = decks[idx - 1].id;
      else deckId = (await (await post('/api/decks', {name: pick})).json()).id;
    }
    const r = await post(`/api/decks/${deckId}/cards`, {scope: b.dataset.addScope, scope_id: b.dataset.addId});
    const d = await r.json();
    alert(`Added ${d.added} cards to the deck.`);
  }));

  // chapter pins (library page)
  document.querySelectorAll('.pin-btn').forEach(b => b.addEventListener('click', async e => {
    e.preventDefault();
    const pinned = b.dataset.pinned === '1';
    const r = await post('/api/pin', {chapter_id: b.dataset.chapter, pinned: !pinned});
    const d = await r.json();
    if (!d.ok) { alert(d.error || 'Could not pin'); return; }
    location.reload();
  }));
})();
