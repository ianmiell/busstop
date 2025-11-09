(function () {
  const container = document.getElementById('all_stops');
  if (!container) {
    return;
  }

  const FIVE_SECONDS = 5000;
  const ONE_MINUTE = 60000;
  let reloadTimer = null;
  let observer = null;

  const hasContent = () => {
    return container.querySelector('.line-row, #stop_name, #no_info') !== null;
  };

  const scheduleReload = (delay) => {
    if (reloadTimer) {
      clearTimeout(reloadTimer);
    }
    reloadTimer = setTimeout(() => {
      window.location.reload();
    }, delay);
  };

  const switchToMinuteRefresh = () => {
    scheduleReload(ONE_MINUTE);
    if (observer) {
      observer.disconnect();
      observer = null;
    }
  };

  if (hasContent()) {
    switchToMinuteRefresh();
    return;
  }

  scheduleReload(FIVE_SECONDS);

  observer = new MutationObserver(() => {
    if (hasContent()) {
      switchToMinuteRefresh();
    }
  });

  observer.observe(container, {
    childList: true,
    subtree: true,
    characterData: true
  });
})();
