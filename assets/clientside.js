/*
  clientside.js — Auto-scroll log window to bottom on content change
*/
window.dash_clientside = window.dash_clientside || {};

window.dash_clientside.clientside = {
  // Called by a clientside callback to auto-scroll the log window
  autoScrollLog: function(children) {
    const el = document.getElementById("log-output");
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
    return window.dash_clientside.no_update;
  }
};

// Also wire up a MutationObserver as a safety net
document.addEventListener("DOMContentLoaded", function () {
  const observer = new MutationObserver(function () {
    const log = document.getElementById("log-output");
    if (log) {
      log.scrollTop = log.scrollHeight;
    }
  });

  // Start observing once the element appears
  const tryObserve = setInterval(function () {
    const log = document.getElementById("log-output");
    if (log) {
      observer.observe(log, { childList: true, subtree: true, characterData: true });
      clearInterval(tryObserve);
    }
  }, 500);
});
