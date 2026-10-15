// Applies the theme saved by the top-bar button before the first paint, so a
// light choice doesn't flash dark. (The CSP forbids inline scripts.)
"use strict";
try {
  const saved = localStorage.getItem("sprintwarden.theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
} catch (_) { /* storage may be unavailable */ }
