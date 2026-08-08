// Shared modal wiring for any page with a `.image-wrapper` gallery: opens
// #image-modal on card click, preloads the full card image behind a blurred
// skeleton (see .modal-content--loading in style.css), and handles the
// modal's own save/unsave button. Extracted from main.js so favorites.js
// (and any future gallery page) can reuse it instead of duplicating it.
export function initModal({ gallery, cardsById, savedCardIds, toggleSave, onSaveToggled }) {
  const modal = document.getElementById('image-modal');
  const modalImg = document.getElementById('modal-image');
  const modalArtist = document.getElementById('modal-artist');
  const modalSaveBtn = document.getElementById('modal-save-btn');
  const closeBtn = modal.querySelector('.close-btn');
  let currentModalCardId = null;

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
    // clear on src reassignment. Show the art-crop thumbnail (already
    // cached, loads instantly) as a blurred skeleton placeholder sized to a
    // standard card, then preload the full image and swap once it's ready.
    // The cardId guard drops a stale preload if the user has already
    // clicked a different card before this one finishes loading.
    const normalUrl = card && card.image_uris && card.image_uris.normal;
    if (normalUrl) {
      modalImg.src = img.src;
      modalImg.classList.add('modal-content--loading');
      preloadFullCard(normalUrl, cardId, img.src);
    } else {
      // No full-card image available for this card at all — just show the
      // art-crop thumbnail, sharp, rather than a placeholder that never resolves.
      modalImg.classList.remove('modal-content--loading');
      modalImg.src = img.src;
    }
  });

  // A failed/stalled fetch of the full-card image used to leave the modal
  // stuck on the blurred placeholder forever, indistinguishable from "still
  // loading" — retry once (CDN blips are usually transient), then fall back
  // to the (sharp) art-crop thumbnail rather than leaving it blurred forever.
  function preloadFullCard(normalUrl, cardId, fallbackSrc, isRetry = false) {
    const preload = new Image();
    preload.onload = () => {
      if (currentModalCardId !== cardId) return;
      modalImg.classList.remove('modal-content--loading');
      modalImg.src = normalUrl;
    };
    preload.onerror = () => {
      if (currentModalCardId !== cardId) return;
      if (!isRetry) {
        preloadFullCard(normalUrl, cardId, fallbackSrc, true);
      } else {
        console.error('Failed to load full card image:', normalUrl);
        modalImg.classList.remove('modal-content--loading');
        modalImg.src = fallbackSrc;
      }
    };
    preload.src = normalUrl;
  }

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

      // Default behavior keeps a same-page grid's own .save-btn in sync
      // (main.js's browse feed). Pages where unsaving should remove the
      // card entirely (favorites.js) pass their own hook instead.
      if (onSaveToggled) {
        onSaveToggled(currentModalCardId, !isSaved);
      } else {
        const cardSaveBtn = gallery.querySelector(
          `.image-wrapper[data-card-id="${currentModalCardId}"] .save-btn`
        );
        if (cardSaveBtn) {
          cardSaveBtn.textContent = isSaved ? 'Save' : 'Saved';
          cardSaveBtn.classList.toggle('saved', !isSaved);
        }
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
}
