// Generic settings form saver: any form[data-settings] posts its named fields
// to /api/settings. Checkboxes -> 'true'/'false'. Segmented buttons use .seg-btn
// with data-field/data-value and an aria-pressed state.
(function () {
  const form = document.querySelector('form[data-settings]');
  if (!form) return;
  const status = form.querySelector('.save-status');
  let dirty = false;
  const saveBtn = form.querySelector('[type="submit"]');

  function markDirty() { dirty = true; if (saveBtn) saveBtn.disabled = false; if (status) status.textContent = ''; }
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);

  // segmented controls
  form.querySelectorAll('.seg-btn').forEach(b => b.addEventListener('click', e => {
    e.preventDefault();
    form.querySelectorAll(`.seg-btn[data-field="${b.dataset.field}"]`).forEach(x => x.setAttribute('aria-pressed', 'false'));
    b.setAttribute('aria-pressed', 'true');
    const hidden = form.querySelector(`input[name="${b.dataset.field}"]`);
    if (hidden) hidden.value = b.dataset.value;
    markDirty();
  }));

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const body = {};
    form.querySelectorAll('input[name], select[name], textarea[name]').forEach(el => {
      if (el.type === 'checkbox') body[el.name] = el.checked ? 'true' : 'false';
      else body[el.name] = el.value;
    });
    if (body.displayName !== undefined) {
      const parts = body.displayName.trim().split(/\s+/).map(w => w[0] || '');
      body.initials = (parts.slice(0, 2).join('') || 'ST').toUpperCase();
    }
    await fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (body.theme) localStorage.setItem('tempu-theme', body.theme);
    dirty = false; if (saveBtn) saveBtn.disabled = true;
    if (status) status.textContent = 'Saved';
    if (form.dataset.reload === '1') setTimeout(() => location.reload(), 400);
  });
})();
