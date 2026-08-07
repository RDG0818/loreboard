import Masonry from 'masonry-layout';
import imagesLoaded from 'imagesloaded';

const API_BASE = 'http://127.0.0.1:8000';

document.addEventListener('DOMContentLoaded', async () => {
  const gallery = document.getElementById('recommendations-gallery');
  const messageEl = document.getElementById('recommendations-message');

  let body;
  try {
    const response = await fetch(`${API_BASE}/api/v1/recommendations`, { credentials: 'include' });
    if (response.status === 401) {
      window.location.href = `${API_BASE}/auth/login/google`;
      return;
    }
    body = await response.json();
  } catch (error) {
    messageEl.textContent = 'Could not load recommendations.';
    return;
  }

  if (body.message) {
    messageEl.textContent = body.message;
  }
  if (!body.recommendations || body.recommendations.length === 0) {
    if (!messageEl.textContent) {
      messageEl.textContent = 'No recommendations yet.';
    }
    return;
  }

  const msnry = new Masonry(gallery, {
    itemSelector: '.image-wrapper',
    columnWidth: '.image-wrapper',
    gutter: 15,
  });

  for (const card of body.recommendations) {
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
    msnry.appended(wrapper);
    msnry.layout();
  }

  window.lucide.createIcons();
});
