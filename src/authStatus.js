// Backend only exposes `email` (no name/picture — see /api/v1/me), so the
// avatar is a plain letter circle rather than a photo.
function buildProfileMenu(apiBase, email) {
  const header = document.querySelector('.page-header');
  if (!header) return;

  const menu = document.createElement('div');
  menu.className = 'profile-menu';

  const avatar = document.createElement('button');
  avatar.type = 'button';
  avatar.className = 'profile-avatar';
  avatar.textContent = (email || '?').charAt(0).toUpperCase();
  avatar.setAttribute('aria-label', 'Account menu');

  const dropdown = document.createElement('div');
  dropdown.className = 'profile-dropdown';

  const row = document.createElement('div');
  row.className = 'profile-dropdown-row';

  const avatarLarge = document.createElement('div');
  avatarLarge.className = 'profile-avatar-large';
  avatarLarge.textContent = (email || '?').charAt(0).toUpperCase();

  const emailLine = document.createElement('p');
  emailLine.className = 'profile-email';
  emailLine.textContent = email;
  emailLine.title = email; // full address on hover — the row itself truncates it

  row.appendChild(avatarLarge);
  row.appendChild(emailLine);

  const divider = document.createElement('div');
  divider.className = 'profile-divider';

  const signOutBtn = document.createElement('button');
  signOutBtn.type = 'button';
  signOutBtn.className = 'profile-signout';
  signOutBtn.textContent = 'Log out';
  signOutBtn.addEventListener('click', async () => {
    try {
      await fetch(`${apiBase}/auth/logout`, { method: 'POST', credentials: 'include' });
    } catch (error) {
      // best-effort — reload regardless so the logged-in UI doesn't linger client-side
    }
    window.location.reload();
  });

  avatar.addEventListener('click', (e) => {
    e.stopPropagation();
    dropdown.classList.toggle('show');
  });
  document.addEventListener('click', (e) => {
    if (!menu.contains(e.target)) dropdown.classList.remove('show');
  });

  dropdown.appendChild(row);
  dropdown.appendChild(divider);
  dropdown.appendChild(signOutBtn);
  menu.appendChild(avatar);
  menu.appendChild(dropdown);
  header.appendChild(menu);
}

export async function initSignInLink(apiBase = '') {
  const el = document.getElementById('sidebar-signin');

  try {
    const response = await fetch(`${apiBase}/api/v1/me`, { credentials: 'include' });
    if (!response.ok) return;
    const data = await response.json();
    if (data.logged_in) {
      buildProfileMenu(apiBase, data.email);
    } else if (el) {
      el.classList.add('show');
    }
  } catch (error) {
    // Backend unreachable — leave the sign-in link hidden; feed still works logged-out.
  }
}
