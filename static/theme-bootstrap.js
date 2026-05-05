// Theme bootstrap — runs synchronously in <head> before the stylesheet
// loads, so the page never flashes the default palette.
// Kept out of app.js so it can run before the rest of the JS parses,
// and out of inline script tags so the CSP can forbid 'unsafe-inline'.
//
// "auto" mode resolves to dark/light based on the OS preference at boot.
// app.js wires up a media-query listener for live changes after load.
(function () {
  try {
    var t = localStorage.getItem("clientctl-theme") || "dark";
    if (t === "auto") {
      var prefersDark = window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: dark)").matches;
      t = prefersDark ? "dark" : "light";
    }
    document.documentElement.dataset.theme = t;
  } catch (e) { /* localStorage unavailable — fall back to CSS default */ }
})();
