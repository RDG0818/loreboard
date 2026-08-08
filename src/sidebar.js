export function initSidebarToggle() {
  const toggle = document.getElementById('sidebar-toggle');
  if (!toggle) return;

  const collapsed = localStorage.getItem('sidebarCollapsed') === 'true';
  document.body.classList.toggle('sidebar-collapsed', collapsed);

  const sidebar = document.querySelector('.sidebar');
  const galleryContainer = document.querySelector('.gallery-container');
  const pageHeader = document.querySelector('.page-header');

  // Set by the click handler just before the collapse/expand transition
  // starts, consumed once the transition (and the relayout it triggers)
  // finishes. { cardId, viewportTop } — the card nearest the viewport
  // center and how far down the viewport it currently sits.
  let anchor = null;

  toggle.addEventListener('click', () => {
    // .sidebar is `position: fixed` (style.css) so it no longer takes up
    // flex space — .gallery-container's margin-left and .page-header's
    // left are what actually reserve room for it. Toggling the collapsed
    // class flips their CSS target instantly (no transition is defined for
    // either), so without this they'd jump the moment you click instead of
    // waiting for the sidebar's own slide to finish, and every card would
    // resize/reflow at the wrong time. Freeze both at their current value
    // via inline style; unfrozen (and relaid-out) once, at transitionend.
    if (galleryContainer) {
      galleryContainer.style.marginLeft = getComputedStyle(galleryContainer).marginLeft;
    }
    if (pageHeader) {
      pageHeader.style.left = getComputedStyle(pageHeader).left;
    }

    // Track a card near the viewport center so it can be put back in the
    // same screen position after the relayout below — more reliable than
    // restoring absolute scrollY, since every card's height changes too
    // (same aspect ratio, but a bigger/smaller container).
    const viewportMid = window.innerHeight / 2;
    let anchorEl = null;
    for (const el of document.querySelectorAll('.image-wrapper')) {
      const rect = el.getBoundingClientRect();
      if (rect.top <= viewportMid && rect.bottom >= viewportMid) {
        anchorEl = el;
        break;
      }
    }
    anchor = anchorEl
      ? { cardId: anchorEl.dataset.cardId, viewportTop: anchorEl.getBoundingClientRect().top }
      : null;

    const isCollapsed = document.body.classList.toggle('sidebar-collapsed');
    localStorage.setItem('sidebarCollapsed', isCollapsed);
  });

  // Masonry only re-lays-out on `window` resize events by default — the
  // sidebar's width change is a CSS transition on `.sidebar`, not a window
  // resize, so Masonry never notices the gallery got wider/narrower and its
  // cached item positions go stale. Pages that use Masonry listen for this
  // event and call `msnry.layout()`.
  if (sidebar) {
    sidebar.addEventListener('transitionend', (e) => {
      if (e.propertyName !== 'width') return;

      if (galleryContainer) galleryContainer.style.marginLeft = '';
      if (pageHeader) pageHeader.style.left = '';

      // Packery animates each item's own reposition over ~0.4s by default.
      // Reading the anchor card's post-layout position right after calling
      // layout() would race that transition (it'd still report the old
      // position, mid-animation). Suppress it for this one relayout so
      // positions land instantly and the scroll correction below reads the
      // true final position, then restore normal animated repositioning
      // (e.g. for infinite-scroll appends) right after.
      document.body.classList.add('layout-instant');
      window.dispatchEvent(new Event('sidebar:layout-change'));

      if (anchor) {
        const anchorEl = document.querySelector(`.image-wrapper[data-card-id="${anchor.cardId}"]`);
        if (anchorEl) {
          const delta = anchorEl.getBoundingClientRect().top - anchor.viewportTop;
          window.scrollBy(0, delta);
        }
        anchor = null;
      }

      requestAnimationFrame(() => document.body.classList.remove('layout-instant'));
    });
  }
}
