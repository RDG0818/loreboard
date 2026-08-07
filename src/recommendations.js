import imagesLoaded from 'imagesloaded';
import { cardArtUrl, createCardWrapper, createSaveToggler } from './cardRender.js';
import { initSidebarToggle } from './sidebar.js';
import { initSignInLink } from './authStatus.js';
import { apiFetch, fetchSavedCardIds, createMasonry } from './api.js';

const API_BASE = '';

document.addEventListener('DOMContentLoaded', async () => {
  initSidebarToggle();
  initSignInLink(API_BASE);
  const gallery = document.getElementById('recommendations-gallery');
  const messageEl = document.getElementById('recommendations-message');

  let body;
  try {
    const response = await apiFetch(API_BASE, '/api/v1/recommendations', { credentials: 'include' });
    if (response.status === 401) return;
    body = await response.json();
  } catch (error) {
    messageEl.textContent = 'Could not load recommendations.';
    return;
  }

  const savedCardIds = await fetchSavedCardIds(API_BASE);
  const toggleSave = createSaveToggler(API_BASE, savedCardIds);

  if (body.message) {
    messageEl.textContent = body.message;
  }
  if (!body.recommendations || body.recommendations.length === 0) {
    if (!messageEl.textContent) {
      messageEl.textContent = 'No recommendations yet.';
    }
    return;
  }

  const msnry = createMasonry(gallery);
  window.addEventListener('sidebar:layout-change', () => msnry.layout());

  for (const card of body.recommendations) {
    const artUrl = cardArtUrl(card);
    if (!artUrl) continue;
    const wrapper = createCardWrapper(card, { savedCardIds, onToggleSave: toggleSave });
    gallery.appendChild(wrapper);
    await new Promise((resolve) => imagesLoaded(wrapper).on('always', resolve));
    msnry.appended(wrapper);
    msnry.layout();
  }

  window.lucide.createIcons();
});
