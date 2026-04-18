/**
 * Koha OPAC Chat Widget Embed Script
 *
 * Drop this into Koha's OPACUserJS system preference or include it via
 * a <script> tag in the OPAC HTML customisation.
 *
 * Configuration:
 *   Set CHATBOT_URL to the base URL where the chatbot backend is running.
 *   Example: "https://chatbot.mylibrary.org"
 */
(function () {
  "use strict";

  // ---- CONFIGURATION ----
  // Base path for the chatbot when served through a reverse proxy.
  // If proxied at /chatbot/, set this to "/chatbot".
  // If the chatbot runs on its own domain, use the full URL instead.
  var CHATBOT_URL = "/chatbot";

  // ---- Prevent double-init ----
  if (document.getElementById("library-chatbot-fab")) return;

  // ---- Styles ----
  var style = document.createElement("style");
  style.textContent =
    "#library-chatbot-fab{position:fixed;bottom:24px;right:24px;z-index:99999;" +
    "width:56px;height:56px;border-radius:50%;background:#3a506b;color:#fff;" +
    "border:none;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.25);" +
    "font-size:28px;display:flex;align-items:center;justify-content:center;" +
    "transition:transform .2s,background .2s}" +
    "#library-chatbot-fab:hover{background:#2c3e50;transform:scale(1.08)}" +
    "#library-chatbot-frame-wrap{position:fixed;bottom:92px;right:24px;z-index:99998;" +
    "width:400px;height:560px;max-width:calc(100vw - 32px);max-height:calc(100vh - 120px);" +
    "border-radius:12px;overflow:hidden;box-shadow:0 8px 32px rgba(0,0,0,.2);" +
    "display:none;background:#fff}" +
    "#library-chatbot-frame-wrap.open{display:block}" +
    "#library-chatbot-frame{width:100%;height:100%;border:none}" +
    "@media(max-width:480px){#library-chatbot-frame-wrap{bottom:0;right:0;" +
    "width:100vw;height:100vh;max-width:100vw;max-height:100vh;border-radius:0}" +
    "#library-chatbot-fab{bottom:16px;right:16px}}";
  document.head.appendChild(style);

  // ---- Floating Action Button ----
  var fab = document.createElement("button");
  fab.id = "library-chatbot-fab";
  fab.setAttribute("aria-label", "Open library chat assistant");
  fab.innerHTML = "&#128218;";
  document.body.appendChild(fab);

  // ---- iframe wrapper ----
  var wrap = document.createElement("div");
  wrap.id = "library-chatbot-frame-wrap";
  wrap.setAttribute("role", "dialog");
  wrap.setAttribute("aria-label", "Library chat assistant");

  var iframe = document.createElement("iframe");
  iframe.id = "library-chatbot-frame";
  iframe.title = "Library Chat Assistant";
  iframe.setAttribute("loading", "lazy");
  // The iframe loads the standalone widget page from the chatbot server.
  iframe.src = CHATBOT_URL + "/static/index.html";
  wrap.appendChild(iframe);
  document.body.appendChild(wrap);

  // ---- Toggle open/close ----
  var isOpen = false;
  fab.addEventListener("click", function () {
    isOpen = !isOpen;
    wrap.classList.toggle("open", isOpen);
    fab.innerHTML = isOpen ? "&#10005;" : "&#128218;";
    fab.setAttribute(
      "aria-label",
      isOpen ? "Close library chat assistant" : "Open library chat assistant"
    );
  });

  // Close on Escape key
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && isOpen) {
      isOpen = false;
      wrap.classList.remove("open");
      fab.innerHTML = "&#128218;";
      fab.setAttribute("aria-label", "Open library chat assistant");
      fab.focus();
    }
  });
})();
