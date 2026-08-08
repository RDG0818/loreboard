import Packery from 'packery';
import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper, createSaveToggler } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';
import { initModal } from './modal.js';
import { apiFetch } from './api.js';

const API_BASE = '';

document.addEventListener('DOMContentLoaded', async () => {
  initSidebarToggle();
  initSignInLink(API_BASE);
  const gallery = document.getElementById('favorites-gallery');

  const msnry = new Packery(gallery, {
    itemSelector: '.image-wrapper',
    columnWidth: '.grid-sizer',
    gutter: '.gutter-sizer',
    percentPosition: true,
  });
  window.addEventListener('sidebar:layout-change', () => msnry.layout());

  let saved;
  try {
    const response = await apiFetch(API_BASE, '/api/v1/saves', { credentials: 'include' });
    if (response.status === 401) return;
    saved = await response.json();
  } catch (error) {
    gallery.innerHTML = `<p class="error-message">Could not load your saves.</p>`;
    return;
  }

  const cardsById = new Map();
  const savedCardIds = new Set(saved.map((c) => c.id));
  const toggleSave = createSaveToggler(API_BASE, savedCardIds);
  const wrappersByCardId = new Map();

  // Shared by the trash-can button and by unsaving through the modal —
  // every card on this page is here because it's saved, so unsaving it
  // (from either place) means it drops out of the grid entirely.
  function removeCard(cardId) {
    const wrapper = wrappersByCardId.get(cardId);
    if (!wrapper) return;
    msnry.remove(wrapper);
    msnry.layout();
    wrappersByCardId.delete(cardId);
  }

  const wrappers = [];
  for (const card of saved) {
    const artUrl = cardArtUrl(card);
    if (!artUrl) continue;

    cardsById.set(card.id, card);
    const wrapper = createCardWrapper(card);
    wrappersByCardId.set(card.id, wrapper);

    const removeBtn = document.createElement('button');
    removeBtn.classList.add('remove-btn');
    removeBtn.innerHTML = '<i data-lucide="trash-2"></i>';

    removeBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        const ok = await toggleSave(card.id, false);
        if (!ok) return;
        removeCard(card.id);
      } catch (error) {
        console.error('Failed to remove save:', error);
      }
    });

    wrapper.appendChild(removeBtn);
    gallery.appendChild(wrapper);
    wrappers.push(wrapper);

    // Skeleton placeholder (cardRender.js/style.css) already sizes the
    // wrapper correctly, so cards don't need to wait on their own network
    // image before appearing — only the snap to the real image needs a
    // relayout once it's loaded.
    imagesLoaded(wrapper, () => msnry.layout());
  }
  msnry.appended(wrappers);
  msnry.layout();

  initModal({
    gallery,
    cardsById,
    savedCardIds,
    toggleSave,
    onSaveToggled: (cardId, isSaved) => {
      if (!isSaved) removeCard(cardId);
    },
  });

  window.lucide.createIcons();
});
