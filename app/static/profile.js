fetch('/api/settings').then(response => response.ok ? response.json() : null).then(settings => {
  if (!settings) return;
  const profile = document.querySelector('.main-nav .profile');
  if (!profile) return;
  profile.querySelector('strong').textContent = settings.user_name;
  profile.querySelector('small').textContent = settings.email;
  const avatar = profile.querySelector('.avatar');
  if (settings.has_avatar) { avatar.textContent = ''; avatar.style.background = 'center / cover url(/api/settings/avatar)'; }
  else avatar.textContent = settings.user_name.slice(0, 1).toUpperCase();
}).catch(() => {});
