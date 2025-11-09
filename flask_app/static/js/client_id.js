(function () {
  const cookieName = 'client_id';

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
    document.cookie = `${name}=${encodeURIComponent(value)}; max-age=${maxAge}; path=/; SameSite=Lax`;
  };

  const generateId = () => {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
      const buffer = new Uint8Array(16);
      window.crypto.getRandomValues(buffer);
      return Array.from(buffer, (byte) => byte.toString(16).padStart(2, '0')).join('');
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  };

  if (!getCookie(cookieName)) {
    const tenYearsInSeconds = 60 * 60 * 24 * 365 * 10;
    setCookie(cookieName, generateId(), tenYearsInSeconds);
  }
})();
