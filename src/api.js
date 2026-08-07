import Packery from 'packery';

export async function apiFetch(apiBase, path, options) {
  const response = await fetch(`${apiBase}${path}`, options);
  if (response.status === 401) {
    window.location.href = `${apiBase}/auth/login/google`;
  }
  return response;
}

export async function fetchSavedCardIds(apiBase) {
  try {
    const response = await fetch(`${apiBase}/api/v1/saves`, { credentials: 'include' });
    if (!response.ok) return new Set();
    const saves = await response.json();
    return new Set(saves.map((c) => c.id));
  } catch (error) {
    return new Set();
  }
}

export function createMasonry(gallery) {
  return new Packery(gallery, {
    itemSelector: '.image-wrapper',
    columnWidth: '.image-wrapper',
    gutter: 15,
  });
}
