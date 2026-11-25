// Page-level "Edit" mode. Nothing on library / chapter / section pages is
// editable until the user presses Edit; then names, icons and order can be
// changed (see struct-inline.js, reader-extras.js). Esc or Done leaves it.
(function () {
  const html = document.documentElement;
  const btns = [...document.querySelectorAll('[data-edit-toggle]')];
  if (!btns.length) return;
  const bar = document.createElement('div');
  bar.id = 'edit-mode-bar';
  bar.innerHTML = `<span class="emb-dot"></span><b>Edit mode</b><span class="emb-hint">${btns[0].dataset.editHint || 'Click a name to rename it, click an icon to change it, drag ⋮⋮ to reorder.'} Changes save automatically.</span><button type="button" class="emb-done">Done</button>`;
  document.body.appendChild(bar);
  function set(on) {
    html.classList.toggle('edit-mode', on);
    btns.forEach(b => { b.setAttribute('aria-pressed', on); b.querySelector('.etl') && (b.querySelector('.etl').textContent = on ? 'Done' : 'Edit'); });
    document.dispatchEvent(new CustomEvent('tempu-edit-mode', {detail: on}));
  }
  btns.forEach(b => b.addEventListener('click', e => { e.preventDefault(); set(!html.classList.contains('edit-mode')); }));
  bar.querySelector('.emb-done').addEventListener('click', () => set(false));
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape' || !html.classList.contains('edit-mode')) return;
    if (document.querySelector('.ip-overlay:not(.hidden), .ed-editing, #img-lightbox.open, html.editing-content')) return;
    set(false);
  });
  window.tempuEditMode = () => html.classList.contains('edit-mode');
})();
