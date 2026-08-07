import Masonry from 'masonry-layout';
import imagesLoaded from 'imagesloaded';

const API_BASE = 'http://127.0.0.1:8000';

document.addEventListener('DOMContentLoaded', async () => {
  const gallery = document.getElementById('favorites-gallery');

  const msnry = new Masonry(gallery, {
    itemSelector: '.image-wrapper',
    columnWidth: '.grid-sizer',
    gutter: '.gutter-sizer',
    percentPosition: true,
  });

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
    const artUrl = card.image_uris && card.image_uris.art_crop;
    if (!artUrl) continue;

    const wrapper = document.createElement('div');
    wrapper.classList.add('image-wrapper');

    const img = document.createElement('img');
    img.src = artUrl;

    const overlay = document.createElement('div');
    overlay.classList.add('overlay');

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

    wrapper.appendChild(img);
    wrapper.appendChild(overlay);
    wrapper.appendChild(removeBtn);
    gallery.appendChild(wrapper);

    imagesLoaded(wrapper, () => {
      msnry.appended(wrapper);
      msnry.layout();
    });
  }

  window.lucide.createIcons();
});
