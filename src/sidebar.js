export function initSidebarToggle() {
  const toggle = document.getElementById('sidebar-toggle');
  if (!toggle) return;

  const collapsed = localStorage.getItem('sidebarCollapsed') === 'true';
  document.body.classList.toggle('sidebar-collapsed', collapsed);

  toggle.addEventListener('click', () => {
    const isCollapsed = document.body.classList.toggle('sidebar-collapsed');
    localStorage.setItem('sidebarCollapsed', isCollapsed);
  });

  // Masonry only re-lays-out on `window` resize events by default — the
  // sidebar's width change is a CSS transition on `.sidebar`, not a window
  // resize, so Masonry never notices the gallery got wider/narrower and its
  // cached item positions go stale. Pages that use Masonry listen for this
  // event and call `msnry.layout()`.
  const sidebar = document.querySelector('.sidebar');
  if (sidebar) {
    sidebar.addEventListener('transitionend', (e) => {
      if (e.propertyName === 'width') {
        window.dispatchEvent(new Event('sidebar:layout-change'));
      }
    });
  }
}
