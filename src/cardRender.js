export function cardArtUrl(card) {
  return card.image_uris && card.image_uris.art_crop;
}

// Scryfall's art_crop bounding box is wrong for a handful of cards (rules
// text / type-line bar baked into the jpeg) — spotted on Summon: Choco/Mog.
// top/bottom are fractions of the source image height to keep.
const ART_CROP_OVERRIDES = {
  '00546117-018a-4286-bc20-b5446c5be56f': { top: 0.13, bottom: 0.9 }, // Summon: Choco/Mog (FIN)
  'b95481b1-1780-4cf9-b910-dd0a4461f818': { top: 0, bottom: 0.9 }, // Summon: Choco/Mog (FIN alt art)
};

function applyArtCropOverride(img, cardId) {
  const crop = ART_CROP_OVERRIDES[cardId];
  if (!crop) return;
  img.addEventListener(
    'load',
    () => {
      const visibleFraction = crop.bottom - crop.top;
      const croppedFraction = 1 - visibleFraction;
      const positionY = croppedFraction > 0 ? (crop.top / croppedFraction) * 100 : 50;
      img.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight * visibleFraction}`;
      img.style.objectFit = 'cover';
      img.style.objectPosition = `50% ${positionY}%`;
    },
    { once: true }
  );
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
  applyArtCropOverride(img, card.id);
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
