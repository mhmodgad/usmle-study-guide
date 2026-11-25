// Shell interactivity: theme, fullscreen, profile menu, notifications, search dialog.
(function () {
  const root = document.documentElement;
  const saved = localStorage.getItem('tempu-theme');
  if (saved) applyTheme(saved);

  function applyTheme(mode) {
    root.classList.toggle('dark', mode === 'dark');
    root.classList.toggle('light', mode === 'light');
    root.style.colorScheme = mode;
    root.setAttribute('data-mantine-color-scheme', mode);
    document.querySelectorAll('.pm-theme').forEach(b =>
      b.classList.toggle('bg-background', b.dataset.theme === mode));
  }
  function setTheme(mode) {
    applyTheme(mode);
    localStorage.setItem('tempu-theme', mode);
    fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({theme: mode})});
  }
  applyTheme(root.classList.contains('dark') ? 'dark' : 'light');

  // fullscreen
  const fs = document.getElementById('fullscreen-btn');
  if (fs) fs.addEventListener('click', () => {
    if (!document.fullscreenElement) document.documentElement.requestFullscreen?.();
    else document.exitFullscreen?.();
  });

  // ---- look (classic / modern) ----
  function applyLook(look) {
    root.classList.toggle('look-modern', look === 'modern');
    document.querySelectorAll('.pm-look').forEach(b =>
      b.classList.toggle('bg-background', b.dataset.look === look));
  }
  function setLook(look) {
    applyLook(look);
    try { localStorage.setItem('tempu-look', look); } catch (e) {}
    fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({look})}).catch(() => {});
  }
  applyLook(root.classList.contains('look-modern') ? 'modern' : 'classic');
  document.querySelectorAll('.pm-look').forEach(b => b.addEventListener('click', () => setLook(b.dataset.look)));

  // ---- sidebar toggle (expand/collapse on desktop, overlay on mobile) ----
  const mqDesktop = window.matchMedia('(min-width: 768px)');
  function setSidebar(open) {
    root.classList.toggle('sb-open', open);
    try { localStorage.setItem('tempu-sidebar', open ? '1' : '0'); } catch (e) {}
  }
  // match the live app: expanded by default on desktop, unless the user collapsed it;
  // mobile always starts closed (overlay)
  try {
    const sb = localStorage.getItem('tempu-sidebar');
    if (mqDesktop.matches && sb !== '0') root.classList.add('sb-open');
    else if (!mqDesktop.matches) root.classList.remove('sb-open');
  } catch (e) {}
  document.querySelectorAll('[aria-label="Toggle Sidebar"]').forEach(btn =>
    btn.addEventListener('click', e => {
      e.preventDefault(); e.stopPropagation();
      setSidebar(!root.classList.contains('sb-open'));
    }));
  const sbBackdrop = document.getElementById('sb-backdrop');
  if (sbBackdrop) sbBackdrop.addEventListener('click', () => setSidebar(false));
  // close the mobile overlay after navigating
  document.querySelectorAll('[data-app-sidebar] .sb-nav-item').forEach(a =>
    a.addEventListener('click', () => { if (!mqDesktop.matches) setSidebar(false); }));

  // ---- profile menu ----
  const pm = document.getElementById('profile-menu');
  const prof = document.getElementById('profile-btn');
  if (prof && pm) {
    prof.addEventListener('click', e => { e.stopPropagation(); closeAll(); pm.classList.toggle('hidden'); });
    pm.querySelectorAll('.pm-theme').forEach(b => b.addEventListener('click', () => setTheme(b.dataset.theme)));
    document.getElementById('pm-notifications').addEventListener('click', () => { pm.classList.add('hidden'); openNotif(); });
  }

  // ---- notifications ----
  const bell = document.getElementById('bell-btn');
  const panel = document.getElementById('notif-panel');
  const list = document.getElementById('notif-list');
  const countEl = document.getElementById('notif-count');
  const CAT = {
    'Access and subscriptions': 'text-tag-orange', 'Flashcards': 'text-status-info',
    'New feature': 'text-tag-purple', 'Step 2 CK': 'text-primary'};
  async function renderNotif() {
    const d = await (await fetch('/api/notifications')).json();
    countEl.textContent = d.unread ? d.unread + ' unread' : 'All read';
    list.innerHTML = d.items.map(n => `
      <div class="notif-item border-b px-4 py-3 last:border-0 ${n.status === 'unread' ? 'bg-primary/5' : ''}" data-id="${n.id}" data-url="${n.action_url || ''}">
        <div class="flex items-center gap-2 text-xs font-medium ${CAT[n.category] || 'text-muted-foreground'}">
          <span>${n.category}</span><span class="ml-auto text-muted-foreground">${n.date}</span>
        </div>
        <p class="mt-1 text-sm font-semibold">${esc(n.title)}</p>
        <p class="mt-0.5 text-xs leading-relaxed text-muted-foreground">${esc(n.body)}</p>
        <div class="mt-1 flex items-center gap-2">
          ${n.action_url ? `<a href="${n.action_url}" class="text-xs font-medium text-primary hover:underline">${n.action_label || 'Open'}</a>` : ''}
          ${n.status === 'unread' ? '<span class="ml-auto rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">Unread</span>' : ''}
        </div>
      </div>`).join('');
    list.querySelectorAll('.notif-item').forEach(el => el.addEventListener('click', async e => {
      if (e.target.tagName === 'A') { await mark(el.dataset.id); return; }
      await mark(el.dataset.id);
      if (el.dataset.url) location.href = el.dataset.url;
      else renderNotif();
    }));
  }
  async function mark(id) {
    const d = await (await fetch('/api/notifications/read', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id})})).json();
    updateBadge(d.unread);
  }
  function updateBadge(n) {
    const badge = bell?.querySelector('span[aria-hidden="true"]');
    if (badge) { badge.textContent = n || ''; badge.classList.toggle('hidden', !n); }
  }
  function openNotif() { closeAll(); panel.classList.remove('hidden'); panel.classList.add('flex'); renderNotif(); }
  if (bell) bell.addEventListener('click', e => { e.stopPropagation(); if (panel.classList.contains('hidden')) openNotif(); else closeNotif(); });
  function closeNotif() { panel.classList.add('hidden'); panel.classList.remove('flex'); }
  document.getElementById('notif-mark-all')?.addEventListener('click', async () => {
    const d = await (await fetch('/api/notifications/read', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({all: true})})).json();
    updateBadge(d.unread); renderNotif();
  });

  function closeAll() { pm?.classList.add('hidden'); closeNotif(); }
  document.addEventListener('click', e => {
    if (pm && !pm.contains(e.target) && e.target !== prof) pm.classList.add('hidden');
    if (panel && !panel.contains(e.target) && e.target !== bell && !bell?.contains(e.target)) closeNotif();
  });

  // ---- search dialog (⌘K) ----
  const dlg = document.getElementById('search-dialog');
  const sdInput = document.getElementById('sd-input');
  const sdResults = document.getElementById('sd-results');
  const headerSearch = document.getElementById('global-search');
  const RECENT_KEY = 'tempu-recent-search';
  function recents() { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); } catch (e) { return []; } }
  function pushRecent(q) { const r = recents().filter(x => x !== q); r.unshift(q); localStorage.setItem(RECENT_KEY, JSON.stringify(r.slice(0, 6))); }
  function openSearch() {
    dlg.classList.remove('hidden'); dlg.classList.add('flex');
    sdInput.value = ''; renderRecents(); setTimeout(() => sdInput.focus(), 0);
  }
  function closeSearch() { dlg.classList.add('hidden'); dlg.classList.remove('flex'); }
  function renderRecents() {
    const r = recents();
    sdResults.innerHTML = r.length
      ? '<p class="px-2 py-1 text-xs font-medium text-muted-foreground">Recent</p>' + r.map(q =>
          `<button class="sd-recent flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-accent" data-q="${esc(q)}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-muted-foreground"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>${esc(q)}</button>`).join('')
      : '<p class="px-3 py-6 text-center text-sm text-muted-foreground">Your recent queries and opened topics will appear here.</p>';
    sdResults.querySelectorAll('.sd-recent').forEach(b => b.addEventListener('click', () => { sdInput.value = b.dataset.q; runSearch(); }));
  }
  let st;
  async function runSearch() {
    const q = sdInput.value.trim();
    if (!q) { renderRecents(); return; }
    const d = await (await fetch('/api/search?q=' + encodeURIComponent(q))).json();
    sdResults.innerHTML = d.items.length
      ? d.items.map(i => `<a href="${i.href}" data-q="${esc(q)}" class="sd-hit block rounded-lg px-3 py-2 hover:bg-accent">
          <p class="text-sm font-medium">${esc(i.title)}</p>
          <p class="text-xs text-muted-foreground">${i.breadcrumb.map(esc).join(' · ')}</p></a>`).join('')
      : '<p class="px-3 py-6 text-center text-sm text-muted-foreground">No results for "' + esc(q) + '"</p>';
    sdResults.querySelectorAll('.sd-hit').forEach(a => a.addEventListener('click', () => pushRecent(a.dataset.q)));
  }
  if (sdInput) sdInput.addEventListener('input', () => { clearTimeout(st); st = setTimeout(runSearch, 180); });
  if (headerSearch) headerSearch.addEventListener('focus', e => { e.target.blur(); openSearch(); });
  if (headerSearch) headerSearch.addEventListener('click', openSearch);
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      if (document.activeElement && document.activeElement.closest && document.activeElement.closest('.topic-article.is-editing')) return; // editor uses Ctrl+K for links
      e.preventDefault(); openSearch();
    }
    if (e.key === 'Escape') { closeSearch(); closeAll(); if (!mqDesktop.matches) setSidebar(false); }
  });
  if (dlg) dlg.addEventListener('mousedown', e => { if (e.target === dlg) closeSearch(); });

  function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
})();
