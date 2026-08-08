import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper, createSaveToggler } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';
import { initModal } from './modal.js';
import { fetchSavedCardIds, createMasonry } from './api.js';

const API_BASE = '';
// Blocked until the recommendation system exists: wide spans need to know
// column state at insert time to stay gap-free, which only Packery's internal
// bin-packer sees. See docs/notes/polish-backlog.md for the plan. Flip to true
// once a gap-safe placement rule (or the rec system) lands.
const ENABLE_WIDE_TILES = false;

document.addEventListener('DOMContentLoaded', async () => {
  initSidebarToggle();
  initSignInLink(API_BASE);
  const gallery = document.querySelector('.gallery');
  const scrollTrigger = document.getElementById('scroll-trigger');
  const searchInput = document.getElementById('search-input');
  const showAllToggle = document.getElementById('show-all-toggle');

  let nextCursor = null;
  let hasMore = true;
  let msnry;
  let isLoading = false;
  let searchToken = 0;
  let showAllCards = localStorage.getItem('showAllCards') === 'true';
  // One shuffle per page load — stable while scrolling/clearing search, fresh on reload.
  // Extension point: this becomes a per-user recommendation ranking later; the feed API
  // just needs an opaque `seed`, so that swap won't touch this file.
  const feedSeed = Math.random().toString(36).slice(2);

  const savedCardIds = await fetchSavedCardIds(API_BASE);
  const toggleSave = createSaveToggler(API_BASE, savedCardIds);
  const cardsById = new Map();

  async function fetchCardsPage() {
    const params = new URLSearchParams({ limit: '30', seed: feedSeed });
    if (nextCursor) params.set('cursor', nextCursor);
    if (showAllCards) params.set('show_all', 'true');
    try {
      const response = await fetch(`${API_BASE}/api/v1/cards?${params}`);
      if (!response.ok) throw new Error('Network response was not ok');
      return await response.json();
    } catch (error) {
      console.error('Failed to fetch cards:', error);
      gallery.innerHTML = `<p class="error-message">Could not load cards. Please ensure the backend is running.</p>`;
      return [];
    }
  }

  async function loadMoreCards(token = searchToken) {
    if (isLoading || !hasMore) return;
    isLoading = true;

    const page = await fetchCardsPage();
    if (token !== searchToken) {
      // superseded by a newer search (or another newer loadMoreCards call)
      isLoading = false;
      return;
    }
    if (page.length === 0) {
      hasMore = false;
      observer.unobserve(scrollTrigger);
      isLoading = false;
      return;
    }
    nextCursor = page[page.length - 1].id;

    if (!msnry) {
      msnry = createMasonry(gallery);
    }

    const wrappers = [];
    for (const card of page) {
      if (token !== searchToken) {
        // superseded by a newer search (or another newer loadMoreCards call)
        isLoading = false;
        return;
      }
      const artUrl = cardArtUrl(card);
      if (!artUrl) continue;

      // Never let the very first card in the gallery be wide — Packery uses
      // the first .image-wrapper's width to set its column unit, and a wide
      // first card would throw off every column-count calc after it. Checked
      // against the live DOM (not e.g. cardsById) so this stays correct across
      // feed resets, which wipe the gallery but not the id->card lookup.
      const enableWideTiles = ENABLE_WIDE_TILES && gallery.querySelector('.image-wrapper') !== null;
      cardsById.set(card.id, card);
      const wrapper = createCardWrapper(card, { savedCardIds, onToggleSave: toggleSave, enableWideTiles });
      gallery.appendChild(wrapper);
      wrappers.push(wrapper);

      // The skeleton placeholder (cardRender.js/style.css) already gives
      // Packery a correctly-sized box the instant it's appended, so cards
      // don't need to wait on their own (uncached) network image before
      // appearing — only the snap to the real image's size needs a
      // relayout once it's actually loaded.
      imagesLoaded(wrapper).on('always', () => {
        if (token !== searchToken) return;
        msnry.layout();
      });
    }

    if (token !== searchToken) {
      isLoading = false;
      return;
    }
    if (wrappers.length > 0) {
      msnry.appended(wrappers);
      msnry.layout();
    }

    isLoading = false;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting) loadMoreCards();
    },
    { rootMargin: '200px' }
  );
  observer.observe(scrollTrigger);
  loadMoreCards();

  // Wipes the gallery and restarts the browse feed from page 1 — used both
  // when search is cleared and when the show-all-cards toggle flips.
  async function resetAndReloadFeed() {
    const thisToken = ++searchToken;
    gallery.innerHTML = '<div class="gutter-sizer"></div>';
    msnry = null;
    // Wait for any in-flight scroll-triggered load to finish, otherwise the
    // `isLoading` guard in loadMoreCards() drops this call and the gallery
    // (already wiped above) stays permanently blank.
    while (isLoading) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    if (thisToken !== searchToken) return; // superseded by a newer search/toggle
    nextCursor = null;
    hasMore = true;
    // Re-observe: the trigger is unobserved whenever hasMore goes false.
    observer.observe(scrollTrigger);
    loadMoreCards(thisToken);
  }

  if (showAllToggle) {
    showAllToggle.classList.toggle('active', showAllCards);
    showAllToggle.querySelector('i').setAttribute('data-lucide', showAllCards ? 'eye' : 'eye-off');

    showAllToggle.addEventListener('click', () => {
      showAllCards = !showAllCards;
      localStorage.setItem('showAllCards', showAllCards);
      showAllToggle.classList.toggle('active', showAllCards);
      showAllToggle.querySelector('i').setAttribute('data-lucide', showAllCards ? 'eye' : 'eye-off');
      window.lucide.createIcons();
      // Active search results aren't affected by this filter (search is intent-driven);
      // the browse feed picks up the new setting once the search is cleared.
      if (searchInput.value.trim()) return;
      resetAndReloadFeed();
    });
  }

  // IntersectionObserver samples geometry at throttled checkpoints, so a
  // fast/flung scroll can move scrollTrigger from "below viewport" to
  // "already scrolled past" between two samples without ever reporting
  // isIntersecting: true — the observer misses the crossing entirely and
  // loadMoreCards() never fires. Back it with a plain scroll-position check
  // as a fallback; loadMoreCards()'s own isLoading/hasMore guards make it
  // safe to call redundantly.
  function checkScrollFallback() {
    if (!hasMore || isLoading) return;
    const { scrollY, innerHeight } = window;
    const scrollHeight = document.documentElement.scrollHeight;
    if (scrollHeight - (scrollY + innerHeight) < 400) loadMoreCards();
  }
  window.addEventListener('scroll', checkScrollFallback, { passive: true });
  window.addEventListener('resize', checkScrollFallback);

  window.addEventListener('sidebar:layout-change', () => {
    if (msnry) msnry.layout();
  });

  window.lucide.createIcons();

  initModal({ gallery, cardsById, savedCardIds, toggleSave });

  let searchDebounce;
  searchInput.addEventListener('input', () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(async () => {
      const query = searchInput.value.trim();
      if (!query) {
        await resetAndReloadFeed();
        return;
      }

      const thisToken = ++searchToken;
      gallery.innerHTML = '<div class="gutter-sizer"></div>';
      msnry = null;
      hasMore = false; // search results aren't paginated in this phase
      try {
        const response = await fetch(`${API_BASE}/api/v1/search/natural`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query }),
        });
        const results = await response.json();
        if (thisToken !== searchToken) return; // superseded by a newer search
        msnry = createMasonry(gallery);
        const wrappers = [];
        for (const card of results) {
          const artUrl = cardArtUrl(card);
          if (!artUrl) continue;
          cardsById.set(card.id, card);
          const wrapper = createCardWrapper(card, { savedCardIds, onToggleSave: toggleSave });
          gallery.appendChild(wrapper);
          wrappers.push(wrapper);

          // Skeleton placeholder (cardRender.js/style.css) already sizes the
          // wrapper correctly, so results don't need to wait on every image
          // in the batch loading before any of them appear — only the snap
          // to each real image needs its own relayout once it's loaded.
          imagesLoaded(wrapper).on('always', () => {
            if (thisToken !== searchToken) return;
            msnry.layout();
          });
        }

        if (thisToken !== searchToken) return; // superseded by a newer search
        msnry.appended(wrappers);
        msnry.layout();
      } catch (error) {
        if (thisToken !== searchToken) return; // superseded by a newer search
        gallery.innerHTML = '<p class="error-message">Search failed.</p>';
      }
    }, 400);
  });
});
