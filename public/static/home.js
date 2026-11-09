(() => {
  const btn = document.getElementById('locate');
  const msg = document.getElementById('locate-msg');
  if (!btn) return;
  btn.addEventListener('click', () => {
    if (!navigator.geolocation) { msg.textContent = 'Your browser cannot share its location.'; return; }
    msg.textContent = 'Finding you…';
    navigator.geolocation.getCurrentPosition(
      (p) => {
        const q = new URLSearchParams({ lat: p.coords.latitude.toFixed(4), lon: p.coords.longitude.toFixed(4), name: 'My location' });
        location.href = '/forecast/overview?' + q;
      },
      () => { msg.textContent = 'Location is blocked. Search for your city instead.'; },
      { timeout: 8000, maximumAge: 600000 }
    );
  });
})();
