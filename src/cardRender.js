export function cardArtUrl(card) {
  return card.image_uris && card.image_uris.art_crop;
}

function setSaveBtnState(btn, isSaved) {
  btn.textContent = isSaved ? 'Saved' : 'Save';
  btn.classList.toggle('saved', isSaved);
}

export function createSaveToggler(apiBase, savedCardIds) {
  return async function toggleSave(cardId, shouldSave) {
    const method = shouldSave ? 'POST' : 'DELETE';
    const url = shouldSave ? `${apiBase}/api/v1/saves` : `${apiBase}/api/v1/saves/${cardId}`;
    const response = await fetch(url, {
      method,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: shouldSave ? JSON.stringify({ card_id: cardId }) : undefined,
    });

    if (response.status === 401) {
      window.location.href = `${apiBase}/auth/login/google`;
      return false;
    }
    if (!response.ok) return false;

    if (shouldSave) savedCardIds.add(cardId);
    else savedCardIds.delete(cardId);
    return true;
  };
}

export function createCardWrapper(card, { savedCardIds, onToggleSave } = {}) {
  const wrapper = document.createElement('div');
  wrapper.classList.add('image-wrapper');
  wrapper.dataset.cardId = card.id;

  const img = document.createElement('img');
  img.src = cardArtUrl(card);

  const overlay = document.createElement('div');
  overlay.classList.add('overlay');

  const artistLabel = document.createElement('span');
  artistLabel.classList.add('artist-label');
  artistLabel.textContent = card.artist || '';

  wrapper.appendChild(img);
  wrapper.appendChild(overlay);
  wrapper.appendChild(artistLabel);

  if (onToggleSave) {
    const saveBtn = document.createElement('button');
    saveBtn.classList.add('save-btn');
    setSaveBtnState(saveBtn, Boolean(savedCardIds && savedCardIds.has(card.id)));

    saveBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const shouldSave = !saveBtn.classList.contains('saved');
      try {
        const ok = await onToggleSave(card.id, shouldSave);
        if (!ok) return;
        setSaveBtnState(saveBtn, shouldSave);
        saveBtn.classList.add('pulse');
        setTimeout(() => saveBtn.classList.remove('pulse'), 150);
      } catch (error) {
        console.error('Failed to update save state:', error);
      }
    });

    wrapper.appendChild(saveBtn);
  }

  return wrapper;
}
