import Masonry from 'masonry-layout';
import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper, createSaveToggler } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';

const API_BASE = '';

document.addEventListener('DOMContentLoaded', async () => {
  initSidebarToggle();
  initSignInLink(API_BASE);
  const gallery = document.querySelector('.gallery');
  const scrollTrigger = document.getElementById('scroll-trigger');
  const searchInput = document.getElementById('search-input');

  let nextCursor = null;
  let hasMore = true;
  let msnry;
  let isLoading = false;
  let searchToken = 0;
  // One shuffle per page load — stable while scrolling/clearing search, fresh on reload.
  // Extension point: this becomes a per-user recommendation ranking later; the feed API
  // just needs an opaque `seed`, so that swap won't touch this file.
  const feedSeed = Math.random().toString(36).slice(2);

  let savedCardIds = new Set();
  try {
    const savesResponse = await fetch(`${API_BASE}/api/v1/saves`, { credentials: 'include' });
    if (savesResponse.ok) {
      const saves = await savesResponse.json();
      savedCardIds = new Set(saves.map((c) => c.id));
    }
  } catch (error) {
    // Not logged in or backend unreachable — treat as no saves; the feed itself still works.
  }
  const toggleSave = createSaveToggler(API_BASE, savedCardIds);
  const cardsById = new Map();

  async function fetchCardsPage() {
    const params = new URLSearchParams({ limit: '30', seed: feedSeed });
    if (nextCursor) params.set('cursor', nextCursor);
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
      msnry = new Masonry(gallery, {
        itemSelector: '.image-wrapper',
        columnWidth: '.image-wrapper',
        gutter: 15,
      });
    }

    for (const card of page) {
      if (token !== searchToken) {
        // superseded by a newer search (or another newer loadMoreCards call)
        isLoading = false;
        return;
      }
      const artUrl = cardArtUrl(card);
      if (!artUrl) continue;

      cardsById.set(card.id, card);
      const wrapper = createCardWrapper(card, { savedCardIds, onToggleSave: toggleSave });
      gallery.appendChild(wrapper);

      await new Promise((resolve) => imagesLoaded(wrapper).on('always', resolve));
      if (token !== searchToken) {
        // superseded by a newer search (or another newer loadMoreCards call)
        isLoading = false;
        return;
      }
      msnry.appended(wrapper);
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

  const modal = document.getElementById('image-modal');
  const modalImg = document.getElementById('modal-image');
  const modalArtist = document.getElementById('modal-artist');
  const modalSaveBtn = document.getElementById('modal-save-btn');
  let currentModalCardId = null;
  const closeBtn = document.querySelector('.close-btn');

  gallery.addEventListener('click', (e) => {
    const wrapper = e.target.closest('.image-wrapper');
    if (!wrapper) return;
    const cardId = wrapper.dataset.cardId;
    currentModalCardId = cardId;
    if (savedCardIds.has(cardId)) {
      modalSaveBtn.textContent = 'Saved';
      modalSaveBtn.classList.add('saved');
    } else {
      modalSaveBtn.textContent = 'Save';
      modalSaveBtn.classList.remove('saved');
    }

    // Card list/search responses already carry the full image_uris (incl.
    // `normal`) and artist — no need to re-fetch.
    const card = cardsById.get(cardId);
    const img = wrapper.querySelector('img');

    modal.classList.add('modal--active');
    modalArtist.textContent = card && card.artist ? `Art by ${card.artist}` : '';

    // `modalImg` is a single reused element, so assigning `.src` directly to
    // the (likely uncached) full-size image leaves the *previous* card's
    // bitmap on screen until the new one finishes loading — an <img> doesn't
    // clear on src reassignment. Show the grid thumbnail first (already
    // cached from the grid render, so it paints instantly and is always the
    // right card), then preload the full image and swap only once it's
    // ready. The cardId guard drops a stale preload if the user has already
    // clicked a different card before this one finishes loading.
    modalImg.src = img.src;
    const normalUrl = card && card.image_uris && card.image_uris.normal;
    if (normalUrl && normalUrl !== img.src) {
      const preload = new Image();
      preload.onload = () => {
        if (currentModalCardId === cardId) modalImg.src = normalUrl;
      };
      preload.src = normalUrl;
    }
  });

  let searchDebounce;
  searchInput.addEventListener('input', () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(async () => {
      const query = searchInput.value.trim();
      const thisToken = ++searchToken;
      gallery.innerHTML = '<div class="gutter-sizer"></div>';
      msnry = null;
      if (!query) {
        // Wait for any in-flight scroll-triggered load to finish, otherwise the
        // `isLoading` guard in loadMoreCards() drops this call and the gallery
        // (already wiped above) stays permanently blank.
        while (isLoading) {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        if (thisToken !== searchToken) return; // superseded by a newer search
        nextCursor = null;
        hasMore = true;
        // Re-observe: the trigger is unobserved whenever hasMore goes false.
        observer.observe(scrollTrigger);
        loadMoreCards(thisToken);
        return;
      }

      hasMore = false; // search results aren't paginated in this phase
      try {
        const response = await fetch(`${API_BASE}/api/v1/search/natural`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query }),
        });
        const results = await response.json();
        if (thisToken !== searchToken) return; // superseded by a newer search
        msnry = new Masonry(gallery, {
          itemSelector: '.image-wrapper',
          columnWidth: '.image-wrapper',
          gutter: 15,
        });
        const wrappers = [];
        for (const card of results) {
          const artUrl = cardArtUrl(card);
          if (!artUrl) continue;
          cardsById.set(card.id, card);
          const wrapper = createCardWrapper(card, { savedCardIds, onToggleSave: toggleSave });
          gallery.appendChild(wrapper);
          wrappers.push(wrapper);
        }

        // Images load in parallel rather than one-at-a-time — with hundreds of
        // results a serial await-per-image loop made results trickle in visibly slowly.
        await new Promise((resolve) => imagesLoaded(gallery).on('always', resolve));
        if (thisToken !== searchToken) return; // superseded by a newer search
        msnry.appended(wrappers);
        msnry.layout();
      } catch (error) {
        if (thisToken !== searchToken) return; // superseded by a newer search
        gallery.innerHTML = '<p class="error-message">Search failed.</p>';
      }
    }, 400);
  });

  function closeModal() {
    modal.classList.remove('modal--active');
  }
  closeBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  modalSaveBtn.addEventListener('click', async () => {
    if (!currentModalCardId) return;
    const isSaved = modalSaveBtn.classList.contains('saved');

    try {
      const ok = await toggleSave(currentModalCardId, !isSaved);
      if (!ok) {
        const previousText = modalSaveBtn.textContent;
        modalSaveBtn.textContent = 'Error';
        setTimeout(() => {
          modalSaveBtn.textContent = previousText;
        }, 1500);
        return;
      }

      modalSaveBtn.textContent = isSaved ? 'Save' : 'Saved';
      modalSaveBtn.classList.toggle('saved', !isSaved);

      const cardSaveBtn = gallery.querySelector(
        `.image-wrapper[data-card-id="${currentModalCardId}"] .save-btn`
      );
      if (cardSaveBtn) {
        cardSaveBtn.textContent = isSaved ? 'Save' : 'Saved';
        cardSaveBtn.classList.toggle('saved', !isSaved);
      }
    } catch (error) {
      console.error('Failed to update save state:', error);
      const previousText = modalSaveBtn.textContent;
      modalSaveBtn.textContent = 'Error';
      setTimeout(() => {
        modalSaveBtn.textContent = previousText;
      }, 1500);
    }
  });
});
