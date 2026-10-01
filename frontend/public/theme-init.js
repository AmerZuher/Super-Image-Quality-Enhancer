// Apply the saved theme before first paint so there is no flash of the wrong theme.
(() => {
  try {
    const theme = JSON.parse(localStorage.getItem("siqe-ui") || "{}").state?.theme;
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  } catch {
    // Storage blocked or corrupt: fall back to the system theme.
  }
})();
