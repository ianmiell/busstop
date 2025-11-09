(function () {
  const button = document.getElementById('share-location-btn');
  const statusEl = document.getElementById('location-status');
  const cookieName = 'user_location';

  if (!button || !statusEl) {
    return;
  }

  const getCookie = (name) => {
    const cookies = document.cookie ? document.cookie.split('; ') : [];
    for (const entry of cookies) {
      const [key, value] = entry.split('=');
      if (key === name) {
        return decodeURIComponent(value);
      }
    }
    return null;
  };

  const setCookie = (name, value, maxAge) => {
    const cookie = `${name}=${encodeURIComponent(value)}; max-age=${maxAge}; path=/; SameSite=Lax`;
    document.cookie = cookie;
  };

  const setStatus = (message) => {
    statusEl.textContent = message;
  };

  const updateStatusFromCookie = () => {
    if (getCookie(cookieName)) {
      button.textContent = 'Update my location';
      setStatus('Location saved.');
    }
  };

  const sendLocationToServer = (coords) => {
    return fetch('/api/location', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        lat: coords.latitude,
        lon: coords.longitude
      })
    }).then((response) => {
      if (!response.ok) {
        throw new Error('Server rejected location');
      }
      return response.json();
    });
  };

  const requestLocation = () => {
    if (!navigator.geolocation) {
      setStatus('Geolocation not supported in this browser.');
      return;
    }

    button.disabled = true;
    setStatus('Requesting location...');

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const coordsValue = `${position.coords.latitude.toFixed(6)},${position.coords.longitude.toFixed(6)}`;
        setCookie(cookieName, coordsValue, 600);
        sendLocationToServer(position.coords)
          .then(() => {
            setStatus('Location saved.');
            button.textContent = 'Update my location';
          })
          .catch((error) => {
            console.error(error);
            setStatus('Unable to save location.');
          })
          .finally(() => {
            button.disabled = false;
          });
      },
      (error) => {
        console.error(error);
        switch (error.code) {
          case error.PERMISSION_DENIED:
            setStatus('Permission denied.');
            break;
          case error.POSITION_UNAVAILABLE:
            setStatus('Location unavailable.');
            break;
          case error.TIMEOUT:
            setStatus('Location request timed out.');
            break;
          default:
            setStatus('Unable to obtain location.');
        }
        button.disabled = false;
      },
      {
        enableHighAccuracy: false,
        timeout: 10000,
        maximumAge: 60000
      }
    );
  };

  button.addEventListener('click', requestLocation);
  updateStatusFromCookie();
})();
