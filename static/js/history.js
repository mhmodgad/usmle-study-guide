/* Undo / redo / version history / backup status (see tempu/history.py, tempu/backup.py)
 *
 *  - Any change that comes back from the server with a `changeset` shows a
 *    toast: "Moved 'X' to 'Y' · Undo". Editor autosaves don't (the editor has
 *    its own undo); they are in the topic's version history instead.
 *  - Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y) outside text fields undo / redo the
 *    latest change in the whole app.
 *  - The header chip shows the backup state; click it for Settings -> Backup.
 *  - TempuHistory.openTopic(id) opens a topic's version history with a
 *    comparison and "Restore this version".
 */
(function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const when = iso => {
    if (!iso) return '';
    const d = new Date(iso), now = new Date(), s = (now - d) / 1000;
    if (s < 60) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (d.toDateString() === now.toDateString()) return 'today ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    return d.toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
  };
  const origFetch = window.fetch.bind(window);
  const api = (url, body) => origFetch(url, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

  // ------------------------------------------------------------------ toast
  let toastEl, toastTimer;
  function toast(msg, actions, ms) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'th-toast';
      toastEl.setAttribute('role', 'status');
      document.body.appendChild(toastEl);
    }
    toastEl.innerHTML = `<span class="th-msg" title="${esc(msg)}">${esc(msg)}</span>`;
    (actions || []).forEach(a => {
      const b = document.createElement('button');
      b.className = 'th-btn primary'; b.textContent = a.label;
      b.onclick = () => { hideToast(); a.run(); };
      toastEl.appendChild(b);
    });
    const x = document.createElement('button');
    x.className = 'th-x'; x.setAttribute('aria-label', 'Dismiss'); x.textContent = '×'; x.onclick = hideToast;
    toastEl.appendChild(x);
    requestAnimationFrame(() => toastEl.classList.add('show'));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, ms || 10000);
  }
  function hideToast() { toastEl && toastEl.classList.remove('show'); }

  // after a reload, show what just happened
  try {
    const pending = sessionStorage.getItem('tempu-history-toast');
    if (pending) {
      sessionStorage.removeItem('tempu-history-toast');
      const p = JSON.parse(pending);
      if (!p.t || Date.now() - p.t < 8000) addEventListener('DOMContentLoaded', () => toast(p.msg, p.redo ? [{label: 'Redo', run: () => redo(p.redo)}]
        : p.undo ? [{label: 'Undo', run: () => undo(p.undo)}] : []));
    }
  } catch (e) { /* storage unavailable */ }
  function reloadWith(msg, extra) {
    try { sessionStorage.setItem('tempu-history-toast', JSON.stringify(Object.assign({msg}, extra || {}))); } catch (e) {}
    location.reload();
  }

  // ------------------------------------------------------------------ undo / redo
  async function undo(id, force) {
    const r = await api('/api/history/undo/' + encodeURIComponent(id || 'latest'), {force: !!force});
    const d = await r.json().catch(() => ({}));
    if (r.status === 409 && d.needs_confirm) {
      const ok = confirm('Some of this was changed again afterwards:\n\n• ' + d.conflicts.join('\n• ') +
        '\n\nUndo anyway? Later changes to those fields are kept.');
      if (ok) return undo(id, true);
      return;
    }
    if (!r.ok || !d.ok) { toast(d.error || 'Nothing to undo'); return; }
    const target = d.changeset && d.changeset.label ? d.changeset.label : 'Undone';
    reloadWith(target + (d.kept && d.kept.length ? ' (kept later changes)' : ''),
      {redo: id && id !== 'latest' ? id : 'latest'});
  }
  async function redo(id, force) {
    const r = await api('/api/history/redo/' + encodeURIComponent(id || 'latest'), {force: !!force});
    const d = await r.json().catch(() => ({}));
    if (r.status === 409 && d.needs_confirm) {
      if (confirm('Some of this was changed again afterwards:\n\n• ' + d.conflicts.join('\n• ') + '\n\nRedo anyway?')) return redo(id, true);
      return;
    }
    if (!r.ok || !d.ok) { toast(d.error || 'Nothing to redo'); return; }
    reloadWith(d.changeset ? d.changeset.label : 'Redone', {undo: 'latest'});
  }

  // Any response that carries a changeset gets an Undo toast (except editor autosaves).
  window.fetch = async function (input, init) {
    const resp = await origFetch(input, init);
    try {
      const url = typeof input === 'string' ? input : input.url;
      const method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
      const autosave = /\/api\/topics\/[^/]+\/content$/.test(url) && (method === 'PUT' || method === 'POST');
      if (method !== 'GET' && !autosave && /\/api\/(structure|topics)\//.test(url) &&
          (resp.headers.get('content-type') || '').includes('json')) {
        resp.clone().json().then(d => {
          if (d && d.changeset && d.changeset.id) {
            const id = d.changeset.id;
            // pages often reload right after a change: carry the toast over
            try { sessionStorage.setItem('tempu-history-toast', JSON.stringify({msg: d.changeset.label, undo: id, t: Date.now()})); } catch (e) {}
            setTimeout(() => toast(d.changeset.label, [{label: 'Undo', run: () => undo(id)}]), 50);
          }
        }).catch(() => {});
      }
    } catch (e) { /* never break the caller */ }
    return resp;
  };

  addEventListener('keydown', e => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k !== 'z' && k !== 'y') return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;   // the field's own undo
    if (document.querySelector('.ce-editing, .topic-article.is-editing')) return;            // content editor open
    e.preventDefault();
    if (k === 'y' || e.shiftKey) redo('latest'); else undo('latest');
  });

  // ------------------------------------------------------------------ backup chip
  async function refreshChip(chip) {
    try {
      const s = await (await origFetch('/api/backup/status')).json();
      chip.dataset.state = s.state;
      let label = s.text;
      if (s.state === 'ok' && s.last_ok) label = 'Backed up ' + when(s.last_ok);
      chip.querySelector('.th-label').textContent = label;
      chip.title = s.last_error ? 'Last backup failed: ' + s.last_error :
        (s.state === 'off' ? 'Cloud backup is off. Your changes are saved on this computer.' :
          'Everything is saved on this computer. ' + label + '.');
      chip.hidden = false;
      clearTimeout(chip._t);
      chip._t = setTimeout(() => refreshChip(chip), s.state === 'running' ? 3000 : 60000);
    } catch (e) { chip.hidden = true; }
  }
  addEventListener('DOMContentLoaded', () => {
    // use the app's own font for the toast/dialogs (it is set on an inner wrapper, not <body>)
    try {
      const host = document.querySelector('main, [data-app-header], .reader-root') || document.body;
      document.documentElement.style.setProperty('--th-font', getComputedStyle(host).fontFamily);
    } catch (e) {}
    const bell = document.getElementById('bell-btn');
    if (bell && !document.getElementById('th-chip')) {
      const chip = document.createElement('a');
      chip.id = 'th-chip'; chip.className = 'th-chip'; chip.href = '/settings/backup'; chip.hidden = true;
      chip.innerHTML = '<span class="th-dot"></span><span class="th-label"></span>';
      bell.parentNode.insertBefore(chip, bell);
      refreshChip(chip);
    }
    // "Version history" in the topic ⋮ menu
    const menu = document.getElementById('topic-actions-menu');
    if (menu && !menu.querySelector('[data-act="history"]')) {
      const b = document.createElement('button');
      b.dataset.act = 'history';
      b.className = 'flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent';
      b.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>Version history';
      menu.appendChild(b);
      let current = null;
      document.addEventListener('click', e => {
        const t = e.target.closest('.topic-actions-btn');
        if (t) current = t.dataset.topic;
      }, true);
      b.addEventListener('click', () => { menu.classList.add('hidden'); if (current) openTopic(current); });
    }
  });

  // ------------------------------------------------------------------ topic version history
  async function openTopic(tid) {
    const list = await (await origFetch('/api/topics/' + encodeURIComponent(tid) + '/history')).json();
    const m = document.createElement('div');
    m.className = 'th-modal';
    m.innerHTML = `<div class="th-panel" role="dialog" aria-label="Version history">
      <div class="th-head"><h2>Version history</h2><button class="th-x" data-close aria-label="Close">×</button></div>
      <div class="th-body"><div class="th-list"></div><div class="th-view"><p class="th-muted">Choose a version on the left.</p></div></div></div>`;
    document.body.appendChild(m);
    const close = () => m.remove();
    m.addEventListener('click', e => { if (e.target === m || e.target.closest('[data-close]')) close(); });
    addEventListener('keydown', function k(e) { if (e.key === 'Escape') { close(); removeEventListener('keydown', k); } });
    const listEl = m.querySelector('.th-list'), view = m.querySelector('.th-view');
    listEl.innerHTML = list.map((v, i) => `<button class="th-item" data-i="${i}">
        ${v.original ? 'Original' : esc(v.saved_at ? when(v.saved_at) : 'Saved version')}
        ${v.current ? '<span class="th-tag">current</span>' : ''}
        <small>${esc(v.original ? 'The content as it came with the library' : (v.title ? v.title : v.label || ''))}</small></button>`).join('');
    listEl.querySelectorAll('.th-item').forEach(b => b.addEventListener('click', () => show(+b.dataset.i)));
    async function show(i) {
      listEl.querySelectorAll('.th-item').forEach(b => b.classList.toggle('sel', +b.dataset.i === i));
      const v = list[i];
      view.innerHTML = '<p class="th-muted">Loading…</p>';
      const d = await (await origFetch(`/api/topics/${encodeURIComponent(tid)}/history/${v.id}`)).json();
      view.innerHTML = `<div class="th-actions">
          ${v.current ? '<span class="th-muted">This is the version you see now.</span>'
            : `<button class="th-btn primary" data-restore>Restore this version</button>`}
          <div class="th-tabs" style="margin-left:auto"><button class="th-btn on" data-tab="diff">Changes</button><button class="th-btn" data-tab="preview">Preview</button></div></div>
        <p class="th-muted">${v.current ? '' : 'Compared with the current text: <ins style="text-decoration:none">added in this version</ins>, <del>not in this version</del>.'}</p>
        <div class="th-diff">${d.diff_html || '<span class="th-muted">Same text as the current version.</span>'}</div>
        <div class="th-preview bn-editor" hidden>${d.html || ''}</div>`;
      view.querySelectorAll('[data-tab]').forEach(t => t.addEventListener('click', () => {
        view.querySelectorAll('[data-tab]').forEach(x => x.classList.toggle('on', x === t));
        view.querySelector('.th-diff').hidden = t.dataset.tab !== 'diff';
        view.querySelector('.th-preview').hidden = t.dataset.tab !== 'preview';
      }));
      const rb = view.querySelector('[data-restore]');
      if (rb) rb.addEventListener('click', async () => {
        rb.disabled = true;
        const r = await origFetch(`/api/topics/${encodeURIComponent(tid)}/history/${v.id}/restore`, {method: 'POST'});
        const dd = await r.json().catch(() => ({}));
        if (location.hash !== '#topic-' + tid) location.hash = 'topic-' + tid;
        reloadWith(dd.changeset ? dd.changeset.label : 'Restored', dd.changeset ? {undo: dd.changeset.id} : {});
      });
    }
    if (list.length) show(0);
  }

  window.TempuHistory = {undo, redo, toast, openTopic, when, esc, reloadWith};
})();
