// Professional rich-text topic-note editor (modal), shared across pages.
// Mirrors the live TEMP-U editor: Paragraph / H1-H3 / image / bold / italic /
// underline / highlight / text color / align / lists / indent, autosave + Saved badge.
(function () {
  const COLORS = ['#ef4444', '#f59e0b', '#eab308', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899', '#111827', '#ffffff'];
  const HILITES = ['#fef08a', '#bbf7d0', '#bfdbfe', '#fbcfe8', '#fed7aa', '#e9d5ff'];

  let modal, titleEl, savedEl, body, curTopic, saveTimer, lastHtml = '';

  function build() {
    modal = document.createElement('div');
    modal.id = 'note-modal';
    modal.className = 'fixed inset-0 z-[70] hidden items-start justify-center bg-black/50 p-4 sm:p-8';
    modal.innerHTML = `
      <div class="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border bg-card shadow-2xl">
        <div class="flex h-14 shrink-0 items-center justify-between border-b px-4">
          <h3 id="ne-title" class="truncate pr-4 text-base font-semibold">Note</h3>
          <div class="flex items-center gap-3">
            <span id="ne-saved" class="text-xs text-muted-foreground"></span>
            <button id="ne-close" class="rounded-md p-2 hover:bg-accent" aria-label="Close notes">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>
            </button>
          </div>
        </div>
        <div id="ne-toolbar" class="flex flex-wrap items-center gap-0.5 border-b px-2 py-1.5"></div>
        <div id="ne-body" class="note-editor-body min-h-[40vh] flex-1 overflow-auto px-6 py-5 outline-none" contenteditable="true" spellcheck="true"></div>
      </div>`;
    document.body.appendChild(modal);
    titleEl = modal.querySelector('#ne-title');
    savedEl = modal.querySelector('#ne-saved');
    body = modal.querySelector('#ne-body');
    buildToolbar(modal.querySelector('#ne-toolbar'));
    modal.querySelector('#ne-close').addEventListener('click', close);
    modal.addEventListener('mousedown', e => { if (e.target === modal) close(); });
    body.addEventListener('input', scheduleSave);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.classList.contains('hidden')) close(); });
  }

  function btn(html, title, onClick) {
    const b = document.createElement('button');
    b.type = 'button'; b.title = title; b.setAttribute('aria-label', title);
    b.className = 'inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground';
    b.innerHTML = html;
    b.addEventListener('mousedown', e => e.preventDefault());
    b.addEventListener('click', onClick);
    return b;
  }
  function sep() { const s = document.createElement('span'); s.className = 'mx-1 h-5 w-px bg-border'; return s; }
  function exec(cmd, val) { document.execCommand(cmd, false, val); body.focus(); scheduleSave(); }
  function block(tag) {
    // toggle: if already that block, go back to <p>
    document.execCommand('formatBlock', false, tag);
    body.focus(); scheduleSave();
  }
  const I = {
    p: 'P', h1: '<b>H1</b>', h2: '<b>H2</b>', h3: '<b>H3</b>',
    bold: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 12h8a4 4 0 0 0 0-8H6v8Z"></path><path d="M6 12h9a4 4 0 0 1 0 8H6v-8Z"></path></svg>',
    italic: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="4" x2="10" y2="4"></line><line x1="14" y1="20" x2="5" y2="20"></line><line x1="15" y1="4" x2="9" y2="20"></line></svg>',
    underline: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4v6a6 6 0 0 0 12 0V4"></path><line x1="4" y1="20" x2="20" y2="20"></line></svg>',
    highlight: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 11-6 6v3h9l3-3"></path><path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"></path></svg>',
    color: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"></circle><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"></circle><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"></circle><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"></circle><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 1.6-.7 1.6-1.6 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.6 1.6-1.6H16c3.3 0 6-2.7 6-6 0-4.9-4.5-8-10-8Z"></path></svg>',
    alignLeft: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="15" y1="12" x2="3" y2="12"></line><line x1="17" y1="18" x2="3" y2="18"></line></svg>',
    alignCenter: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="17" y1="12" x2="7" y2="12"></line><line x1="19" y1="18" x2="5" y2="18"></line></svg>',
    alignRight: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="21" y1="6" x2="3" y2="6"></line><line x1="21" y1="12" x2="9" y2="12"></line><line x1="21" y1="18" x2="7" y2="18"></line></svg>',
    ul: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line></svg>',
    ol: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="10" y1="6" x2="21" y2="6"></line><line x1="10" y1="12" x2="21" y2="12"></line><line x1="10" y1="18" x2="21" y2="18"></line><path d="M4 6h1v4"></path><path d="M4 10h2"></path><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"></path></svg>',
    outdent: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="7 8 3 12 7 16"></polyline><line x1="21" y1="6" x2="11" y2="6"></line><line x1="21" y1="12" x2="11" y2="12"></line><line x1="21" y1="18" x2="11" y2="18"></line></svg>',
    indent: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 8 7 12 3 16"></polyline><line x1="21" y1="6" x2="11" y2="6"></line><line x1="21" y1="12" x2="11" y2="12"></line><line x1="21" y1="18" x2="11" y2="18"></line></svg>',
    image: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><circle cx="9" cy="9" r="2"></circle><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"></path></svg>',
  };

  function pop(anchor, swatches, apply) {
    document.querySelectorAll('.ne-pop').forEach(p => p.remove());
    const p = document.createElement('div');
    p.className = 'ne-pop absolute z-[80] mt-1 flex flex-wrap gap-1 rounded-lg border bg-popover p-2 shadow-xl';
    p.style.width = '150px';
    swatches.forEach(c => {
      const s = document.createElement('button');
      s.type = 'button';
      s.className = 'h-6 w-6 rounded border';
      s.style.background = c;
      s.addEventListener('mousedown', e => e.preventDefault());
      s.addEventListener('click', () => { apply(c); p.remove(); });
      p.appendChild(s);
    });
    const r = anchor.getBoundingClientRect();
    p.style.left = r.left + 'px'; p.style.top = (r.bottom) + 'px'; p.style.position = 'fixed';
    document.body.appendChild(p);
    setTimeout(() => document.addEventListener('mousedown', function h(e) {
      if (!p.contains(e.target)) { p.remove(); document.removeEventListener('mousedown', h); }
    }), 0);
  }

  function buildToolbar(tb) {
    tb.appendChild(btn(I.p, 'Paragraph', () => block('P')));
    tb.appendChild(btn(I.h1, 'Heading 1', () => block('H1')));
    tb.appendChild(btn(I.h2, 'Heading 2', () => block('H2')));
    tb.appendChild(btn(I.h3, 'Heading 3', () => block('H3')));
    tb.appendChild(sep());
    const imgBtn = btn(I.image, 'Add image', () => fileInput.click());
    const fileInput = document.createElement('input');
    fileInput.type = 'file'; fileInput.accept = 'image/*'; fileInput.style.display = 'none';
    fileInput.addEventListener('change', () => {
      const f = fileInput.files[0]; if (!f) return;
      const rd = new FileReader();
      rd.onload = () => { exec('insertImage', rd.result); };
      rd.readAsDataURL(f); fileInput.value = '';
    });
    tb.appendChild(imgBtn); tb.appendChild(fileInput);
    tb.appendChild(sep());
    tb.appendChild(btn(I.bold, 'Bold', () => exec('bold')));
    tb.appendChild(btn(I.italic, 'Italic', () => exec('italic')));
    tb.appendChild(btn(I.underline, 'Underline', () => exec('underline')));
    tb.appendChild(btn(I.highlight, 'Highlight', e => pop(e.currentTarget, HILITES, c => exec('hiliteColor', c))));
    tb.appendChild(btn(I.color, 'Text color', e => pop(e.currentTarget, COLORS, c => exec('foreColor', c))));
    tb.appendChild(sep());
    tb.appendChild(btn(I.alignLeft, 'Align left', () => exec('justifyLeft')));
    tb.appendChild(btn(I.alignCenter, 'Align center', () => exec('justifyCenter')));
    tb.appendChild(btn(I.alignRight, 'Align right', () => exec('justifyRight')));
    tb.appendChild(sep());
    tb.appendChild(btn(I.ul, 'Bulleted list', () => exec('insertUnorderedList')));
    tb.appendChild(btn(I.ol, 'Numbered list', () => exec('insertOrderedList')));
    tb.appendChild(btn(I.outdent, 'Decrease list indent', () => exec('outdent')));
    tb.appendChild(btn(I.indent, 'Increase list indent', () => exec('indent')));
  }

  function scheduleSave() {
    savedEl.textContent = 'Saving…';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 600);
  }
  async function save() {
    if (!curTopic) return;
    const html = body.innerHTML;
    if (html === lastHtml) { savedEl.textContent = 'Saved'; return; }
    lastHtml = html;
    const text = body.innerText;
    try {
      await fetch('/api/notes/topic/' + curTopic, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({body_html: html, plain_text: text})});
      savedEl.textContent = 'Saved';
      document.dispatchEvent(new CustomEvent('note-saved', {detail: {topic: curTopic, hasText: !!text.trim()}}));
    } catch (e) { savedEl.textContent = 'Save failed'; }
  }

  async function open(topicId, title) {
    if (!modal) build();
    curTopic = topicId;
    titleEl.textContent = title || 'Note';
    savedEl.textContent = '';
    body.innerHTML = '<p>Loading…</p>';
    modal.classList.remove('hidden'); modal.classList.add('flex');
    const r = await fetch('/api/notes/topic/' + topicId);
    const d = await r.json();
    body.innerHTML = d.body_html || '<p><br></p>';
    lastHtml = body.innerHTML;
    body.focus();
  }
  function close() {
    clearTimeout(saveTimer); save();
    modal.classList.add('hidden'); modal.classList.remove('flex');
    curTopic = null;
  }

  window.TempuNoteEditor = {open};
})();
