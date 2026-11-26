// In-place content editor for reader topics.
//
// Word-like editing of a topic's document: type anywhere, format text
// (bold/italic/underline/strike, text colour, highlight), change a block's
// type (paragraph / headings / lists / quote), colour a whole block, indent
// and outdent, drag any block (text or image) to a new place, drop or paste
// images, resize images, and edit the topic title. Every change is saved to
// the local database automatically (and with Ctrl+S); "Restore original"
// brings back the untouched document. Edits survive content rebuilds.
(function () {
  'use strict';
  const COLORS = ['default', 'gray', 'brown', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink', 'red'];
  const SWATCH = {default: 'transparent', gray: '#93908b', brown: '#b2886b', orange: '#d27b2d', yellow: '#cb9434',
                  green: '#5a9e77', blue: '#4e93e0', purple: '#ad7ec8', pink: '#df67a4', red: '#e8685d'};
  const SWATCH_BG = {default: 'transparent', gray: '#383836', brown: '#45362d', orange: '#53361f', yellow: '#504425',
                     green: '#263d30', blue: '#233850', purple: '#3c2d47', pink: '#4e2b3c', red: '#502c29'};
  const IMG_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-image custom_readerImageIcon__2ILdD" aria-hidden="true"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><circle cx="9" cy="9" r="2"></circle><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"></path></svg>';
  const ic = p => `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;

  const uid = () => (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () => Math.floor(Math.random() * 16).toString(16));
  const toast = m => (window.tempuToast ? window.tempuToast(m) : console.log(m));

  let ed = null;   // the active editing session (one topic at a time)

  // ------------------------------------------------------------ helpers
  const rootOf = art => art.querySelector('.bn-editor > .bn-block-group');
  const blockOf = n => (n && (n.nodeType === 1 ? n : n.parentElement))?.closest?.('.bn-block-outer');
  const contentOf = b => b && b.querySelector(':scope > .bn-block > .bn-block-content, :scope > .bn-block > .react-renderer > .bn-block-content');
  const inlineOf = b => { const c = contentOf(b); return c && c.querySelector('.bn-inline-content'); };
  const childGroup = (b, create) => {
    let g = b.querySelector(':scope > .bn-block > .bn-block-group');
    if (!g && create) {
      g = document.createElement('div'); g.className = 'bn-block-group'; g.dataset.nodeType = 'blockGroup';
      b.querySelector(':scope > .bn-block').appendChild(g);
    }
    return g;
  };
  const typeOf = b => contentOf(b)?.dataset.contentType || 'paragraph';
  const isTextBlock = b => !!inlineOf(b) && !['image', 'video', 'youtube', 'table'].includes(typeOf(b));

  function newBlock(type = 'paragraph', inner = '', opts = {}) {
    const id = uid();
    const outer = document.createElement('div');
    outer.className = 'bn-block-outer'; outer.dataset.nodeType = 'blockOuter'; outer.dataset.id = id;
    outer.innerHTML = `<div class="bn-block" data-node-type="blockContainer" data-id="${id}">${contentHTML(type, inner || '', opts)}</div>`;
    return outer;
  }
  function contentHTML(type, inner, opts = {}) {
    const attrs = (opts.bg && opts.bg !== 'default' ? ` data-background-color="${opts.bg}"` : '') +
                  (opts.fg && opts.fg !== 'default' ? ` data-text-color="${opts.fg}"` : '') +
                  (opts.align && opts.align !== 'left' ? ` data-text-alignment="${opts.align}"` : '');
    const body = inner || '<br class="ProseMirror-trailingBreak">';
    if (type.startsWith('heading')) {
      const lvl = +(type.split(':')[1] || 2);
      return `<div class="bn-block-content" data-content-type="heading" data-level="${lvl}"${attrs}><h${lvl} class="bn-inline-content">${body}</h${lvl}></div>`;
    }
    if (type === 'quote') return `<div class="bn-block-content" data-content-type="quote"${attrs}><blockquote class="bn-inline-content">${body}</blockquote></div>`;
    if (type === 'numberedListItem') return `<div class="bn-block-content" data-content-type="numberedListItem" data-index="1"${attrs}><p class="bn-inline-content">${body}</p></div>`;
    if (type === 'bulletListItem') return `<div class="bn-block-content" data-content-type="bulletListItem"${attrs}><p class="bn-inline-content">${body}</p></div>`;
    return `<div class="bn-block-content" data-content-type="paragraph"${attrs}><p class="bn-inline-content">${body}</p></div>`;
  }
  function imageBlock(url, width) {
    const id = uid();
    const w = width ? ` width="${width}"` : '';
    const v = width ? ` style="--reader-image-width: ${width}px;"` : '';
    const dw = width ? ` data-preview-width="${width}"` : '';
    const outer = document.createElement('div');
    outer.className = 'bn-block-outer'; outer.dataset.nodeType = 'blockOuter'; outer.dataset.id = id;
    outer.innerHTML = `<div class="bn-block" data-node-type="blockContainer" data-id="${id}"><div class="react-renderer node-image bn-react-node-view-renderer" contenteditable="false"><div class="bn-block-content" data-content-type="image" data-url="${url}"${dw} data-file-block="true" data-node-view-wrapper="" style="white-space: normal;"><div class="bn-file-block-content-wrapper custom_readerImageBlock__gqKMu"${v}><div class="bn-visual-media-wrapper custom_readerImageFrame__fggjz custom_readerImageFrameLoaded__NfvPJ" data-image-state="loaded"><img class="bn-visual-media custom_readerImage__IUONH" alt=""${w} loading="lazy" decoding="async" contenteditable="false" draggable="false" src="${url}"><div class="custom_readerImageStatus__C0xox" data-image-status="loaded">${IMG_ICON}</div></div></div></div></div></div>`;
    return outer;
  }
  function placeCaret(el, atEnd = true) {
    if (!el) return;
    const host = el.closest('[contenteditable="true"]');
    if (host && document.activeElement !== host) host.focus({preventScroll: true});
    const r = document.createRange();
    r.selectNodeContents(el); r.collapse(!atEnd);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
  }
  // moving a node in the DOM drops the browser selection; put the caret back
  function keepCaret(fn) {
    const s = getSelection();
    const saved = s.rangeCount ? [s.anchorNode, s.anchorOffset, s.focusNode, s.focusOffset] : null;
    fn();
    if (saved && saved[0] && document.contains(saved[0])) {
      try { s.setBaseAndExtent(saved[0], saved[1], saved[2], saved[3]); } catch (e) { /* ignore */ }
    }
  }
  function currentBlock() {
    const s = getSelection();
    if (s.rangeCount) {
      const b = blockOf(s.getRangeAt(0).startContainer);
      if (b && ed && ed.root.contains(b)) return b;
    }
    if (ed && ed.selectedBlock && ed.root.contains(ed.selectedBlock)) return ed.selectedBlock;
    return ed && ed.lastCaretBlock && ed.root.contains(ed.lastCaretBlock) ? ed.lastCaretBlock : null;
  }
  function renumber(root) {
    root.querySelectorAll('.bn-block-group').forEach(g => scanGroup(g));
    scanGroup(root);
    function scanGroup(g) {
      let n = 0;
      [...g.children].forEach(o => {
        const c = o.classList.contains('bn-block-outer') ? contentOf(o) : null;
        if (c && c.dataset.contentType === 'numberedListItem') { n += 1; c.dataset.index = n; } else n = 0;
      });
    }
  }
  function cleanForSave(root) {
    const clone = root.cloneNode(true);
    clone.querySelectorAll('.ce-handle, .ce-drop-line, .ce-img-tools').forEach(x => x.remove());
    clone.querySelectorAll('.ce-selected, .ce-dragging').forEach(x => x.classList.remove('ce-selected', 'ce-dragging'));
    clone.querySelectorAll('[contenteditable="true"]').forEach(x => x.removeAttribute('contenteditable'));
    clone.querySelectorAll('.tempu-highlight, .tempu-inline-anchor').forEach(x => x.replaceWith(...x.childNodes));
    // stray empty wrappers the browser sometimes leaves
    clone.querySelectorAll('span:not([class]):not([data-style-type]):empty').forEach(x => x.remove());
    clone.querySelectorAll('.bn-block-group:empty').forEach(x => x.remove());
    clone.querySelectorAll('.bn-inline-content').forEach(ic => {
      if (!ic.textContent.length && !ic.querySelector('img,br,.math')) ic.innerHTML = '<br class="ProseMirror-trailingBreak">';
    });
    return clone.innerHTML;
  }

  // ------------------------------------------------------------ toolbar
  function toolbarHTML() {
    const sw = (cls, bgmap) => COLORS.map(c =>
      `<button class="${cls}" data-color="${c}" title="${c}" style="background:${bgmap[c]}">${c === 'default' ? '×' : ''}</button>`).join('');
    return `
    <div class="ce-row">
      <select class="ce-type" title="Text style">
        <option value="paragraph">Normal text</option>
        <option value="heading:1">Heading 1</option>
        <option value="heading:2">Heading 2</option>
        <option value="heading:3">Heading 3</option>
        <option value="bulletListItem">• Bulleted list</option>
        <option value="numberedListItem">1. Numbered list</option>
        <option value="quote">Quote / callout</option>
      </select>
      <span class="ce-sep"></span>
      <button data-cmd="bold" title="Bold (Ctrl+B)"><b>B</b></button>
      <button data-cmd="italic" title="Italic (Ctrl+I)"><i>I</i></button>
      <button data-cmd="underline" title="Underline (Ctrl+U)"><u>U</u></button>
      <button data-cmd="strikeThrough" title="Strikethrough"><s>S</s></button>
      <span class="ce-pop-wrap"><button data-pop="fg" title="Text colour"><span class="ce-a">A</span></button><div class="ce-pop" data-pop-body="fg"><p>Text colour</p>${sw('ce-fg', SWATCH)}</div></span>
      <span class="ce-pop-wrap"><button data-pop="hl" title="Highlight text">${ic('<path d="m9 11-6 6v3h9l3-3"/><path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/>')}</button><div class="ce-pop" data-pop-body="hl"><p>Highlight</p>${sw('ce-hl', SWATCH)}</div></span>
      <span class="ce-pop-wrap"><button data-pop="bg" title="Block background">${ic('<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/>')}</button><div class="ce-pop" data-pop-body="bg"><p>Block colour</p>${sw('ce-bg', SWATCH_BG)}</div></span>
      <button data-act="link" title="Link (Ctrl+K) — to a web page or another topic">${ic('<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>')}</button>
      <span class="ce-pop-wrap"><button data-pop="align" title="Alignment">${ic('<path d="M21 6H3"/><path d="M15 12H3"/><path d="M17 18H3"/>')}</button><div class="ce-pop ce-menu" data-pop-body="align">
        <button data-align="left">⯇ Align left</button><button data-align="center">☰ Center</button><button data-align="right">⯈ Align right</button></div></span>
      <button data-cmd="removeFormat" title="Clear formatting">${ic('<path d="M4 7V4h16v3"/><path d="M5 20h6"/><path d="M13 4 8 20"/><path d="m15 15 5 5"/><path d="m20 15-5 5"/>')}</button>
      <span class="ce-sep"></span>
      <button data-act="outdent" title="Outdent (Shift+Tab)">${ic('<path d="M21 6H11"/><path d="M21 12H11"/><path d="M21 18H11"/><path d="m7 8-4 4 4 4"/>')}</button>
      <button data-act="indent" title="Indent (Tab)">${ic('<path d="M21 6H11"/><path d="M21 12H11"/><path d="M21 18H11"/><path d="m3 8 4 4-4 4"/>')}</button>
      <button data-act="up" title="Move block up (Alt+↑)">${ic('<path d="m18 15-6-6-6 6"/>')}</button>
      <button data-act="down" title="Move block down (Alt+↓)">${ic('<path d="m6 9 6 6 6-6"/>')}</button>
      <span class="ce-sep"></span>
      <button data-act="add" title="New block below">${ic('<path d="M5 12h14"/><path d="M12 5v14"/>')}</button>
      <span class="ce-pop-wrap"><button data-pop="insert" title="Insert table, callout, toggle, divider…">${ic('<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18M9 21V9"/>')}<small>▾</small></button>
        <div class="ce-pop ce-menu" data-pop-body="insert">
          <p>Insert below</p>
          <button data-ins="table">▦ Table…</button>
          <button data-ins="callout">💡 Callout box</button>
          <button data-ins="toggle">▸ Toggle (collapsible) list</button>
          <button data-ins="quote">❝ Quote</button>
          <button data-ins="h2">H Heading</button>
          <button data-ins="divider">― Divider line</button>
          <button data-ins="paragraph">¶ Empty paragraph</button>
        </div></span>
      <button data-act="image" title="Insert image">${ic('<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>')}</button>
      <button data-act="dup" title="Duplicate block">${ic('<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>')}</button>
      <button data-act="delete" title="Delete block">${ic('<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>')}</button>
      <span class="ce-sep"></span>
      <button data-act="undo" title="Undo (Ctrl+Z)">${ic('<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/>')}</button>
      <button data-act="redo" title="Redo (Ctrl+Y)">${ic('<path d="M21 7v6h-6"/><path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3l3 2.7"/>')}</button>
      <span class="ce-grow"></span>
      <span class="ce-status">Saved</span>
      <span class="ce-pop-wrap"><button data-pop="more" title="More">${ic('<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>')}</button>
        <div class="ce-pop ce-menu" data-pop-body="more">
          <button data-act="history">Version history…</button>
          <button data-act="restore" class="ce-danger">Restore original content</button>
        </div></span>
      <button data-act="done" class="ce-done" title="Finish editing">Done</button>
    </div>
    <input type="file" accept="image/*" multiple class="hidden ce-file">`;
  }

  // ------------------------------------------------------------ session
  async function start(art) {
    if (ed && ed.art === art) return;
    if (ed) await finish();
    const tid = art.dataset.topicId;
    const r = await fetch(`/api/topics/${tid}/content`);
    if (!r.ok) { toast('Could not load this topic for editing.'); return; }
    const data = await r.json();
    const body = art.querySelector('.topic-body');
    if (body.classList.contains('hidden')) body.classList.remove('hidden');
    const root = rootOf(art);
    root.innerHTML = data.html;                       // clean copy, without highlight marks
    const title = art.querySelector('.topic-title');
    title.textContent = data.title;

    const tb = document.createElement('div');
    tb.className = 'ce-toolbar';
    tb.innerHTML = toolbarHTML();
    art.insertBefore(tb, body);

    const handle = document.createElement('div');
    handle.className = 'ce-handle';
    handle.innerHTML = `<button class="ce-h-add" title="Add a block below">${ic('<path d="M5 12h14"/><path d="M12 5v14"/>')}</button><span class="ce-h-drag" draggable="true" title="Drag to move · click to select">⋮⋮</span>`;
    const dropLine = document.createElement('div'); dropLine.className = 'ce-drop-line';
    const imgTools = document.createElement('div'); imgTools.className = 'ce-img-tools';
    imgTools.innerHTML = `
      <button data-img="align-left" title="Align left">${ic('<path d="M3 6h18M3 12h10M3 18h14"/>')}</button>
      <button data-img="align-center" title="Center">${ic('<path d="M3 6h18M7 12h10M5 18h14"/>')}</button>
      <button data-img="align-right" title="Align right">${ic('<path d="M3 6h18M11 12h10M7 18h14"/>')}</button>
      <span class="ce-sep"></span>
      <button data-img="wrap-left" title="Text wraps on the right of the image">${ic('<rect x="3" y="5" width="8" height="8" rx="1"/><path d="M14 6h7M14 10h7M3 17h18M3 21h12"/>')}</button>
      <button data-img="wrap-right" title="Text wraps on the left of the image">${ic('<rect x="13" y="5" width="8" height="8" rx="1"/><path d="M3 6h7M3 10h7M3 17h18M3 21h12"/>')}</button>
      <span class="ce-sep"></span>
      <button data-img="crop" title="Crop (drag the edges on the image)">${ic('<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>')}</button>
      <button data-img="rot-r" title="Rotate 90°">${ic('<path d="M21 12a9 9 0 1 1-9-9c2.5 0 4.8 1 6.5 2.7L21 8"/><path d="M21 3v5h-5"/>')}</button>
      <button data-img="flip-h" title="Flip">${ic('<path d="M12 3v18"/><path d="m8 7-5 5 5 5V7z"/><path d="m16 7 5 5-5 5V7z"/>')}</button>
      <span class="ce-sep"></span>
      <button data-img="caption" title="Caption">${ic('<path d="M4 7h16M4 12h10M4 17h7"/>')}</button>
      <button data-img="replace" title="Replace image">${ic('<path d="M21 12a9 9 0 0 0-15-6.7L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 15 6.7L21 16"/><path d="M16 16h5v5"/>')}</button>
      <span class="ce-pop-wrap"><button data-img="more" title="More">${ic('<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>')}</button>
        <div class="ce-img-more">
          <button data-w="100">↔ Fit to width</button><button data-img="orig">1:1 Original size</button>
          <button data-w="50">½ Half width</button><button data-img="wrap-none">▭ No text wrap</button>
          <div class="ce-menu-sep"></div>
          <button data-img="side-prev">⬌ Beside the block above</button><button data-img="side-next">⬌ Beside the block below</button>
          <button data-img="unpair">⇣ Out of the columns</button>
          <div class="ce-menu-sep"></div>
          <button data-img="rot-l">↺ Rotate left</button><button data-img="flip-v">⇵ Flip vertically</button>
          <button data-img="alt">Alt text…</button><button data-img="dup">⧉ Duplicate</button><button data-img="full">⤢ View full size</button>
          <button data-img="up">↑ Move up</button><button data-img="down">↓ Move down</button>
        </div></span>
      <button data-img="delete" class="ce-danger" title="Delete image">${ic('<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>')}</button>
      <span class="ce-img-px">—</span>`;
    const resizer = document.createElement('div'); resizer.className = 'ce-resizer';
    resizer.innerHTML = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].map(h => `<span class="ce-rh ce-rh-${h}" data-h="${h}" title="Drag to resize"></span>`).join('') +
      '<span class="ce-rot" title="Drag to rotate"></span><span class="ce-rs-label"></span><span class="ce-rs-hint">drag to move · corners resize · ◯ rotates</span>';
    const alignZones = document.createElement('div'); alignZones.className = 'ce-align-zones';
    alignZones.innerHTML = '<span data-z="left">Left</span><span data-z="center">Center</span><span data-z="right">Right</span>';
    const ghost = document.createElement('div'); ghost.className = 'ce-ghost';
    const vline = document.createElement('div'); vline.className = 'ce-vline';
    const tblTools = document.createElement('div'); tblTools.className = 'ce-img-tools ce-tbl-tools';
    tblTools.innerHTML = `<button data-t="row-above">+ Row ↑</button><button data-t="row-below">+ Row ↓</button><button data-t="col-left">+ Col ←</button><button data-t="col-right">+ Col →</button><span class="ce-sep"></span><button data-t="header">Header row</button><button data-t="del-row" class="ce-danger">− Row</button><button data-t="del-col" class="ce-danger">− Col</button>`;
    document.body.append(handle, dropLine, imgTools, tblTools, resizer, ghost, vline, alignZones);

    root.querySelectorAll('.bn-block-content[data-float]').forEach(c => c.closest('.bn-block-outer')?.classList.add('ce-float-' + c.dataset.float));
    // callout icons are decorations: keep the caret out of them
    root.querySelectorAll('.mark-calloutIcon').forEach(x => x.setAttribute('contenteditable', 'false'));
    root.setAttribute('contenteditable', 'true');
    root.spellcheck = true;
    title.setAttribute('contenteditable', 'true');
    art.classList.add('is-editing');
    document.documentElement.classList.add('editing-content');

    ed = {art, tid, root, title, tb, handle, dropLine, imgTools, tblTools, resizer, ghost, vline, alignZones, file: tb.querySelector('.ce-file'),
          dirty: false, saving: false, checkpointed: false, undo: [], redo: [], timer: null,
          session: Math.random().toString(36).slice(2) + Date.now().toString(36),
          lastSnap: 0, selectedBlock: null, hoverBlock: null, dragBlock: null};
    snapshot(true);
    bind();
    const first = root.querySelector('.bn-inline-content');
    if (first) placeCaret(first, false);
    status('Auto-save on');
  }

  async function finish(reload = true) {
    if (!ed) return;
    // never close (and reload) with unsaved text: wait for saves in flight, save the rest
    if (!(await save())) {
      status("Couldn't save — your changes are still here. Check the app is running, then press Done again.", 'error');
      return;
    }
    if (!ed) return;
    const {art} = ed;
    teardown();
    if (reload) {
      // reload so highlights / notes re-anchor on the saved text
      location.hash = 'topic-' + art.dataset.topicId;
      location.reload();
    }
  }
  function teardown() {
    if (!ed) return;
    ed.tb.remove(); ed.handle.remove(); ed.dropLine.remove(); ed.imgTools.remove(); ed.tblTools.remove(); ed.resizer.remove(); ed.ghost.remove(); ed.vline.remove(); ed.alignZones.remove(); document.querySelector('.ce-cropper')?.remove();
    ed.root.removeAttribute('contenteditable');
    ed.title.removeAttribute('contenteditable');
    ed.art.classList.remove('is-editing');
    document.documentElement.classList.remove('editing-content');
    ed.unbind && ed.unbind();
    ed = null;
  }

  function status(t, cls) {
    if (!ed) return;
    const s = ed.tb.querySelector('.ce-status');
    s.textContent = t; s.dataset.state = cls || '';
  }
  // every edit bumps ed.rev; a save only marks the editor clean if nothing
  // changed while it was on its way (typing during a save used to be dropped)
  function markDirty() { ed.dirty = true; ed.rev = (ed.rev || 0) + 1; }
  function changed(structural) {
    if (!ed) return;
    markDirty();
    status('Unsaved changes…', 'dirty');
    snapshot(structural);
    clearTimeout(ed.timer);
    ed.timer = setTimeout(() => save(), 1500);
    if (structural) { normalizeColumns(ed.root); renumber(ed.root); positionImgTools(); }
  }
  // Resolves true when everything typed so far is saved, false when the server
  // couldn't be reached (then it retries on its own every few seconds).
  async function save() {
    const me = ed;
    if (!me) return true;
    if (me.saving) { await me.saving; return ed === me ? save() : true; }   // one save at a time
    if (!me.dirty) return true;
    clearTimeout(me.timer);
    renumber(me.root);
    const rev = me.rev || 0;
    const payload = {html: cleanForSave(me.root), title: me.title.textContent.trim(), checkpoint: !me.checkpointed, session: me.session};
    status('Saving…', 'saving');
    me.saving = (async () => {
      try {
        const r = await fetch(`/api/topics/${me.tid}/content`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
        if (!r.ok) throw new Error(r.status);
        me.checkpointed = true;
        if ((me.rev || 0) === rev) { me.dirty = false; if (ed === me) status('Saved ✓', 'saved'); }
        return true;
      } catch (e) {
        if (ed === me) status('Save failed — retrying. Your changes are kept here.', 'error');
        clearTimeout(me.retry);
        me.retry = setTimeout(() => { if (ed === me) save(); }, 3000);
        return false;
      } finally { me.saving = null; }
    })();
    const ok = await me.saving;
    if (ok && me.dirty && ed === me) return save();     // edits made while it was saving
    return ok;
  }
  // last chance when the page is closed: a "keepalive" request outlives the page
  function saveOnUnload() {
    if (!ed || !ed.dirty) return;
    const body = JSON.stringify({html: cleanForSave(ed.root), title: ed.title.textContent.trim(),
                                 checkpoint: !ed.checkpointed, session: ed.session});
    if (body.length < 60000) {
      try { fetch(`/api/topics/${ed.tid}/content`, {method: 'PUT', keepalive: true, headers: {'Content-Type': 'application/json'}, body}); } catch (e) {}
    }
  }

  // undo / redo snapshots of the whole document
  function snapshot(force) {
    if (!ed) return;
    const now = Date.now();
    if (!force && now - ed.lastSnap < 900) return;
    ed.lastSnap = now;
    const html = ed.root.innerHTML;
    if (ed.undo.length && ed.undo[ed.undo.length - 1] === html) return;
    ed.undo.push(html); if (ed.undo.length > 100) ed.undo.shift();
    ed.redo = [];
  }
  function undo() {
    if (!ed || ed.undo.length < 2) return;
    const cur = ed.root.innerHTML;
    // make sure the latest typing is in the stack before stepping back
    if (ed.undo[ed.undo.length - 1] !== cur) ed.undo.push(cur);
    ed.redo.push(ed.undo.pop());
    ed.root.innerHTML = ed.undo[ed.undo.length - 1];
    markDirty(); clearTimeout(ed.timer); ed.timer = setTimeout(() => save(), 1500); status('Unsaved changes…', 'dirty');
  }
  function redo() {
    if (!ed || !ed.redo.length) return;
    const html = ed.redo.pop(); ed.undo.push(html); ed.root.innerHTML = html;
    markDirty(); clearTimeout(ed.timer); ed.timer = setTimeout(() => save(), 1500); status('Unsaved changes…', 'dirty');
  }

  // ------------------------------------------------------------ block operations
  function setType(b, type) {
    if (!b || !isTextBlock(b)) return;
    const c = contentOf(b), ic = inlineOf(b);
    const opts = {bg: c.dataset.backgroundColor, fg: c.dataset.textColor, align: c.dataset.textAlignment};
    const tmp = document.createElement('div');
    tmp.innerHTML = contentHTML(type, ic.innerHTML, opts);
    c.replaceWith(tmp.firstElementChild);
    placeCaret(inlineOf(b));
    changed(true);
  }
  function setBlockBg(b, color) {
    const c = contentOf(b); if (!c) return;
    if (color === 'default') c.removeAttribute('data-background-color'); else c.dataset.backgroundColor = color;
    changed(true);
  }
  function wrapSelection(styleType, value) {
    const s = getSelection();
    if (!s.rangeCount || s.isCollapsed) { toast('Select some text first.'); return; }
    const r = s.getRangeAt(0);
    if (!ed.root.contains(r.commonAncestorContainer)) return;
    const frag = r.extractContents();
    // remove the same style from what was selected, so colours don't nest
    frag.querySelectorAll(`[data-style-type="${styleType}"]`).forEach(x => x.replaceWith(...x.childNodes));
    if (value === 'default') { r.insertNode(frag); }
    else {
      const span = document.createElement('span');
      span.dataset.styleType = styleType; span.dataset.value = value;
      if (styleType === 'textColor') span.dataset.textColor = value;
      span.appendChild(frag);
      r.insertNode(span);
      const nr = document.createRange(); nr.selectNodeContents(span); s.removeAllRanges(); s.addRange(nr);
    }
    changed(true);
  }
  function move(b, dir) {
    if (!b) return;
    keepCaret(() => {
      if (dir < 0) { const p = b.previousElementSibling; if (p) p.before(b); }
      else { const n = b.nextElementSibling; if (n) n.after(b); }
    });
    b.scrollIntoView({block: 'nearest'});
    changed(true);
  }
  function indent(b) {
    const prev = b && b.previousElementSibling;
    if (!prev || !prev.classList.contains('bn-block-outer')) return;
    keepCaret(() => childGroup(prev, true).appendChild(b));
    changed(true);
  }
  function outdent(b) {
    const g = b && b.parentElement;
    if (!g || g === ed.root || !g.classList.contains('bn-block-group')) return;
    const parentBlock = g.closest('.bn-block-outer');
    if (!parentBlock) return;
    // following siblings become children of the moved block (Word-like)
    const after = []; let n = b.nextElementSibling;
    while (n) { after.push(n); n = n.nextElementSibling; }
    keepCaret(() => {
      parentBlock.after(b);
      if (after.length) { const cg = childGroup(b, true); after.forEach(x => cg.appendChild(x)); }
    });
    if (!g.children.length) g.remove();
    changed(true);
  }
  function addBelow(b, type = 'paragraph') {
    const nb = newBlock(type);
    if (b) b.after(nb); else ed.root.appendChild(nb);
    placeCaret(inlineOf(nb));
    changed(true);
    return nb;
  }
  function removeBlock(b) {
    if (!b) return;
    const focusTo = b.previousElementSibling || b.nextElementSibling || b.parentElement.closest('.bn-block-outer');
    const g = b.parentElement;
    b.remove();
    if (g !== ed.root && g.classList.contains('bn-block-group') && !g.children.length) g.remove();
    if (!ed.root.querySelector('.bn-block-outer')) ed.root.appendChild(newBlock());
    if (focusTo && inlineOf(focusTo)) placeCaret(inlineOf(focusTo));
    selectBlock(null);
    changed(true);
  }
  function duplicate(b) {
    if (!b) return;
    const c = b.cloneNode(true);
    c.querySelectorAll('[data-id]').forEach(x => { /* fresh ids for the copy */ });
    const nid = uid(); c.dataset.id = nid;
    c.querySelectorAll('.bn-block-outer, .bn-block').forEach(x => x.dataset.id = uid());
    c.querySelector(':scope > .bn-block').dataset.id = nid;
    c.classList.remove('ce-selected');
    b.after(c);
    changed(true);
  }
  function selectBlock(b) {
    if (!ed) return;
    ed.root.querySelectorAll('.ce-selected').forEach(x => x.classList.remove('ce-selected'));
    ed.selectedBlock = b;
    if (b) b.classList.add('ce-selected');
    positionImgTools();
  }

  // ------------------------------------------------------------ images
  async function upload(files) {
    const urls = [];
    for (const f of files) {
      if (!f.type.startsWith('image/')) { toast(`“${f.name}” is not an image.`); continue; }
      const fd = new FormData(); fd.append('file', f, f.name || 'pasted.png');
      status('Uploading image…', 'saving');
      const r = await fetch('/api/uploads', {method: 'POST', body: fd});
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.url) { toast(j.error || 'Upload failed'); continue; }
      urls.push(j.url);
    }
    return urls;
  }
  async function insertImages(files, anchor, before) {
    const urls = await upload(files);
    let last = anchor;
    urls.forEach(u => {
      const blk = imageBlock(u);
      if (!last) ed.root.appendChild(blk);
      else if (before && last === anchor) last.before(blk);
      else last.after(blk);
      last = blk;
    });
    if (urls.length) { selectBlock(last); changed(true); }
  }
  function imgBlockOf(n) {
    const b = blockOf(n);
    return b && typeOf(b) === 'image' ? b : null;
  }
  const imgEl = b => b && b.querySelector('img.bn-visual-media, img');
  const wrapEl = b => b && b.querySelector('.bn-file-block-content-wrapper');
  function columnWidth(b) {
    const host = (b && (b.closest('.bn-block-column') || b.parentElement)) || ed.root;
    return Math.max(80, host.getBoundingClientRect().width || ed.root.getBoundingClientRect().width || 800);
  }
  function currentPx(b) { const i = imgEl(b); return Math.round(i ? i.getBoundingClientRect().width : 0); }
  function positionImgTools() {
    if (!ed) return;
    const b = ed.selectedBlock;
    const show = b && typeOf(b) === 'image' && document.body.contains(b);
    ed.imgTools.classList.toggle('show', !!show);
    ed.resizer.classList.toggle('show', !!show);
    if (!show) return;
    const r = imgEl(b).getBoundingClientRect();
    const tw = ed.imgTools.offsetWidth || 460, th = ed.imgTools.offsetHeight || 44;
    ed.imgTools.style.left = Math.max(8, Math.min(innerWidth - tw - 8, r.left + r.width / 2 - tw / 2)) + 'px';
    ed.imgTools.style.top = (r.top - th - 34 > 60 ? r.top - th - 34 : Math.min(innerHeight - th - 8, r.bottom + 14)) + 'px';
    Object.assign(ed.resizer.style, {left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px'});
    const px = Math.round(r.width), col = columnWidth(b);
    ed.resizer.querySelector('.ce-rs-label').textContent = px + ' px';
    ed.imgTools.querySelector('.ce-img-px').textContent = px + ' px';
    const c = contentOf(b);
    ed.imgTools.querySelectorAll('[data-img^="align-"],[data-img^="wrap-"]').forEach(x => x.classList.remove('is-on'));
    ed.imgTools.querySelector(`[data-img="align-${c.dataset.textAlignment || 'left'}"]`)?.classList.add('is-on');
    ed.imgTools.querySelector(`[data-img="wrap-${c.dataset.float || 'none'}"]`)?.classList.add('is-on');
    const inCol = !!b.closest('.bn-block-column');
    ed.imgTools.querySelector('[data-img="unpair"]').style.display = inCol ? '' : 'none';
    ed.imgTools.querySelector('.ce-img-px').textContent = px + ' px · ' + Math.round(px / col * 100) + '%';
  }
  function setImgPx(b, px, save = true) {
    const wrap = wrapEl(b), img = imgEl(b), content = contentOf(b);
    px = Math.round(Math.max(24, Math.min(px, columnWidth(b))));
    wrap.style.setProperty('--reader-image-width', px + 'px');
    img.setAttribute('width', px); img.style.removeProperty('width');
    content.dataset.previewWidth = px;
    const outer = b;
    if (content.dataset.float) outer.style.width = px + 'px';
    positionImgTools();
    if (save) changed(true);
  }
  function setImgWidth(b, pct) { setImgPx(b, columnWidth(b) * pct / 100); }
  function setImgAlign(b, a) {
    const c = contentOf(b);
    if (a === 'left') c.removeAttribute('data-text-alignment'); else c.dataset.textAlignment = a;
    if (c.dataset.float) setImgWrap(b, 'none', false);
    positionImgTools(); changed(true);
  }
  function setImgWrap(b, side, save = true) {
    const c = contentOf(b);
    if (side === 'none') { delete c.dataset.float; b.classList.remove('ce-float-left', 'ce-float-right'); b.style.removeProperty('width'); }
    else {
      c.dataset.float = side; c.removeAttribute('data-text-alignment');
      b.classList.remove('ce-float-left', 'ce-float-right'); b.classList.add('ce-float-' + side);
      let px = currentPx(b); const col = columnWidth(b);
      if (px > col * 0.6) px = Math.round(col * 0.45);
      setImgPx(b, px, false);
    }
    positionImgTools(); if (save) changed(true);
  }
  // ---- columns (images side by side)
  function columnList(blocks) {
    const list = document.createElement('div');
    list.className = 'bn-block-column-list'; list.dataset.nodeType = 'columnList'; list.dataset.id = uid(); list.style.display = 'flex';
    blocks.forEach(bl => {
      const col = document.createElement('div');
      col.className = 'bn-block-column'; col.dataset.nodeType = 'column'; col.dataset.id = uid(); col.dataset.width = '1'; col.style.flexGrow = '1';
      col.appendChild(bl); list.appendChild(col);
    });
    return list;
  }
  function placeBeside(target, moving, side) {     // side: 'left' | 'right' of target
    if (!target || !moving || target === moving) return;
    snapshot(true);
    const tCol = target.parentElement.classList.contains('bn-block-column') ? target.parentElement : null;
    if (moving.parentElement.classList.contains('bn-block-column') && moving.parentElement === tCol) {
      // same column: split it
    }
    if (tCol) {
      const col = document.createElement('div');
      col.className = 'bn-block-column'; col.dataset.nodeType = 'column'; col.dataset.id = uid(); col.dataset.width = '1'; col.style.flexGrow = '1';
      col.appendChild(moving);
      if (side === 'left') tCol.before(col); else tCol.after(col);
    } else {
      const ph = document.createElement('div'); target.before(ph);
      const list = columnList(side === 'left' ? [moving, target] : [target, moving]);
      ph.replaceWith(list);
    }
    [target, moving].forEach(x => { if (typeOf(x) === 'image' && contentOf(x).dataset.float) setImgWrap(x, 'none', false); });
    changed(true);
  }
  function unpair(b) {
    const list = b.closest('.bn-block-column-list'); if (!list) return;
    snapshot(true);
    list.after(b);
    changed(true);
  }
  function normalizeColumns(root) {
    root.querySelectorAll('.bn-block-column').forEach(c => { if (!c.querySelector('.bn-block-outer')) c.remove(); });
    root.querySelectorAll('.bn-block-column-list').forEach(l => {
      const cols = [...l.querySelectorAll(':scope > .bn-block-column')];
      if (!cols.length) l.remove();
      else if (cols.length === 1) l.replaceWith(...cols[0].childNodes);
    });
  }
  // ---- pixel edits (rotate / flip / crop) baked into a new image file
  function loadImage(url) {
    return new Promise((res, rej) => { const im = new Image(); im.crossOrigin = 'anonymous'; im.onload = () => res(im); im.onerror = rej; im.src = url; });
  }
  async function bake(b, draw, w, h) {
    const img = imgEl(b);
    let im;
    try { im = await loadImage(img.currentSrc || img.src); } catch (e) { toast('Could not load this image for editing.'); return; }
    const W = w(im), H = h(im);
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const cx = cv.getContext('2d');
    draw(cx, im, W, H);
    let blob;
    try { blob = await new Promise(r => cv.toBlob(r, 'image/png')); } catch (e) { blob = null; }
    if (!blob) { toast('This image comes from the internet and can’t be edited. Use “Replace” with a saved copy first.'); return; }
    const [u] = await upload([new File([blob], 'edited.png', {type: 'image/png'})]);
    if (!u) return;
    const keepPx = currentPx(b);
    img.src = u; contentOf(b).dataset.url = u;
    img.onload = () => { setImgPx(b, Math.min(keepPx, columnWidth(b)), false); positionImgTools(); };
    changed(true);
    status('Image updated', 'saved');
  }
  function transformImage(b, op) {
    if (op === 'rot-l' || op === 'rot-r') {
      return bake(b, (cx, im, W, H) => { cx.translate(W / 2, H / 2); cx.rotate((op === 'rot-r' ? 1 : -1) * Math.PI / 2); cx.drawImage(im, -im.naturalWidth / 2, -im.naturalHeight / 2); },
        im => im.naturalHeight, im => im.naturalWidth);
    }
    if (op === 'flip-h' || op === 'flip-v') {
      return bake(b, (cx, im, W, H) => { if (op === 'flip-h') { cx.translate(W, 0); cx.scale(-1, 1); } else { cx.translate(0, H); cx.scale(1, -1); } cx.drawImage(im, 0, 0); },
        im => im.naturalWidth, im => im.naturalHeight);
    }
  }
  function rotateBy(b, deg) {
    const rad = deg * Math.PI / 180, c = Math.abs(Math.cos(rad)), sn = Math.abs(Math.sin(rad));
    return bake(b, (cx, im, W, H) => { cx.translate(W / 2, H / 2); cx.rotate(rad); cx.drawImage(im, -im.naturalWidth / 2, -im.naturalHeight / 2); },
      im => Math.round(im.naturalWidth * c + im.naturalHeight * sn), im => Math.round(im.naturalWidth * sn + im.naturalHeight * c));
  }
  // crop directly on the image: drag the edges / corners, drag inside to move
  function startCrop(b) {
    const img = imgEl(b); if (!img) return;
    document.querySelector('.ce-cropper')?.remove();
    ed.cropping = b;
    ed.imgTools.classList.remove('show'); ed.resizer.classList.remove('show');
    const cr = document.createElement('div'); cr.className = 'ce-cropper';
    cr.innerHTML = '<div class="ce-cr-frame">' + ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].map(h => `<span class="ce-crh ce-crh-${h}" data-h="${h}"></span>`).join('') +
      '<span class="ce-cr-size"></span></div><div class="ce-cr-bar"><span>Drag the edges to crop</span><button data-c="reset">Reset</button><button data-c="cancel">Cancel</button><button data-c="apply" class="ce-cr-ok">✓ Crop</button></div>';
    document.body.appendChild(cr);
    const frame = cr.querySelector('.ce-cr-frame');
    let sel = {x: 0, y: 0, w: 1, h: 1};          // fractions of the image
    const place = () => {
      const r = img.getBoundingClientRect();
      Object.assign(cr.style, {left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px'});
      Object.assign(frame.style, {left: sel.x * r.width + 'px', top: sel.y * r.height + 'px', width: sel.w * r.width + 'px', height: sel.h * r.height + 'px'});
      cr.querySelector('.ce-cr-size').textContent = Math.round(sel.w * img.naturalWidth) + ' × ' + Math.round(sel.h * img.naturalHeight);
    };
    place();
    const onScroll = () => place();
    addEventListener('scroll', onScroll, true);
    frame.addEventListener('pointerdown', e => {
      e.preventDefault(); e.stopPropagation(); frame.setPointerCapture(e.pointerId);
      const h = e.target.closest('.ce-crh')?.dataset.h || 'move';
      const r = img.getBoundingClientRect(), s0 = {...sel}, x0 = e.clientX, y0 = e.clientY;
      const mv = ev => {
        const dx = (ev.clientX - x0) / r.width, dy = (ev.clientY - y0) / r.height, min = 0.03;
        let {x, y, w, h: hh} = s0;
        if (h === 'move') { x = Math.max(0, Math.min(1 - w, x + dx)); y = Math.max(0, Math.min(1 - hh, y + dy)); }
        else {
          if (h.includes('w')) { const nx = Math.max(0, Math.min(x + w - min, x + dx)); w = w + (x - nx); x = nx; }
          if (h.includes('e')) w = Math.max(min, Math.min(1 - x, w + dx));
          if (h.includes('n')) { const ny = Math.max(0, Math.min(y + hh - min, y + dy)); hh = hh + (y - ny); y = ny; }
          if (h.includes('s')) hh = Math.max(min, Math.min(1 - y, hh + dy));
        }
        sel = {x, y, w, h: hh}; place();
      };
      const up = () => { frame.removeEventListener('pointermove', mv); frame.removeEventListener('pointerup', up); };
      frame.addEventListener('pointermove', mv); frame.addEventListener('pointerup', up);
    });
    const done = async apply => {
      removeEventListener('scroll', onScroll, true); document.removeEventListener('keydown', key, true);
      cr.remove(); ed.cropping = null;
      if (apply && (sel.w < 0.995 || sel.h < 0.995)) {
        const sx = Math.round(sel.x * img.naturalWidth), sy = Math.round(sel.y * img.naturalHeight);
        const sw = Math.max(1, Math.round(sel.w * img.naturalWidth)), sh = Math.max(1, Math.round(sel.h * img.naturalHeight));
        const keep = currentPx(b) * sel.w;
        await bake(b, (cx, im) => cx.drawImage(im, sx, sy, sw, sh, 0, 0, sw, sh), () => sw, () => sh);
        setTimeout(() => { if (ed) setImgPx(b, Math.max(60, keep)); }, 400);
      }
      selectBlock(b);
    };
    const key = e => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); done(true); } if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); } };
    document.addEventListener('keydown', key, true);
    cr.querySelector('.ce-cr-bar').addEventListener('click', e => {
      const c = e.target.closest('[data-c]'); if (!c) return;
      if (c.dataset.c === 'reset') { sel = {x: 0, y: 0, w: 1, h: 1}; return place(); }
      done(c.dataset.c === 'apply');
    });
  }
  function cropImage(b) {
    const img = imgEl(b);
    const dlg = document.createElement('div'); dlg.className = 'ce-crop';
    dlg.innerHTML = `<div class="ce-crop-box"><p class="ce-crop-h">Drag on the picture to choose the area to keep</p>
      <div class="ce-crop-stage"><img alt=""><div class="ce-crop-rect"><span class="ce-crop-size"></span></div></div>
      <div class="ce-crop-foot"><button data-c="reset">Reset</button><span class="ce-grow"></span><button data-c="cancel">Cancel</button><button data-c="apply" class="ce-done">Crop</button></div></div>`;
    document.body.appendChild(dlg);
    const pic = dlg.querySelector('img'), rect = dlg.querySelector('.ce-crop-rect'), stage = dlg.querySelector('.ce-crop-stage');
    pic.src = img.currentSrc || img.src;
    let sel = null, start = null, mode = null, grab = null;
    const draw = () => {
      if (!sel) { rect.style.display = 'none'; return; }
      Object.assign(rect.style, {display: 'block', left: sel.x + 'px', top: sel.y + 'px', width: sel.w + 'px', height: sel.h + 'px'});
      const k = pic.naturalWidth / pic.clientWidth;
      rect.querySelector('.ce-crop-size').textContent = Math.round(sel.w * k) + ' × ' + Math.round(sel.h * k);
    };
    const pt = e => { const r = pic.getBoundingClientRect(); return {x: Math.max(0, Math.min(r.width, e.clientX - r.left)), y: Math.max(0, Math.min(r.height, e.clientY - r.top))}; };
    stage.addEventListener('pointerdown', e => {
      e.preventDefault(); stage.setPointerCapture(e.pointerId);
      const p = pt(e);
      if (sel && p.x > sel.x && p.x < sel.x + sel.w && p.y > sel.y && p.y < sel.y + sel.h) { mode = 'move'; grab = {dx: p.x - sel.x, dy: p.y - sel.y}; }
      else { mode = 'draw'; start = p; sel = {x: p.x, y: p.y, w: 0, h: 0}; }
      draw();
    });
    stage.addEventListener('pointermove', e => {
      if (!mode) return;
      const p = pt(e);
      if (mode === 'draw') sel = {x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y)};
      else { sel.x = Math.max(0, Math.min(pic.clientWidth - sel.w, p.x - grab.dx)); sel.y = Math.max(0, Math.min(pic.clientHeight - sel.h, p.y - grab.dy)); }
      draw();
    });
    stage.addEventListener('pointerup', () => { mode = null; if (sel && (sel.w < 4 || sel.h < 4)) sel = null; draw(); });
    dlg.addEventListener('click', async e => {
      const c = e.target.closest('[data-c]'); if (!c) { if (e.target === dlg) dlg.remove(); return; }
      if (c.dataset.c === 'cancel') return dlg.remove();
      if (c.dataset.c === 'reset') { sel = null; return draw(); }
      if (!sel) { toast('Drag on the picture to choose an area first.'); return; }
      const k = pic.naturalWidth / pic.clientWidth;
      const sx = Math.round(sel.x * k), sy = Math.round(sel.y * k), sw = Math.round(sel.w * k), sh = Math.round(sel.h * k);
      dlg.remove();
      await bake(b, (cx, im) => cx.drawImage(im, sx, sy, sw, sh, 0, 0, sw, sh), () => sw, () => sh);
    });
  }

  function setCaption(b) {
    const content = contentOf(b);
    const fig = b.querySelector('figure, .bn-file-block-content-wrapper');
    let cap = b.querySelector('figcaption');
    const val = prompt('Image caption (leave empty to remove):', cap ? cap.textContent : '');
    if (val === null) return;
    if (!val.trim()) { if (cap) cap.remove(); content.removeAttribute('data-caption'); }
    else {
      if (!cap) { cap = document.createElement('figcaption'); cap.className = 'bn-file-caption'; fig.appendChild(cap); }
      cap.textContent = val.trim(); content.dataset.caption = val.trim();
    }
    changed(true);
  }

  // ------------------------------------------------------------ rich paste
  const KEEP_INLINE = {B: 'strong', STRONG: 'strong', I: 'em', EM: 'em', U: 'u', S: 's', STRIKE: 's', DEL: 's', SUB: 'sub', SUP: 'sup', CODE: 'code', A: 'a', BR: 'br'};
  function cleanInline(node) {
    let out = '';
    node.childNodes.forEach(n => {
      if (n.nodeType === 3) { out += n.textContent.replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c])); return; }
      if (n.nodeType !== 1) return;
      const t = KEEP_INLINE[n.tagName];
      const st = n.getAttribute('style') || '';
      let inner = cleanInline(n);
      if (/font-weight:\s*(bold|[6-9]00)/i.test(st) && !t) inner = `<strong>${inner}</strong>`;
      if (/font-style:\s*italic/i.test(st) && !t) inner = `<em>${inner}</em>`;
      if (t === 'br') { out += '<br>'; return; }
      if (t === 'a') {
        const href = n.getAttribute('href') || '';
        if (/^(https?:|mailto:|\/)/i.test(href)) out += `<a class="tempu-extlink" href="${href.replace(/"/g, '&quot;')}" target="_blank" rel="noopener noreferrer">${inner}</a>`;
        else out += inner;
        return;
      }
      out += t ? `<${t}>${inner}</${t}>` : inner;
    });
    return out;
  }
  function htmlToBlocks(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('script,style,meta,link,title,head').forEach(x => x.remove());
    const out = [];
    const BLOCK = /^(P|DIV|H1|H2|H3|H4|H5|H6|LI|BLOCKQUOTE|PRE|TR|SECTION|ARTICLE|HEADER|FOOTER|FIGURE)$/;
    function walk(el, listType) {
      [...el.childNodes].forEach(n => {
        if (n.nodeType === 3) { if (n.textContent.trim()) out.push({type: 'paragraph', html: cleanInline({childNodes: [n]})}); return; }
        if (n.nodeType !== 1) return;
        const tag = n.tagName;
        if (tag === 'IMG' && n.src && /^(https?:|data:image|\/)/.test(n.getAttribute('src') || '')) { out.push({type: 'image', src: n.getAttribute('src')}); return; }
        if (tag === 'UL' || tag === 'OL') { walk(n, tag === 'OL' ? 'numberedListItem' : 'bulletListItem'); return; }
        if (tag === 'TABLE') { n.querySelectorAll('tr').forEach(tr => out.push({type: 'paragraph', html: [...tr.children].map(c => cleanInline(c)).join(' · ')})); return; }
        if (BLOCK.test(tag)) {
          const hasBlocks = [...n.children].some(c => BLOCK.test(c.tagName) || c.tagName === 'UL' || c.tagName === 'OL' || c.tagName === 'TABLE' || c.tagName === 'IMG');
          if (hasBlocks && tag !== 'LI') { walk(n, listType); return; }
          const type = /^H[1-3]$/.test(tag) ? 'heading:' + tag[1] : /^H[4-6]$/.test(tag) ? 'heading:3'
            : tag === 'LI' ? (listType || 'bulletListItem') : tag === 'BLOCKQUOTE' ? 'quote' : 'paragraph';
          const h = cleanInline(n).trim();
          if (h) out.push({type, html: h});
          if (tag === 'LI') [...n.children].filter(c => c.tagName === 'UL' || c.tagName === 'OL').forEach(c => walk(c, c.tagName === 'OL' ? 'numberedListItem' : 'bulletListItem'));
          return;
        }
        const h = cleanInline({childNodes: [n]}).trim();
        if (h) out.push({type: 'paragraph', html: h});
      });
    }
    walk(doc.body, null);
    return out;
  }

  // ------------------------------------------------------------ alignment / insert
  function setAlign(b, a) {
    const c = contentOf(b); if (!c) return;
    if (a === 'left') c.removeAttribute('data-text-alignment'); else c.dataset.textAlignment = a;
    changed(true);
  }
  const CALLOUT_ICONS = ['light', 'warning', 'key', 'pin', 'siren', 'brain', 'pill', 'doctor', 'question-mark', 'microscope', 'alarm', 'clue', 'lab-coat', 'loud-speaker', 'no-entry', 'paperclip', 'puzzle', 'versus', 'giftbox'];
  function calloutIcon(name) {
    return `<span class="react-renderer mark-calloutIcon" contenteditable="false"><span class="callout-icon-marker" data-icon="${name}" style="display: inline-block; width: 0px; height: 0px;"><span class="callout-icon-image" style="width: 20px; height: 20px; position: absolute; left: 13px; top: 21.75px; user-select: none; background-image: url(&quot;/editor/quoteIcons/${name}.webp?v=1&quot;); background-size: contain; background-repeat: no-repeat; background-position: center center;"></span><span data-mark-view-content=""><span>​</span></span></span></span>`;
  }
  function tableBlock(rows, cols) {
    const id = uid();
    const outer = document.createElement('div');
    outer.className = 'bn-block-outer'; outer.dataset.nodeType = 'blockOuter'; outer.dataset.id = id;
    const cell = (tag) => `<${tag} colspan="1" rowspan="1"><p><br class="ProseMirror-trailingBreak"></p></${tag}>`;
    const trs = [...Array(rows)].map((_, r) => `<tr>${[...Array(cols)].map(() => cell(r === 0 ? 'th' : 'td')).join('')}</tr>`).join('');
    outer.innerHTML = `<div class="bn-block" data-node-type="blockContainer" data-id="${id}"><div class="bn-block-content" data-content-type="table"><div class="tableWrapper"><div class="tableWrapper-inner"><table style="--default-cell-min-width: 120px; min-width: ${120 * cols}px;"><colgroup>${'<col>'.repeat(cols)}</colgroup><tbody>${trs}</tbody></table></div><div class="table-widgets-container" style="position: relative;"></div></div></div></div>`;
    return outer;
  }
  function insertBlock(kind, b) {
    let nb;
    if (kind === 'table') {
      const v = prompt('Table size (rows × columns):', '3 x 3'); if (!v) return;
      const m = v.match(/(\d+)\D+(\d+)/); const r = Math.min(50, +(m ? m[1] : 3)), c = Math.min(12, +(m ? m[2] : 3));
      nb = tableBlock(Math.max(1, r), Math.max(1, c));
    } else if (kind === 'callout') {
      const pick = prompt('Callout icon — ' + CALLOUT_ICONS.join(', '), 'light'); if (pick === null) return;
      const icon = CALLOUT_ICONS.includes((pick || '').trim()) ? pick.trim() : 'light';
      nb = newBlock('quote', calloutIcon(icon) + 'Write the callout text…', {bg: 'yellow'});
    } else if (kind === 'toggle') {
      nb = newBlock('paragraph');
      const c = contentOf(nb);
      const tmp = document.createElement('div');
      tmp.innerHTML = `<div class="bn-block-content" data-content-type="toggleListItem"><div><div class="bn-toggle-wrapper" data-show-children="true"><button class="bn-toggle-button" type="button"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="CURRENTCOLOR"><path d="M320-200v-560l440 280-440 280Z"></path></svg></button><p class="bn-inline-content">Toggle title</p></div></div></div>`;
      c.replaceWith(tmp.firstElementChild);
      childGroup(nb, true).appendChild(newBlock('paragraph', 'Hidden content — click the arrow to show or hide it.'));
    } else if (kind === 'divider') {
      const id = uid(); nb = document.createElement('div');
      nb.className = 'bn-block-outer'; nb.dataset.nodeType = 'blockOuter'; nb.dataset.id = id;
      nb.innerHTML = `<div class="bn-block" data-node-type="blockContainer" data-id="${id}"><div class="bn-block-content" data-content-type="divider" contenteditable="false"><hr></div></div>`;
    } else if (kind === 'quote') nb = newBlock('quote');
    else if (kind === 'h2') nb = newBlock('heading:2');
    else nb = newBlock('paragraph');
    if (b) b.after(nb); else ed.root.appendChild(nb);
    const target = nb.querySelector('th p, .bn-inline-content');
    if (target) placeCaret(target, true);
    changed(true);
  }

  // table row/column operations (shown while the caret is in a table)
  function tableOp(cell, op) {
    const table = cell.closest('table'), tr = cell.parentElement;
    const ci = [...tr.children].indexOf(cell);
    const blank = tag => { const x = document.createElement(tag); x.setAttribute('colspan', '1'); x.setAttribute('rowspan', '1'); x.innerHTML = '<p><br class="ProseMirror-trailingBreak"></p>'; return x; };
    if (op === 'row-below' || op === 'row-above') {
      const nr = document.createElement('tr');
      [...tr.children].forEach(() => nr.appendChild(blank('td')));
      if (op === 'row-below') tr.after(nr); else tr.before(nr);
    } else if (op === 'col-right' || op === 'col-left') {
      table.querySelectorAll('tr').forEach((r, ri) => {
        const ref = r.children[Math.min(ci, r.children.length - 1)];
        const n = blank(r.children[0] && r.children[0].tagName === 'TH' && ri === 0 ? 'th' : 'td');
        if (op === 'col-right') ref.after(n); else ref.before(n);
      });
      table.querySelector('colgroup')?.appendChild(document.createElement('col'));
    } else if (op === 'del-row') {
      if (table.querySelectorAll('tr').length > 1) tr.remove();
    } else if (op === 'del-col') {
      if (tr.children.length > 1) {
        table.querySelectorAll('tr').forEach(r => r.children[ci] && r.children[ci].remove());
        table.querySelector('colgroup col')?.remove();
      }
    } else if (op === 'header') {
      const first = table.querySelector('tr');
      [...first.children].forEach(c => {
        const n = document.createElement(c.tagName === 'TH' ? 'td' : 'th');
        [...c.attributes].forEach(a => n.setAttribute(a.name, a.value)); n.innerHTML = c.innerHTML; c.replaceWith(n);
      });
    }
    const cols = table.querySelector('tr')?.children.length || 1;
    table.style.minWidth = (120 * cols) + 'px';
    changed(true);
  }

  // ------------------------------------------------------------ links
  let topicIndex = null;
  async function loadTopicIndex() {
    if (topicIndex) return topicIndex;
    const lib = document.querySelector('.reader-root')?.dataset.libraryId;
    if (!lib) return (topicIndex = []);
    const tree = await fetch('/api/structure/tree/' + lib).then(r => r.json()).catch(() => []);
    topicIndex = [];
    tree.forEach(c => c.sections.forEach(sct => sct.topics.forEach(t => topicIndex.push({id: t.id, title: t.title, where: sct.title + ' · ' + c.title}))));
    return topicIndex;
  }
  function openLinkDialog() {
    if (!ed) return;
    const s = getSelection();
    if (!s.rangeCount || !ed.root.contains(s.getRangeAt(0).commonAncestorContainer)) { toast('Select the text to link first.'); return; }
    const range = s.getRangeAt(0).cloneRange();
    const existing = (range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement).closest('a');
    let dlg = document.getElementById('ce-link-dlg');
    if (!dlg) {
      dlg = document.createElement('div'); dlg.id = 'ce-link-dlg';
      dlg.innerHTML = `<div class="ce-link-box">
        <p class="ce-link-h">Link to a topic in this app, or paste a web address</p>
        <input class="ce-link-q" type="text" placeholder="Search topics… or https://…">
        <div class="ce-link-list"></div>
        <div class="ce-link-foot"><button data-l="remove" class="ce-danger">Remove link</button><span class="ce-grow"></span><button data-l="cancel">Cancel</button><button data-l="url" class="ce-done">Link to URL</button></div></div>`;
      document.body.appendChild(dlg);
    }
    dlg.classList.add('open');
    const q = dlg.querySelector('.ce-link-q'), list = dlg.querySelector('.ce-link-list');
    q.value = existing ? (existing.getAttribute('href') || '') : '';
    dlg.querySelector('[data-l=remove]').style.display = existing ? '' : 'none';
    const draw = async () => {
      const idx = await loadTopicIndex();
      const v = q.value.trim().toLowerCase();
      const hits = !v || /^https?:|^\//.test(v) ? [] : idx.filter(t => t.title.toLowerCase().includes(v)).slice(0, 40);
      list.innerHTML = hits.map(t => `<button data-t="${t.id}"><span>${t.title.replace(/</g, '&lt;')}</span><small>${t.where.replace(/</g, '&lt;')}</small></button>`).join('')
        || `<p class="ce-link-tip">${v ? 'No topic matches — press “Link to URL” for a web link.' : 'Type to search the library’s topics.'}</p>`;
    };
    q.oninput = draw; draw(); setTimeout(() => q.focus(), 0);
    const close = () => { dlg.classList.remove('open'); dlg.onclick = null; q.onkeydown = null; };
    const apply = (href, isTopic, topicId) => {
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
      if (existing) existing.replaceWith(...existing.childNodes);
      const a = document.createElement('a');
      if (isTopic) { a.className = 'tempu-xref'; a.href = '/r/t/' + topicId; a.dataset.refTopic = topicId; a.dataset.refBlock = ''; }
      else { a.className = 'tempu-extlink'; a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
      const r = sel.getRangeAt(0);
      if (r.collapsed) a.textContent = isTopic ? (topicIndex.find(t => t.id === topicId)?.title || 'link') : href;
      else a.appendChild(r.extractContents());
      r.insertNode(a);
      changed(true); close();
    };
    dlg.onclick = e => {
      if (e.target === dlg) return close();
      const t = e.target.closest('[data-t]'); if (t) return apply(null, true, t.dataset.t);
      const l = e.target.closest('[data-l]'); if (!l) return;
      if (l.dataset.l === 'cancel') return close();
      if (l.dataset.l === 'remove') { if (existing) { existing.replaceWith(...existing.childNodes); changed(true); } return close(); }
      if (l.dataset.l === 'url') {
        let v = q.value.trim(); if (!v) return;
        if (!/^(https?:|mailto:|\/)/i.test(v)) v = 'https://' + v;
        apply(v, false);
      }
    };
    q.onkeydown = e => {
      if (e.key === 'Escape') close();
      if (e.key === 'Enter') { e.preventDefault(); const first = list.querySelector('[data-t]'); if (first && !/^https?:|^\//.test(q.value.trim())) apply(null, true, first.dataset.t); else dlg.querySelector('[data-l=url]').click(); }
    };
  }

  // ------------------------------------------------------------ events
  function bind() {
    const {root, tb, handle, dropLine, imgTools, title} = ed;
    const offs = [];
    const on = (el, ev, fn, opt) => { el.addEventListener(ev, fn, opt); offs.push(() => el.removeEventListener(ev, fn, opt)); };
    ed.unbind = () => offs.forEach(f => f());

    // keep the selection when clicking toolbar buttons
    on(tb, 'mousedown', e => { if (e.target.closest('button') && !e.target.closest('select')) e.preventDefault(); });
    on(imgTools, 'mousedown', e => { if (!e.target.closest('input')) e.preventDefault(); });

    on(tb, 'click', e => {
      const btn = e.target.closest('button'); if (!btn) return;
      const b = currentBlock();
      if (btn.dataset.pop) {
        const body = tb.querySelector(`[data-pop-body="${btn.dataset.pop}"]`);
        const open = body.classList.contains('open');
        tb.querySelectorAll('.ce-pop.open').forEach(p => p.classList.remove('open'));
        if (!open) body.classList.add('open');
        return;
      }
      tb.querySelectorAll('.ce-pop.open').forEach(p => p.classList.remove('open'));
      if (btn.dataset.cmd) {
        document.execCommand(btn.dataset.cmd, false, null);
        if (btn.dataset.cmd === 'removeFormat') {
          const s = getSelection();
          if (s.rangeCount && !s.isCollapsed) {
            const r = s.getRangeAt(0); const frag = r.extractContents();
            frag.querySelectorAll('[data-style-type],strong,b,em,i,u,s,strike').forEach(x => x.replaceWith(...x.childNodes));
            r.insertNode(frag);
          }
        }
        changed(true); return;
      }
      if (btn.dataset.align) { if (b) setAlign(b, btn.dataset.align); else toast('Click inside a block first.'); return; }
      if (btn.dataset.ins) return insertBlock(btn.dataset.ins, b);
      if (btn.classList.contains('ce-fg')) return wrapSelection('textColor', btn.dataset.color);
      if (btn.classList.contains('ce-hl')) return wrapSelection('backgroundColor', btn.dataset.color);
      if (btn.classList.contains('ce-bg')) { if (b) setBlockBg(b, btn.dataset.color); else toast('Click inside a block first.'); return; }
      const act = btn.dataset.act;
      if (act === 'done') return finish();
      if (act === 'undo') return undo();
      if (act === 'redo') return redo();
      if (act === 'image') { ed.insertAfter = b; ed.file.click(); return; }
      if (act === 'link') return openLinkDialog();
      if (act === 'add') return addBelow(b);
      if (act === 'restore') return restoreOriginal();
      if (act === 'history') return showHistory();
      if (!b) { toast('Click inside a block first.'); return; }
      if (act === 'delete') return removeBlock(b);
      if (act === 'dup') return duplicate(b);
      if (act === 'up') return move(b, -1);
      if (act === 'down') return move(b, 1);
      if (act === 'indent') return indent(b);
      if (act === 'outdent') return outdent(b);
    });
    on(tb.querySelector('.ce-type'), 'change', e => {
      const b = ed.lastCaretBlock && ed.root.contains(ed.lastCaretBlock) ? ed.lastCaretBlock : currentBlock();
      if (b) setType(b, e.target.value); else toast('Click inside a block first.');
    });
    on(ed.file, 'change', async () => {
      const files = [...ed.file.files]; ed.file.value = '';
      if (files.length) await insertImages(files, ed.insertAfter || null, false);
    });

    on(ed.tblTools, 'mousedown', e => e.preventDefault());
    on(ed.tblTools, 'click', e => { const b = e.target.closest('[data-t]'); if (b && ed.cell) tableOp(ed.cell, b.dataset.t); });
    // reflect the caret's block type in the style picker
    on(document, 'selectionchange', () => {
      if (!ed) return;
      const s = getSelection(); if (!s.rangeCount) return;
      const an = s.anchorNode && (s.anchorNode.nodeType === 1 ? s.anchorNode : s.anchorNode.parentElement);
      const cell = an && an.closest && an.closest('td,th');
      if (cell && root.contains(cell)) {
        ed.cell = cell;
        const r = cell.closest('table').getBoundingClientRect();
        ed.tblTools.style.left = Math.max(8, r.left) + 'px'; ed.tblTools.style.top = Math.max(60, r.top - 44) + 'px';
        ed.tblTools.classList.add('show');
      } else if (!ed.tblTools.matches(':hover')) { ed.tblTools.classList.remove('show'); }
      const b = blockOf(s.getRangeAt(0).startContainer);
      if (!b || !root.contains(b)) return;
      ed.lastCaretBlock = b;
      const c = contentOf(b); if (!c) return;
      const t = c.dataset.contentType;
      const v = t === 'heading' ? 'heading:' + (c.dataset.level || 2) : t;
      const sel = tb.querySelector('.ce-type');
      if ([...sel.options].some(o => o.value === v)) sel.value = v;
    });

    on(root, 'input', () => changed(false));
    on(title, 'input', () => changed(false));
    on(title, 'keydown', e => { if (e.key === 'Enter') { e.preventDefault(); placeCaret(root.querySelector('.bn-inline-content'), false); } });

    // ---- keyboard: Enter splits blocks, Backspace merges, Tab nests, shortcuts
    on(root, 'keydown', e => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); save(true); return; }
      if (mod && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return; }
      if (mod && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); redo(); return; }
      const b = currentBlock();
      if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); move(b, e.key === 'ArrowUp' ? -1 : 1); return; }
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); openLinkDialog(); return; }
      const cell = (getSelection().anchorNode && (getSelection().anchorNode.nodeType === 1 ? getSelection().anchorNode : getSelection().anchorNode.parentElement))?.closest?.('td,th');
      if (e.key === 'Tab' && cell && root.contains(cell)) {
        e.preventDefault();
        const cells = [...cell.closest('table').querySelectorAll('td,th')];
        let i = cells.indexOf(cell) + (e.shiftKey ? -1 : 1);
        if (i >= cells.length) { tableOp(cell, 'row-below'); i = cells.length; }
        const nc = [...cell.closest('table').querySelectorAll('td,th')][Math.max(0, i)];
        if (nc) placeCaret(nc.querySelector('p') || nc, true);
        return;
      }
      if (e.key === 'Tab') { e.preventDefault(); if (b) (e.shiftKey ? outdent(b) : indent(b)); return; }
      if (ed.selectedBlock && typeOf(ed.selectedBlock) === 'image' && (e.key === 'Delete' || e.key === 'Backspace')) {
        e.preventDefault(); removeBlock(ed.selectedBlock); return;
      }
      if (!b) return;
      const ic = inlineOf(b);
      if (!ic) return;
      const s = getSelection(); if (!s.rangeCount) return;
      const r = s.getRangeAt(0);
      if (e.key === 'Enter' && !e.shiftKey) {
        if (!ic.contains(r.startContainer)) return;
        e.preventDefault();
        snapshot(true);
        if (!s.isCollapsed) r.deleteContents();
        const t = typeOf(b);
        // Enter on an empty list item ends the list (Word behaviour)
        if (!ic.textContent.trim() && (t === 'bulletListItem' || t === 'numberedListItem')) {
          if (b.parentElement !== root) outdent(b); else setType(b, 'paragraph');
          return;
        }
        const tail = document.createRange();
        tail.setStart(r.startContainer, r.startOffset);
        tail.setEnd(ic, ic.childNodes.length);
        const frag = tail.extractContents();
        const nextType = (t === 'bulletListItem' || t === 'numberedListItem') ? t : 'paragraph';
        const nb = newBlock(nextType);
        const nic = inlineOf(nb);
        nic.innerHTML = '';
        nic.appendChild(frag);
        if (!nic.textContent.length && !nic.querySelector('img')) nic.innerHTML = '<br class="ProseMirror-trailingBreak">';
        if (!ic.textContent.length && !ic.querySelector('img')) ic.innerHTML = '<br class="ProseMirror-trailingBreak">';
        // the new block takes over the children (like splitting a paragraph)
        const kids = childGroup(b, false);
        b.after(nb);
        if (kids && nextType === 'paragraph' && t === 'paragraph') nb.querySelector(':scope > .bn-block').appendChild(kids);
        placeCaret(nic, false);
        changed(true);
        return;
      }
      if (e.key === 'Enter' && e.shiftKey) {
        e.preventDefault();
        document.execCommand('insertLineBreak');
        changed(false);
        return;
      }
      if (e.key === 'Backspace' && s.isCollapsed) {
        const pre = document.createRange();
        pre.setStart(ic, 0); pre.setEnd(r.startContainer, r.startOffset);
        if (pre.toString().length === 0 && !pre.cloneContents().querySelector('img')) {
          e.preventDefault();
          snapshot(true);
          const t = typeOf(b);
          if (t !== 'paragraph') { setType(b, 'paragraph'); return; }          // 1st: turn list/heading into text
          if (b.parentElement !== root) { outdent(b); placeCaret(ic, false); return; }
          // merge into the previous text block
          let prev = b.previousElementSibling;
          while (prev && prev.classList.contains('bn-block-outer')) {
            const deepest = [...prev.querySelectorAll('.bn-block-outer')].pop() || prev;
            if (isTextBlock(deepest)) { prev = deepest; break; }
            prev = null;
          }
          if (!prev || !isTextBlock(prev)) {
            if (!ic.textContent.trim() && b.previousElementSibling) { const pb = b.previousElementSibling; b.remove(); selectBlock(pb); changed(true); }
            return;
          }
          const pic = inlineOf(prev);
          pic.querySelectorAll('br.ProseMirror-trailingBreak').forEach(x => x.remove());
          const mark = document.createElement('span'); mark.className = 'ce-caret';
          pic.appendChild(mark);
          [...ic.childNodes].filter(n => !(n.nodeName === 'BR' && n.classList?.contains('ProseMirror-trailingBreak'))).forEach(n => pic.appendChild(n));
          const kids = childGroup(b, false);
          if (kids) childGroup(prev, true).append(...kids.children);
          b.remove();
          const cr = document.createRange(); cr.setStartBefore(mark); cr.collapse(true);
          s.removeAllRanges(); s.addRange(cr); mark.remove();
          if (!pic.textContent.length) pic.innerHTML = '<br class="ProseMirror-trailingBreak">';
          changed(true);
        }
      }
    });

    // ---- paste: images upload; rich text keeps bold/italic/links/headings/lists
    on(root, 'paste', async e => {
      const cd = e.clipboardData; if (!cd) return;
      const files = [...cd.files].filter(f => f.type.startsWith('image/'));
      if (files.length) { e.preventDefault(); await insertImages(files, currentBlock(), false); return; }
      const html = cd.getData('text/html'), text = cd.getData('text/plain');
      { const an = getSelection().anchorNode, el = an && (an.nodeType === 1 ? an : an.parentElement);
        const icon = el && el.closest && el.closest('.mark-calloutIcon');
        if (icon) { const r = document.createRange(); r.setStartAfter(icon); r.collapse(true); getSelection().removeAllRanges(); getSelection().addRange(r); } }
      const inCell = (getSelection().anchorNode?.parentElement || getSelection().anchorNode)?.closest?.('td,th');
      e.preventDefault();
      snapshot(true);
      const blocks = html && !inCell ? htmlToBlocks(html) : null;
      if (!blocks || !blocks.length) {
        const lines = (text || '').replace(/\r/g, '').split('\n');
        document.execCommand('insertText', false, lines.shift());
        if (inCell) { lines.forEach(l => document.execCommand('insertText', false, ' ' + l)); changed(false); return; }
        let b = currentBlock();
        lines.forEach(line => {
          const m = line.match(/^\s*([-*•]|\d+[.)])\s+(.*)$/);
          const type = m ? (/\d/.test(m[1]) ? 'numberedListItem' : 'bulletListItem') : 'paragraph';
          const nb = newBlock(type);
          inlineOf(nb).textContent = m ? m[2] : line;
          if (!inlineOf(nb).textContent) inlineOf(nb).innerHTML = '<br class="ProseMirror-trailingBreak">';
          if (b) b.after(nb); else root.appendChild(nb);
          b = nb;
        });
        if (lines.length) placeCaret(inlineOf(b));
        changed(true);
        return;
      }
      // first pasted block's text goes where the caret is; the rest become blocks after it
      const first = blocks.shift();
      document.execCommand('insertHTML', false, first.html || '');
      let b = currentBlock();
      blocks.forEach(x => {
        const nb = x.type === 'image' ? imageBlock(x.src) : newBlock(x.type);
        if (x.type !== 'image') inlineOf(nb).innerHTML = x.html || '<br class="ProseMirror-trailingBreak">';
        if (b) b.after(nb); else root.appendChild(nb);
        b = nb;
      });
      if (b && inlineOf(b)) placeCaret(inlineOf(b));
      changed(true);
    });

    // ---- links stay clickable with Ctrl/Cmd; images select on click
    on(root, 'click', e => {
      if (ed.suppressClick) { e.preventDefault(); return; }
      const ib = imgBlockOf(e.target);
      if (ib) { e.preventDefault(); selectBlock(ib); return; }
      if (!e.target.closest('.ce-handle')) selectBlock(null);
      // toggle headings / toggle lists: let the arrow open/close while editing
      const tbtn = e.target.closest('.bn-toggle-button');
      if (tbtn) {
        e.preventDefault();
        const w = tbtn.closest('.bn-toggle-wrapper');
        w.dataset.showChildren = w.dataset.showChildren === 'false' ? 'true' : 'false';
      }
    });
    on(root, 'dblclick', e => { const ib = imgBlockOf(e.target); if (ib && window.tempuOpenLightbox) window.tempuOpenLightbox(ib.querySelector('img')); });

    on(imgTools, 'click', e => {
      const btn = e.target.closest('button'); const b = ed.selectedBlock; if (!btn || !b) return;
      if (btn.dataset.img === 'more') { imgTools.querySelector('.ce-img-more').classList.toggle('open'); return; }
      imgTools.querySelector('.ce-img-more').classList.remove('open');
      if (btn.dataset.w) return setImgWidth(b, +btn.dataset.w);
      const a = btn.dataset.img;
      if (a === 'orig') { const i = imgEl(b); return setImgPx(b, i.naturalWidth || currentPx(b)); }
      if (a.startsWith('align-')) return setImgAlign(b, a.slice(6));
      if (a.startsWith('wrap-')) return setImgWrap(b, a.slice(5));
      if (a === 'side-next' || a === 'side-prev') {
        let t = a === 'side-next' ? b.nextElementSibling : b.previousElementSibling;
        if (!t && b.parentElement.classList.contains('bn-block-column')) { const col = a === 'side-next' ? b.parentElement.parentElement.nextElementSibling : b.parentElement.parentElement.previousElementSibling; t = col; }
        if (t && t.classList.contains('bn-block-column-list')) {
          const cols = [...t.querySelectorAll(':scope > .bn-block-column')];
          t = (a === 'side-next' ? cols[0] : cols[cols.length - 1])?.querySelector('.bn-block-outer');
        }
        if (!t || !t.classList.contains('bn-block-outer')) { toast(a === 'side-next' ? 'There is no block after this image.' : 'There is no block before this image.'); return; }
        placeBeside(t, b, a === 'side-next' ? 'left' : 'right');
        return selectBlock(b);
      }
      if (a === 'unpair') { unpair(b); return selectBlock(b); }
      if (a === 'rot-l' || a === 'rot-r' || a === 'flip-h' || a === 'flip-v') return transformImage(b, a);
      if (a === 'crop') return startCrop(b);
      if (a === 'up') { move(b, -1); return selectBlock(b); }
      if (a === 'down') { move(b, 1); return selectBlock(b); }
      if (a === 'dup') return duplicate(b);
      if (a === 'full') return window.tempuOpenLightbox && window.tempuOpenLightbox(imgEl(b));
      if (a === 'delete') return removeBlock(b);
      if (a === 'caption') return setCaption(b);
      if (a === 'alt') {
        const i = imgEl(b); const v = prompt('Alternative text (describes the image for search and screen readers):', i.alt || '');
        if (v === null) return; i.alt = v.trim(); return changed(true);
      }
      if (a === 'replace') {
        const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/*';
        inp.onchange = async () => {
          const [u] = await upload([...inp.files]); if (!u) return;
          b.querySelectorAll('img').forEach(i => i.src = u);
          contentOf(b).dataset.url = u; changed(true);
        };
        inp.click();
      }
    });

    // ---- resize by dragging the handles round the selected image
    on(ed.resizer, 'pointerdown', e => {
      const h = e.target.closest('.ce-rh'); const b = ed.selectedBlock; if (!h || !b) return;
      e.preventDefault(); e.stopPropagation();
      h.setPointerCapture(e.pointerId);
      const dir = h.dataset.h, startX = e.clientX, startY = e.clientY, startW = currentPx(b);
      const i = imgEl(b); const ratio = (i.naturalHeight && i.naturalWidth) ? i.naturalHeight / i.naturalWidth : (i.offsetHeight / Math.max(1, i.offsetWidth));
      const centered = contentOf(b).dataset.textAlignment === 'center';
      ed.resizer.classList.add('is-resizing');
      const moveFn = ev => {
        let dx = ev.clientX - startX, dy = ev.clientY - startY;
        if (dir.includes('w')) dx = -dx;
        let w = startW;
        if (dir === 'n' || dir === 's') w = startW + (dir === 's' ? dy : -dy) / Math.max(ratio, 0.01);
        else w = startW + dx * (centered ? 2 : 1);
        setImgPx(b, w, false);
      };
      const upFn = () => { h.removeEventListener('pointermove', moveFn); h.removeEventListener('pointerup', upFn); ed.resizer.classList.remove('is-resizing'); changed(true); };
      h.addEventListener('pointermove', moveFn); h.addEventListener('pointerup', upFn);
    });

    // ---- rotate by dragging the round knob above the image (snaps to 90°)
    on(ed.resizer, 'pointerdown', e => {
      const knob = e.target.closest('.ce-rot'); const b = ed.selectedBlock; if (!knob || !b) return;
      e.preventDefault(); e.stopPropagation(); knob.setPointerCapture(e.pointerId);
      const img = imgEl(b), r = img.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const a0 = Math.atan2(e.clientY - cy, e.clientX - cx);
      let deg = 0;
      const lbl = ed.resizer.querySelector('.ce-rs-label');
      ed.resizer.classList.add('is-rotating');
      const mv = ev => {
        let d = (Math.atan2(ev.clientY - cy, ev.clientX - cx) - a0) * 180 / Math.PI;
        d = ((d + 540) % 360) - 180;
        const snap = Math.round(d / 90) * 90;
        deg = Math.abs(d - snap) < 7 ? snap : Math.round(d);
        img.style.transform = `rotate(${deg}deg)`;
        lbl.textContent = deg + '°';
      };
      const up = async () => {
        knob.removeEventListener('pointermove', mv); knob.removeEventListener('pointerup', up);
        ed.resizer.classList.remove('is-rotating');
        img.style.removeProperty('transform');
        if (deg % 360 !== 0) await rotateBy(b, deg);
        positionImgTools();
      };
      knob.addEventListener('pointermove', mv); knob.addEventListener('pointerup', up);
    });

    // ---- drag an image itself to move it (drop above/below any block, or beside it)
    on(root, 'pointerdown', e => {
      if (e.button !== 0) return;
      const b = imgBlockOf(e.target); if (!b || e.target.closest('figcaption') || ed.cropping) return;
      const sx = e.clientX, sy = e.clientY;
      let dragging = false, target = null;
      const mv = ev => {
        if (!dragging) {
          if (Math.hypot(ev.clientX - sx, ev.clientY - sy) < 6) return;
          dragging = true; ed.dragBlock = b; b.classList.add('ce-dragging'); selectBlock(b);
          ed.ghost.innerHTML = ''; const g = imgEl(b).cloneNode(); g.removeAttribute('width'); ed.ghost.appendChild(g); ed.ghost.classList.add('show');
          ed.imgTools.classList.remove('show'); ed.resizer.classList.remove('show');
        }
        ev.preventDefault();
        Object.assign(ed.ghost.style, {left: ev.clientX + 12 + 'px', top: ev.clientY + 12 + 'px'});
        ed.ghost.style.display = 'none';
        dropLine.classList.remove('show'); ed.vline.classList.remove('show'); ed.alignZones.classList.remove('show');
        // still over its own row -> horizontal drag aligns it (left / center / right)
        const own = (contentOf(b) || b).getBoundingClientRect();
        if (ev.clientY > own.top - 10 && ev.clientY < own.bottom + 10) {
          const col = (b.closest('.bn-block-column') || b.parentElement).getBoundingClientRect();
          const zone = ev.clientX < col.left + col.width / 3 ? 'left' : ev.clientX > col.left + col.width * 2 / 3 ? 'right' : 'center';
          Object.assign(ed.alignZones.style, {left: col.left + 'px', top: own.top + 'px', width: col.width + 'px', height: own.height + 'px'});
          ed.alignZones.querySelectorAll('span').forEach(z => z.classList.toggle('on', z.dataset.z === zone));
          ed.alignZones.classList.add('show');
          target = {align: zone};
          ed.ghost.style.display = '';
          return;
        }
        target = dropPoint(ev);
        ed.ghost.style.display = '';
        if (!target) return;
        const r = target.r;
        const zone = Math.min(120, r.width * 0.22);
        if (ev.clientX < r.left + zone || ev.clientX > r.right - zone) {
          target.side = ev.clientX < r.left + zone ? 'left' : 'right';
          Object.assign(ed.vline.style, {left: (target.side === 'left' ? r.left - 4 : r.right + 1) + 'px', top: r.top + 'px', height: r.height + 'px'});
          ed.vline.classList.add('show');
        } else {
          target.side = null;
          const rr = (target.b.closest('.bn-block-column') || root).getBoundingClientRect();
          Object.assign(dropLine.style, {left: rr.left + 'px', width: rr.width + 'px', top: ((target.before ? r.top : r.bottom) - 2) + 'px'});
          dropLine.classList.add('show');
        }
      };
      const up = () => {
        document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up);
        if (!dragging) return;
        ed.suppressClick = true; setTimeout(() => { if (ed) ed.suppressClick = false; }, 50);
        ed.ghost.classList.remove('show'); dropLine.classList.remove('show'); ed.vline.classList.remove('show'); ed.alignZones.classList.remove('show');
        b.classList.remove('ce-dragging'); ed.dragBlock = null;
        if (!target) { positionImgTools(); return; }
        if (target.align) { setImgAlign(b, target.align); return selectBlock(b); }
        if (target.side) placeBeside(target.b, b, target.side);
        else {
          snapshot(true);
          const oldGroup = b.parentElement;
          if (target.before) target.b.before(b); else target.b.after(b);
          if (oldGroup !== root && oldGroup.classList.contains('bn-block-group') && !oldGroup.children.length) oldGroup.remove();
          changed(true);
        }
        selectBlock(b);
      };
      document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up);
    });

    // ---- hover handle (drag / add) for every block, text or image
    on(root, 'mousemove', e => {
      if (ed.dragBlock || e.buttons) return;      // don't move the handle while a button is held
      const b = blockOf(e.target);
      if (!b || !root.contains(b)) return;
      if (b !== ed.hoverBlock) { ed.hoverBlock = b; placeHandle(b); }
    });
    on(window, 'scroll', () => { if (ed) { if (ed.hoverBlock) placeHandle(ed.hoverBlock); positionImgTools(); } }, true);
    on(window, 'resize', () => { if (ed) positionImgTools(); });
    function placeHandle(b) {
      const c = contentOf(b) || b;
      const r = c.getBoundingClientRect();
      const rr = root.getBoundingClientRect();
      handle.style.top = (r.top + Math.min(r.height, 34) / 2 - 13) + 'px';
      handle.style.left = Math.max(4, Math.min(r.left, rr.left) - 52) + 'px';
      handle.classList.add('show');
    }
    on(handle.querySelector('.ce-h-add'), 'click', () => { if (ed.hoverBlock) addBelow(ed.hoverBlock); });
    on(handle.querySelector('.ce-h-drag'), 'click', () => { if (ed.hoverBlock) selectBlock(ed.hoverBlock); });

    const drag = handle.querySelector('.ce-h-drag');
    on(drag, 'dragstart', e => {
      const b = ed.hoverBlock; if (!b) return;
      ed.dragBlock = b;
      b.classList.add('ce-dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/x-tempu-block', b.dataset.id || 'block');
      try { e.dataTransfer.setDragImage(contentOf(b) || b, 10, 10); } catch (_) { /* ignore */ }
    });
    on(drag, 'dragend', () => endDrag());
    function endDrag() {
      if (ed && ed.dragBlock) ed.dragBlock.classList.remove('ce-dragging');
      if (ed) { ed.dragBlock = null; ed.dropTarget = null; }
      dropLine.classList.remove('show');
    }
    function dropPoint(e) {
      let el = document.elementFromPoint(e.clientX, e.clientY);
      let b = blockOf(el);
      if (!b || !root.contains(b)) {
        // pointer in the margin: nearest block by vertical position
        const all = [...root.querySelectorAll(':scope > .bn-block-outer')];
        b = all.find(x => x.getBoundingClientRect().bottom > e.clientY) || all[all.length - 1];
      }
      if (!b) return null;
      // pointer in a list's indentation gutter -> target the parent block instead
      let lifted = false;
      while (b.parentElement !== root && b.parentElement.classList.contains('bn-block-group')) {
        const left = (contentOf(b) || b).getBoundingClientRect().left;
        const up = b.parentElement.closest('.bn-block-outer');
        if (up && root.contains(up) && e.clientX < left - 6) { b = up; lifted = true; } else break;
      }
      if (ed.dragBlock && (b === ed.dragBlock || ed.dragBlock.contains(b))) return null;
      const r = (lifted ? b : (contentOf(b) || b)).getBoundingClientRect();
      const before = e.clientY < r.top + r.height / 2;
      return {b, before, r};
    }
    on(root, 'dragover', e => {
      const isFiles = [...(e.dataTransfer?.types || [])].includes('Files');
      if (!ed.dragBlock && !isFiles) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = isFiles ? 'copy' : 'move';
      const p = dropPoint(e);
      if (!p) { dropLine.classList.remove('show'); ed.dropTarget = null; return; }
      ed.dropTarget = p;
      const rr = (p.b.closest('.bn-block-column') || root).getBoundingClientRect();
      const left = Math.max(rr.left, p.r.left - 4);
      dropLine.style.left = left + 'px';
      dropLine.style.width = (rr.right - left) + 'px';
      dropLine.style.top = ((p.before ? p.r.top : p.r.bottom) - 2) + 'px';
      dropLine.classList.add('show');
    });
    on(root, 'dragleave', e => { if (!root.contains(e.relatedTarget)) dropLine.classList.remove('show'); });
    on(root, 'drop', async e => {
      const files = [...(e.dataTransfer?.files || [])].filter(f => f.type.startsWith('image/'));
      const p = ed.dropTarget || dropPoint(e);
      if (files.length) {
        e.preventDefault(); dropLine.classList.remove('show');
        await insertImages(files, p ? p.b : null, p ? p.before : false);
        return;
      }
      if (!ed.dragBlock) return;
      e.preventDefault();
      if (p) {
        snapshot(true);
        const oldGroup = ed.dragBlock.parentElement;
        if (p.before) p.b.before(ed.dragBlock); else p.b.after(ed.dragBlock);
        if (oldGroup !== root && oldGroup.classList.contains('bn-block-group') && !oldGroup.children.length) oldGroup.remove();
        selectBlock(ed.dragBlock);
        changed(true);
      }
      endDrag();
    });
    // dropping image files anywhere on the topic while editing
    on(ed.art, 'dragover', e => { if ([...(e.dataTransfer?.types || [])].includes('Files')) e.preventDefault(); });

    on(window, 'beforeunload', e => { if (ed && ed.dirty) { saveOnUnload(); e.preventDefault(); e.returnValue = ''; } });
    on(document, 'click', e => {
      if (!e.target.closest('.ce-pop-wrap')) tb.querySelectorAll('.ce-pop.open').forEach(p => p.classList.remove('open'));
    });
    on(document, 'keydown', e => {
      if (e.key !== 'Escape' || !ed || document.querySelector('#img-lightbox.open, .ce-crop, #ce-link-dlg.open')) return;
      if (ed.selectedBlock) { selectBlock(null); return; }
      finish();
    });
  }

  async function restoreOriginal() {
    if (!ed) return;
    if (!confirm('Go back to the original content of this topic?\n(You can undo this, and your edited version stays in Version history.)')) return;
    const {tid} = ed;
    if (ed.saving) await ed.saving;          // a save landing after this would undo it
    if (!ed) return;
    ed.dirty = false; clearTimeout(ed.timer); clearTimeout(ed.retry);
    teardown();
    await fetch(`/api/topics/${tid}/content`, {method: 'DELETE'});
    location.hash = 'topic-' + tid; location.reload();
  }
  async function showHistory() {
    if (!ed) return;
    const {tid} = ed;
    await save();
    if (window.TempuHistory) { window.TempuHistory.openTopic(tid); return; }
    toast('Version history is not available.');
  }

  // ------------------------------------------------------------ entry points
  document.addEventListener('click', e => {
    const btn = e.target.closest('.topic-edit-btn');
    if (!btn) return;
    e.preventDefault(); e.stopPropagation();
    const art = btn.closest('.topic-article');
    if (ed && ed.art === art) finish(); else start(art);
  });
  // the "⋮" topic menu gets an "Edit content" entry
  const menu = document.getElementById('topic-actions-menu');
  if (menu && !menu.querySelector('[data-act="edit"]')) {
    const b = document.createElement('button');
    b.dataset.act = 'edit';
    b.className = 'flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent';
    b.innerHTML = ic('<path d="M12 20h9"/><path d="M16.4 3.6a2.1 2.1 0 0 1 3 3L7.4 18.6 3 20l1.4-4.4Z"/>') + 'Edit content';
    menu.insertBefore(b, menu.firstChild);
    b.addEventListener('click', () => {
      const id = menu.dataset.currentTopic || document.querySelector('.topic-actions-btn.ce-last')?.dataset.topic;
      const art = id && document.getElementById('topic-' + id);
      menu.classList.add('hidden');
      if (art) start(art);
    });
    document.addEventListener('click', e => {
      const t = e.target.closest('.topic-actions-btn');
      if (t) { menu.dataset.currentTopic = t.dataset.topic; }
    }, true);
  }
  window.TempuContentEditor = {start: art => start(art), finish: () => finish()};
})();
