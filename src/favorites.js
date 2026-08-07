import Packery from 'packery';
import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';

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
    const response = await fetch(`${API_BASE}/api/v1/saves`, { credentials: 'include' });
    if (response.status === 401) {
      window.location.href = `${API_BASE}/auth/login/google`;
      return;
    }
    saved = await response.json();
  } catch (error) {
    gallery.innerHTML = `<p class="error-message">Could not load your saves.</p>`;
    return;
  }

  for (const card of saved) {
    const artUrl = cardArtUrl(card);
    if (!artUrl) continue;

    const wrapper = createCardWrapper(card);

    const removeBtn = document.createElement('button');
    removeBtn.classList.add('remove-btn');
    removeBtn.innerHTML = '<i data-lucide="trash-2"></i>';

    removeBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        const response = await fetch(`${API_BASE}/api/v1/saves/${card.id}`, {
          method: 'DELETE',
          credentials: 'include',
        });

        if (response.status === 401) {
          window.location.href = `${API_BASE}/auth/login/google`;
          return;
        }

        if (!response.ok) {
          console.error('Failed to remove save:', response.status);
          return;
        }

        msnry.remove(wrapper);
        msnry.layout();
      } catch (error) {
        console.error('Failed to remove save:', error);
      }
    });

    wrapper.appendChild(removeBtn);
    gallery.appendChild(wrapper);

    imagesLoaded(wrapper, () => {
      msnry.appended(wrapper);
      msnry.layout();
    });
  }

  window.lucide.createIcons();
});
