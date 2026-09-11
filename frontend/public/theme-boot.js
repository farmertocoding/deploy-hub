(function () {
  var KEY = "deploy-hub.appearance.v1";
  var stored = null;
  try {
    stored = localStorage.getItem(KEY);
  } catch (_storage) {
    stored = null;
  }
  if (stored !== "dark" && stored !== "light" && stored !== "system") stored = null;
  var theme;
  if (stored === "dark" || stored === "light") theme = stored;
  else {
    var prefers = false;
    try {
      prefers = window.matchMedia("(prefers-color-scheme: dark)").matches;
    } catch (_media) {
      prefers = false;
    }
    theme = prefers ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
