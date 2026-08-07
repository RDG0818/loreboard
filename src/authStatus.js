export async function initSignInLink(apiBase = '') {
  const el = document.getElementById('sidebar-signin');
  if (!el) return;

  try {
    const response = await fetch(`${apiBase}/api/v1/me`, { credentials: 'include' });
    if (!response.ok) return;
    const data = await response.json();
    if (!data.logged_in) el.classList.add('show');
  } catch (error) {
    // Backend unreachable — leave the sign-in link hidden; feed still works logged-out.
  }
}
