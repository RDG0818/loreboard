import Masonry from 'masonry-layout';
import imagesLoaded from 'imagesloaded';

const API_BASE = '';

document.addEventListener('DOMContentLoaded', async () => {
  const gallery = document.querySelector('.gallery');
  const scrollTrigger = document.getElementById('scroll-trigger');
  const searchInput = document.getElementById('search-input');

  let nextCursor = null;
  let hasMore = true;
  let msnry;
  let isLoading = false;
  let searchToken = 0;

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

  async function fetchCardsPage() {
    const params = new URLSearchParams({ limit: '30' });
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

  function cardArtUrl(card) {
    return card.image_uris && card.image_uris.art_crop;
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

      const wrapper = document.createElement('div');
      wrapper.classList.add('image-wrapper');
      wrapper.dataset.cardId = card.id;

      const img = document.createElement('img');
      img.src = artUrl;

      const overlay = document.createElement('div');
      overlay.classList.add('overlay');

      const artistLabel = document.createElement('span');
      artistLabel.classList.add('artist-label');
      artistLabel.textContent = card.artist || '';

      wrapper.appendChild(img);
      wrapper.appendChild(overlay);
      wrapper.appendChild(artistLabel);
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

  window.lucide.createIcons();

  const modal = document.getElementById('image-modal');
  const modalImg = document.getElementById('modal-image');
  const modalName = document.getElementById('modal-name');
  const modalManaCost = document.getElementById('modal-mana-cost');
  const modalTypeLine = document.getElementById('modal-type-line');
  const modalOracleText = document.getElementById('modal-oracle-text');
  const modalArtist = document.getElementById('modal-artist');
  const modalSaveBtn = document.getElementById('modal-save-btn');
  let currentModalCardId = null;
  const closeBtn = document.querySelector('.close-btn');

  gallery.addEventListener('click', async (e) => {
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
    const img = wrapper.querySelector('img');

    modal.classList.add('modal--active');
    modalImg.src = img.src;
    modalName.textContent = '';
    modalManaCost.textContent = '';
    modalTypeLine.textContent = '';
    modalOracleText.textContent = 'Loading...';
    modalArtist.textContent = '';

    try {
      const response = await fetch(`${API_BASE}/api/v1/cards/${cardId}`);
      const card = await response.json();
      modalName.textContent = card.name;
      modalManaCost.textContent = card.mana_cost || '';
      modalTypeLine.textContent = card.type_line || '';
      modalOracleText.textContent = card.oracle_text || '';
      modalArtist.textContent = card.artist ? `Art by ${card.artist}` : '';
      if (card.image_uris && card.image_uris.normal) {
        modalImg.src = card.image_uris.normal;
      }
    } catch (error) {
      modalOracleText.textContent = 'Could not load card details.';
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
        for (const card of results) {
          if (thisToken !== searchToken) return; // superseded by a newer search
          const artUrl = card.image_uris && card.image_uris.art_crop;
          if (!artUrl) continue;
          const wrapper = document.createElement('div');
          wrapper.classList.add('image-wrapper');
          wrapper.dataset.cardId = card.id;

          const img = document.createElement('img');
          img.src = artUrl;

          const overlay = document.createElement('div');
          overlay.classList.add('overlay');

          const artistLabel = document.createElement('span');
          artistLabel.classList.add('artist-label');
          artistLabel.textContent = card.artist || '';

          wrapper.appendChild(img);
          wrapper.appendChild(overlay);
          wrapper.appendChild(artistLabel);
          gallery.appendChild(wrapper);
          await new Promise((resolve) => imagesLoaded(wrapper).on('always', resolve));
          if (thisToken !== searchToken) return; // superseded by a newer search
          msnry.appended(wrapper);
          msnry.layout();
        }
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
    const method = isSaved ? 'DELETE' : 'POST';
    const url = isSaved
      ? `${API_BASE}/api/v1/saves/${currentModalCardId}`
      : `${API_BASE}/api/v1/saves`;

    try {
      const response = await fetch(url, {
        method,
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: isSaved ? undefined : JSON.stringify({ card_id: currentModalCardId }),
      });

      if (response.status === 401) {
        window.location.href = `${API_BASE}/auth/login/google`;
        return;
      }

      if (!response.ok) {
        console.error('Failed to update save state:', response.status);
        const previousText = modalSaveBtn.textContent;
        modalSaveBtn.textContent = 'Error';
        setTimeout(() => {
          modalSaveBtn.textContent = previousText;
        }, 1500);
        return;
      }

      modalSaveBtn.textContent = isSaved ? 'Save' : 'Saved';
      modalSaveBtn.classList.toggle('saved', !isSaved);
      if (isSaved) {
        savedCardIds.delete(currentModalCardId);
      } else {
        savedCardIds.add(currentModalCardId);
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
