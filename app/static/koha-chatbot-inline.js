/**
 * Library AI Chatbot — Inline Embed for Koha OPACUserJS
 *
 * Paste this entire file into OPACUserJS, or load it via:
 *   (function(){ var s=document.createElement("script");
 *     s.src="/chatbot/static/koha-chatbot-inline.js";
 *     document.body.appendChild(s); })();
 *
 * CONFIGURATION: Set CHATBOT_API below to your chatbot backend URL.
 */
(function () {
  "use strict";
  var CHATBOT_API = "/chatbot";
  // Auto-detect: when served from Vercel, use same origin (empty string = relative).
  // When embedded on an external site (like Koha), use the script's own origin.
  if (window.location.hostname.includes("vercel.app")) {
    CHATBOT_API = "";
  } else {
    // Detect the origin from the script tag's src attribute
    try {
      var scripts = document.getElementsByTagName("script");
      for (var i = scripts.length - 1; i >= 0; i--) {
        var src = scripts[i].src || "";
        if (src.indexOf("koha-chatbot-inline") !== -1) {
          CHATBOT_API = src.replace(/\/static\/koha-chatbot-inline\.js.*$/, "");
          break;
        }
      }
    } catch (e) {}
  }
  // Don't init inside iframes that we created (prevents infinite nesting)
  // but allow init on normal Koha pages even if they happen to be framed
  try {
    if (window !== window.top && window.frameElement && window.frameElement.id === "lc-detail-frame") return;
  } catch(e) {}
  if (document.getElementById("lc-fab")) return;

  var css = document.createElement("style");
  css.textContent =
    "#lc-fab{position:fixed;bottom:24px;right:24px;z-index:100000;" +
    "width:56px;height:56px;border-radius:50%;background:#0E553F;color:#fff;" +
    "border:none;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.25);" +
    "font-size:28px;display:flex;align-items:center;justify-content:center;" +
    "transition:transform .2s,background .2s}" +
    "#lc-fab:hover{background:#0a3f2e;transform:scale(1.08)}" +
    "#lc-wrap{position:fixed;bottom:92px;right:24px;z-index:99999;" +
    "width:400px;height:560px;max-width:calc(100vw - 32px);" +
    "max-height:calc(100vh - 120px);border-radius:12px;overflow:hidden;" +
    "box-shadow:0 8px 32px rgba(0,0,0,.2);display:none;background:#fff;" +
    "flex-direction:column;font-family:-apple-system,BlinkMacSystemFont," +
    "'Segoe UI',Roboto,Helvetica,Arial,sans-serif}" +
    "#lc-wrap.open{display:flex}" +
    "#lc-hdr{background:#0E553F;color:#fff;padding:14px 18px;" +
    "font-size:1.05rem;font-weight:600;display:flex;align-items:center;" +
    "gap:10px;flex-shrink:0}" +
    "#lc-new{background:none;border:1px solid rgba(255,255,255,.4);color:#fff;" +
    "border-radius:14px;padding:4px 12px;font-size:.75rem;cursor:pointer;" +
    "margin-left:auto;transition:background .15s}" +
    "#lc-new:hover{background:rgba(255,255,255,.15)}" +
    "#lc-msgs{flex:1;overflow-y:auto;padding:14px;display:flex;" +
    "flex-direction:column;gap:8px;background:#fff}" +
    ".lc-m{max-width:80%;padding:10px 14px;border-radius:16px;" +
    "font-size:.93rem;line-height:1.45;word-wrap:break-word;white-space:pre-wrap}" +
    ".lc-m.u{align-self:flex-end;background:#0E553F;color:#fff;" +
    "border-bottom-right-radius:4px}" +
    ".lc-m.b{align-self:flex-start;background:#f0f0ec;color:#2d2d2d;" +
    "border-bottom-left-radius:4px}" +
    ".lc-fb{display:flex;gap:4px;margin-top:6px}" +
    ".lc-fb button{background:none;border:1px solid #ccc;border-radius:12px;" +
    "padding:2px 8px;font-size:.78rem;cursor:pointer;color:#777;transition:all .15s;line-height:1.4}" +
    ".lc-fb button:hover{border-color:#0E553F;color:#0E553F}" +
    ".lc-fb button.voted{border-color:#0E553F;color:#0E553F;font-weight:600}" +
    ".lc-fb button:disabled{opacity:.5;cursor:default}" +
    ".lc-handoff-rate{display:flex;gap:8px;justify-content:center}" +
    ".lc-rate-btn{background:#fff;border:1px solid #ccc;border-radius:18px;" +
    "padding:8px 16px;font-size:.88rem;cursor:pointer;transition:all .15s}" +
    ".lc-rate-btn:hover{border-color:#0E553F;background:#f0fdf4}" +
    ".lc-m.e{align-self:center;background:#fce4e4;color:#a94442;" +
    "border-radius:8px;font-size:.85rem;text-align:center}" +
    ".lc-t{align-self:flex-start;display:flex;align-items:center;gap:8px;padding:10px 14px;" +
    "background:#f0f0ec;border-radius:16px;border-bottom-left-radius:4px;color:#888;font-size:.82rem}" +
    ".lc-spinner{width:18px;height:18px;border:2.5px solid #ddd;border-top-color:#D4A017;" +
    "border-radius:50%;animation:lcSpin .7s linear infinite}" +
    "@keyframes lcSpin{to{transform:rotate(360deg)}}" +
    "#lc-bar{display:flex;padding:10px;gap:8px;border-top:1px solid #e0e0e0;" +
    "background:#fff;flex-shrink:0}" +
    "#lc-in{flex:1;padding:10px 14px;border:1px solid #ccc;border-radius:20px;" +
    "font-size:.93rem;outline:none;text-align:left}" +
    "#lc-in:focus{border-color:#0E553F}" +
    "#lc-go{background:#D4A017;color:#fff;border:none;border-radius:50%;" +
    "width:40px;height:40px;cursor:pointer;display:flex;align-items:center;" +
    "justify-content:center;font-size:1.1rem;flex-shrink:0}" +
    "#lc-go:hover{background:#b8890f}" +
    "#lc-go:disabled{background:#a0aab4;cursor:not-allowed}" +
    ".lc-w{text-align:center;color:#555;font-size:.88rem;padding:18px 10px;" +
    "line-height:1.5}" +
    ".lc-faqs{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;padding:8px 10px 14px}" +
    ".lc-faq{background:#fff;color:#0E553F;border:1px solid #D4A017;border-radius:18px;" +
    "padding:7px 14px;font-size:.82rem;cursor:pointer;transition:background .15s,border-color .15s;" +
    "line-height:1.3;text-align:left}" +
    ".lc-faq:hover{background:#fdf6e3;border-color:#b8890f}" +
    // Catalog result cards
    ".lc-results{display:flex;flex-direction:column;gap:8px;width:100%;max-width:95%;align-self:flex-start}" +
    ".lc-results-header{font-size:.88rem;color:#555;padding:4px 0}" +
    ".lc-card{background:#fff;border:1px solid #e0e0e0;border-radius:10px;padding:10px 12px;" +
    "display:flex;flex-direction:column;gap:6px;transition:border-color .15s}" +
    ".lc-card:hover{border-color:#0E553F}" +
    ".lc-card-title{font-size:.88rem;font-weight:600;color:#2d2d2d;line-height:1.3}" +
    ".lc-card-author{font-size:.78rem;color:#666}" +
    ".lc-card-btn{display:inline-block;background:#0E553F!important;color:#fff!important;border:none;border-radius:14px;" +
    "padding:5px 14px;font-size:.76rem;cursor:pointer;text-decoration:none!important;" +
    "text-align:center;transition:background .15s;align-self:flex-start}" +
    ".lc-card-btn:hover{background:#0a3f2e!important}" +
    ".lc-pager{display:flex;flex-direction:column;align-items:center;gap:4px;padding:6px 0}" +
    ".lc-pager-row{display:flex;align-items:center;gap:6px}" +
    ".lc-pager-btn{background:#fff;border:1px solid #ccc;border-radius:14px;" +
    "padding:4px 12px;font-size:.78rem;cursor:pointer;color:#0E553F;transition:all .15s}" +
    ".lc-pager-btn:hover{background:#f0fdf4;border-color:#0E553F}" +
    ".lc-pager-btn:disabled{opacity:.4;cursor:default;background:#fff}" +
    ".lc-pager-btn.active{background:#0E553F;color:#fff;border-color:#0E553F}" +
    ".lc-pager-info{font-size:.75rem;color:#888}" +
    "#lc-librarian{background:none;border:1px solid rgba(255,255,255,.4);color:#fff;" +
    "border-radius:14px;padding:4px 10px;font-size:.72rem;cursor:pointer;" +
    "transition:background .15s;white-space:nowrap}" +
    "#lc-librarian:hover{background:rgba(255,255,255,.15)}" +
    "@media(max-width:480px){#lc-wrap{bottom:0;right:0;width:100vw;" +
    "height:100vh;max-width:100vw;max-height:100vh;border-radius:0}" +
    "#lc-fab{bottom:16px;right:16px}}";
  document.head.appendChild(css);

  // FAB
  var fab = document.createElement("button");
  fab.id = "lc-fab";
  fab.setAttribute("aria-label", "Open library chat assistant");
  fab.innerHTML = "&#128218;";
  document.body.appendChild(fab);

  // Chat panel
  var wrap = document.createElement("div");
  wrap.id = "lc-wrap";
  wrap.setAttribute("role", "dialog");
  wrap.setAttribute("aria-label", "Library chat assistant");
  wrap.innerHTML =
    '<div id="lc-hdr"><span aria-hidden="true">&#128218;</span> Hero — Library Assistant<button id="lc-librarian" aria-label="Talk to a librarian">&#128172; Librarian</button><button id="lc-new" aria-label="Start new chat">New Chat</button></div>' +
    '<div id="lc-msgs" role="log" aria-live="polite">' +
    '<div class="lc-w">Hi, I\'m Hero! 👋 I can help you find books, check hours, or answer questions about the library. What can I do for you?</div>' +
    '<div class="lc-faqs">' +
    '<button class="lc-faq" data-q="What are the library hours?">&#128336; Library hours</button>' +
    '<button class="lc-faq" data-q="What is the borrowing limit?">&#128214; Borrowing limit</button>' +
    '<button class="lc-faq" data-q="How do I renew a book?">&#128260; Renew a book</button>' +
    '<button class="lc-faq" data-q="What are the overdue fines?">&#128176; Overdue fines</button>' +
    '<button class="lc-faq" data-q="What happens if I lose a book?">&#128269; Lost book</button>' +
    '</div>' +
    '</div>' +
    '<div id="lc-bar">' +
    '<input type="text" id="lc-in" placeholder="Ask me about the library..." autocomplete="off" aria-label="Type your message">' +
    '<button id="lc-go" aria-label="Send message" disabled>&#10148;</button>' +
    '</div>';
  document.body.appendChild(wrap);

  var msgs = document.getElementById("lc-msgs");
  var inp = document.getElementById("lc-in");
  var btn = document.getElementById("lc-go");

  // Session — persist across page navigations
  var STORE_KEY = "lc_chat";
  var STORE_VER = 2; // bump to clear stale data
  var stored = {};
  try {
    var raw = JSON.parse(sessionStorage.getItem(STORE_KEY)) || {};
    if (raw.ver === STORE_VER) stored = raw;
  } catch(e) {}
  var sid = stored.sid || ((typeof crypto !== "undefined" && crypto.randomUUID)
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
        var r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      }));
  var chatHistory = stored.history || []; // [{text, cls}]
  var wasOpen = stored.open !== undefined ? stored.open : true;

  function saveState() {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify({
        ver: STORE_VER, sid: sid, history: chatHistory.slice(-40), open: open
      }));
    } catch(e) {}
  }

  // Restore previous messages
  if (chatHistory.length > 0) {
    var w = msgs.querySelector(".lc-w"); if (w) w.remove();
    var fq = msgs.querySelector(".lc-faqs"); if (fq) fq.remove();
    chatHistory.forEach(function(m) { addMsgRaw(m.text, m.cls, m.ts); });
  }

  // Check if the existing session has expired — auto-reset to new chat
  if (chatHistory.length > 0 && sid) {
    fetch(CHATBOT_API + "/api/session-status/" + encodeURIComponent(sid))
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.status === "expired" || d.status === "not_found") {
          resetToNewChat();
        }
      })
      .catch(function() {});
  }

  // Toggle — restore previous state
  var open = wasOpen;
  if (open) {
    wrap.classList.add("open");
    fab.innerHTML = "&#10005;";
    fab.setAttribute("aria-label", "Close chat");
  }

  // Scroll to bottom after everything is rendered and visible
  if (chatHistory.length > 0 && open) {
    // Multiple attempts to ensure scroll works across all browsers
    function scrollToBottom() { msgs.scrollTop = msgs.scrollHeight; }
    scrollToBottom();
    setTimeout(scrollToBottom, 100);
    setTimeout(scrollToBottom, 300);
    window.addEventListener("load", scrollToBottom);
  }
  fab.addEventListener("click", function () {
    open = !open;
    wrap.classList.toggle("open", open);
    fab.innerHTML = open ? "&#10005;" : "&#128218;";
    fab.setAttribute("aria-label", open ? "Close chat" : "Open library chat assistant");
    if (open) {
      inp.focus();
      setTimeout(function() { msgs.scrollTop = msgs.scrollHeight; }, 50);
    }
    saveState();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && open) {
      open = false; wrap.classList.remove("open");
      fab.innerHTML = "&#128218;";
      fab.setAttribute("aria-label", "Open library chat assistant");
      fab.focus();
    }
  });

  // Helpers
  function scroll() { msgs.scrollTop = msgs.scrollHeight; }
  function renderMsg(t, c, ts) {
    var d = document.createElement("div"); d.className = "lc-m " + c;
    // Check if this is a catalog result message — render as cards
    if (c === "b" && t && t.indexOf("found in the catalog") !== -1) {
      return renderCatalogCards(t, ts);
    }
    var html = t.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
      '<a href="$2" class="lc-link" style="color:inherit;text-decoration:underline;cursor:pointer">$1</a>');
    html = html.replace(/(^|[^"'])(https?:\/\/[^\s<]+)/g,
      '$1<a href="$2" class="lc-link" style="color:inherit;text-decoration:underline;cursor:pointer">$2</a>');
    d.innerHTML = html;
    // Add feedback buttons for bot messages
    if (c === "b" && ts) {
      var fb = document.createElement("div"); fb.className = "lc-fb";
      var up = document.createElement("button"); up.innerHTML = "&#128077;"; up.setAttribute("aria-label", "Helpful");
      var down = document.createElement("button"); down.innerHTML = "&#128078;"; down.setAttribute("aria-label", "Not helpful");
      function vote(rating, btn, other) {
        btn.classList.add("voted"); btn.disabled = true; other.disabled = true;
        fetch(CHATBOT_API + "/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sid, message_timestamp: ts, rating: rating })
        }).catch(function(){});
      }
      up.addEventListener("click", function() { vote(1, up, down); });
      down.addEventListener("click", function() { vote(-1, down, up); });
      fb.appendChild(up); fb.appendChild(down);
      d.appendChild(fb);
    }
    d.querySelectorAll("a.lc-link").forEach(function(a) {
      a.addEventListener("click", function(e) {
        e.preventDefault();
        e.stopPropagation();
        window.location.href = a.href;
      });
    });
    return d;
  }
  function renderCatalogCards(text, ts) {
    var d = document.createElement("div"); d.className = "lc-m b";
    d.style.cssText = "max-width:80%;white-space:normal";
    var wrap = document.createElement("div"); wrap.className = "lc-results";
    wrap.style.cssText = "width:100%";
    var lines = text.split("\n");
    var headerDiv = document.createElement("div"); headerDiv.className = "lc-results-header";
    headerDiv.textContent = "📚 Here's what I found in the catalog:";
    wrap.appendChild(headerDiv);

    // Parse all cards from text
    var allCards = [];
    var currentTitle = "", currentAuthor = "", currentUrl = "";
    function collectCard() {
      if (!currentTitle) return;
      allCards.push({ title: currentTitle, author: currentAuthor, url: currentUrl });
      currentTitle = ""; currentAuthor = ""; currentUrl = "";
    }
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      var numMatch = line.match(/^\d+\.\s+(.+?)(?:\s+by\s+(.+))?$/);
      if (numMatch && line.indexOf("View in catalog") === -1) {
        collectCard();
        currentTitle = numMatch[1] || "";
        currentAuthor = numMatch[2] || "";
        if (!currentAuthor && currentTitle.match(/\s+by\s*$/)) {
          currentTitle = currentTitle.replace(/\s+by\s*$/, "");
        }
      } else if (line.indexOf("View in catalog:") !== -1) {
        var urlMatch = line.match(/https?:\/\/[^\s]+/);
        if (urlMatch) currentUrl = urlMatch[0];
      }
    }
    collectCard();

    // Pagination
    var PAGE_SIZE = 3;
    var currentPage = 0;
    var totalPages = Math.ceil(allCards.length / PAGE_SIZE);

    var cardsContainer = document.createElement("div");
    cardsContainer.style.cssText = "display:flex;flex-direction:column;gap:8px";
    wrap.appendChild(cardsContainer);

    var pagerDiv = document.createElement("div"); pagerDiv.className = "lc-pager";
    if (totalPages > 1) wrap.appendChild(pagerDiv);

    function renderPage() {
      cardsContainer.innerHTML = "";
      var start = currentPage * PAGE_SIZE;
      var end = Math.min(start + PAGE_SIZE, allCards.length);
      for (var j = start; j < end; j++) {
        var rec = allCards[j];
        var card = document.createElement("div"); card.className = "lc-card";
        var titleEl = document.createElement("div"); titleEl.className = "lc-card-title";
        titleEl.textContent = rec.title;
        card.appendChild(titleEl);
        if (rec.author) {
          var authorEl = document.createElement("div"); authorEl.className = "lc-card-author";
          authorEl.textContent = "by " + rec.author;
          card.appendChild(authorEl);
        }
        if (rec.url) {
          var btn = document.createElement("a"); btn.className = "lc-card-btn";
          btn.href = rec.url; btn.textContent = "View in catalog";
          btn.addEventListener("click", function(e) { e.stopPropagation(); });
          card.appendChild(btn);
        }
        cardsContainer.appendChild(card);
      }
      // Update pager
      if (totalPages > 1) {
        pagerDiv.innerHTML = "";
        var row = document.createElement("div"); row.className = "lc-pager-row";
        var prev = document.createElement("button"); prev.className = "lc-pager-btn";
        prev.textContent = "◀"; prev.disabled = currentPage === 0;
        prev.addEventListener("click", function() { if (currentPage > 0) { currentPage--; renderPage(); scroll(); } });
        row.appendChild(prev);
        // Sliding window: show max 5 page numbers around current page
        var maxVisible = 5;
        var half = Math.floor(maxVisible / 2);
        var startPage = Math.max(0, currentPage - half);
        var endPage = Math.min(totalPages, startPage + maxVisible);
        if (endPage - startPage < maxVisible) startPage = Math.max(0, endPage - maxVisible);
        for (var p = startPage; p < endPage; p++) {
          (function(pg) {
            var numBtn = document.createElement("button"); numBtn.className = "lc-pager-btn";
            numBtn.textContent = pg + 1;
            if (pg === currentPage) numBtn.classList.add("active");
            numBtn.addEventListener("click", function() { currentPage = pg; renderPage(); scroll(); });
            row.appendChild(numBtn);
          })(p);
        }
        var next = document.createElement("button"); next.className = "lc-pager-btn";
        next.textContent = "▶"; next.disabled = currentPage === totalPages - 1;
        next.addEventListener("click", function() { if (currentPage < totalPages - 1) { currentPage++; renderPage(); scroll(); } });
        row.appendChild(next);
        pagerDiv.appendChild(row);
        var info = document.createElement("span"); info.className = "lc-pager-info";
        info.textContent = (start + 1) + "–" + end + " of " + allCards.length;
        pagerDiv.appendChild(info);
      }
    }
    renderPage();

    // Feedback buttons
    if (ts) {
      var fb = document.createElement("div"); fb.className = "lc-fb"; fb.style.padding = "4px 0";
      var up = document.createElement("button"); up.innerHTML = "&#128077;"; up.setAttribute("aria-label", "Helpful");
      var down = document.createElement("button"); down.innerHTML = "&#128078;"; down.setAttribute("aria-label", "Not helpful");
      function voteCards(rating, b, o) {
        b.classList.add("voted"); b.disabled = true; o.disabled = true;
        fetch(CHATBOT_API + "/api/feedback", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sid, message_timestamp: ts, rating: rating })
        }).catch(function(){});
      }
      up.addEventListener("click", function() { voteCards(1, up, down); });
      down.addEventListener("click", function() { voteCards(-1, down, up); });
      fb.appendChild(up); fb.appendChild(down);
      wrap.appendChild(fb);
    }
    d.appendChild(wrap);
    return d;
  }
  function addMsgRaw(t, c, ts) {
    msgs.appendChild(renderMsg(t, c, ts)); scroll();
  }
  function addMsg(t, c, ts) {
    addMsgRaw(t, c, ts);
    chatHistory.push({text: t, cls: c, ts: ts});
    saveState();
    resetInactivityTimer();
  }
  function showTyping(label) {
    var d = document.createElement("div"); d.className = "lc-t"; d.id = "lc-tp";
    d.innerHTML = '<div class="lc-spinner"></div> ' + (label || 'Thinking…');
    msgs.appendChild(d); scroll();
  }
  function hideTyping() { var e = document.getElementById("lc-tp"); if (e) e.remove(); }

  // Input
  inp.addEventListener("input", function () { btn.disabled = !inp.value.trim(); });
  inp.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !btn.disabled) { e.preventDefault(); send(); }
  });
  btn.addEventListener("click", send);

  // FAQ buttons — auto-send the question
  msgs.addEventListener("click", function (e) {
    var target = e.target;
    // Handle click on FAQ buttons or Talk to Librarian button
    var faq = target.closest ? target.closest(".lc-faq") : null;
    if (!faq && target.classList && target.classList.contains("lc-faq")) faq = target;
    if (!faq) return;
    e.preventDefault();
    e.stopPropagation();
    var question = faq.getAttribute("data-q");
    if (!question) return;
    inp.value = question;
    btn.disabled = false;
    send();
  });

  // Talk to a Librarian header button — triggers handoff via chat
  var libBtn = document.getElementById("lc-librarian");
  libBtn.addEventListener("click", function () {
    if (handoffActive) return; // already in handoff, ignore
    inp.value = "Talk to a librarian";
    btn.disabled = false;
    send();
  });

  // --- 5-minute inactivity timer ---
  var INACTIVITY_TIMEOUT = 5 * 60 * 1000; // 5 minutes
  var inactivityTimer = null;

  function resetInactivityTimer() {
    if (inactivityTimer) clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(function () {
      // Close session on server
      if (sid) {
        var blob = new Blob(
          [JSON.stringify({ message: "", session_id: sid })],
          { type: "application/json" }
        );
        navigator.sendBeacon(CHATBOT_API + "/api/close-session", blob);
      }
      addMsg("Session ended due to inactivity. Starting a new chat…", "b");
      setTimeout(function () { resetToNewChat(); }, 2000);
    }, INACTIVITY_TIMEOUT);
  }

  // Start the timer on first load if there's an active chat
  if (chatHistory.length > 0) resetInactivityTimer();

  // New Chat button
  function resetToNewChat() {
    stopPolling();
    if (inactivityTimer) { clearTimeout(inactivityTimer); inactivityTimer = null; }
    chatHistory.length = 0;
    sid = (typeof crypto !== "undefined" && crypto.randomUUID)
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
          var r = (Math.random() * 16) | 0;
          return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
        });
    msgs.innerHTML =
      '<div class="lc-w">Hi, I\'m Hero! 👋 I can help you find books, check hours, or answer questions about the library. What can I do for you?</div>' +
      '<div class="lc-faqs">' +
      '<button class="lc-faq" data-q="What are the library hours?">&#128336; Library hours</button>' +
      '<button class="lc-faq" data-q="What is the borrowing limit?">&#128214; Borrowing limit</button>' +
      '<button class="lc-faq" data-q="How do I renew a book?">&#128260; Renew a book</button>' +
      '<button class="lc-faq" data-q="What are the overdue fines?">&#128176; Overdue fines</button>' +
      '<button class="lc-faq" data-q="What happens if I lose a book?">&#128269; Lost book</button>' +
      '</div>';
    inp.disabled = false;
    inp.placeholder = "Type your message…";
    btn.disabled = false;
    libBtn.style.opacity = "1";
    libBtn.style.cursor = "pointer";
    saveState();
  }

  document.getElementById("lc-new").addEventListener("click", function () {
    // Close the old session on the server
    if (sid) {
      var blob = new Blob(
        [JSON.stringify({ message: "", session_id: sid })],
        { type: "application/json" }
      );
      navigator.sendBeacon(CHATBOT_API + "/api/close-session", blob);
    }
    resetToNewChat();
    inp.focus();
  });

  // Send
  function send() {
    var text = inp.value.trim();
    if (!text) return;
    resetInactivityTimer();
    var w = msgs.querySelector(".lc-w"); if (w) w.remove();
    var fq = msgs.querySelector(".lc-faqs"); if (fq) fq.remove();
    addMsg(text, "u");
    inp.value = ""; btn.disabled = true; inp.disabled = true;
    var lower = text.toLowerCase();
    var isSearch = /\b(find|search|look|book|books|author|title|catalog|isbn)\b/.test(lower);
    showTyping(isSearch ? "Searching…" : "Thinking…");
    fetch(CHATBOT_API + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sid })
    })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || "Request failed"); });
      return r.json();
    })
    .then(function (d) {
      // If server says to do client-side search, fetch Koha RSS directly
      if (d.client_search) {
        var kohaBase = "";
        // Detect Koha OPAC origin — if we're on the OPAC, use same origin
        if (window.location.hostname.indexOf("lorma") !== -1 || document.querySelector("#opac-main-search")) {
          kohaBase = window.location.origin;
        } else {
          kohaBase = "https://library.lorma.edu";
        }
        var rssUrl = kohaBase + "/cgi-bin/koha/opac-search.pl?q=" + encodeURIComponent("ti:" + d.client_search + " OR au:" + d.client_search + " OR " + d.client_search) + "&format=rss";
        fetch(rssUrl)
          .then(function(r) { return r.text(); })
          .then(function(xml) {
            var parser = new DOMParser();
            var doc = parser.parseFromString(xml, "text/xml");
            var items = doc.querySelectorAll("item");
            var results = [];
            items.forEach(function(item, idx) {
              if (idx >= 20) return;
              var title = item.querySelector("title");
              var link = item.querySelector("link");
              var creator = item.getElementsByTagNameNS("http://purl.org/dc/elements/1.1/", "creator");
              var author = (creator.length > 0 && creator[0].textContent.trim()) ? creator[0].textContent.trim() : "";
              // If no dc:creator, extract from description "By Author.<br"
              if (!author) {
                var desc = item.querySelector("description");
                if (desc && desc.textContent) {
                  var byMatch = desc.textContent.match(/By\s+(.+?)\.\s*<br/);
                  if (byMatch) author = byMatch[1].trim();
                }
              }
              results.push({
                title: title ? title.textContent.trim() : "Unknown",
                author: author || "Unknown Author",
                url: link ? kohaBase + link.textContent.trim() : ""
              });
            });
            // Send results to backend for formatting
            return fetch(CHATBOT_API + "/api/format-results", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ results: results, session_id: sid, message: d.client_search })
            });
          })
          .then(function(r) { return r.json(); })
          .then(function(d2) { hideTyping(); if (d2.reply) addMsg(d2.reply, "b", d2.timestamp); })
          .catch(function() {
            hideTyping();
            addMsg("Hmm, I couldn't search the catalog right now. Try searching directly on the library website! 🔍", "e");
          });
        return;
      }
      hideTyping(); if (d.reply) addMsg(d.reply, "b", d.timestamp);
    })
    .catch(function (err) {
      hideTyping();
      if (err.message === "Failed to fetch" || err.name === "TypeError") {
        addMsg("Oops, I can't connect right now 😅 Check your internet and try again in a moment!", "e");
      } else {
        addMsg(err.message || "Something went wrong.", "e");
      }
    })
    .finally(function () {
      if (!handoffActive || handoffHandler) {
        inp.disabled = false; inp.focus(); btn.disabled = !inp.value.trim();
      }
    });
  }

  // --- Librarian handoff polling ---
  var handoffActive = false;
  var handoffHandler = null;
  var lastPollTs = 0;
  var pollTimer = null;

  function startPolling() {
    if (pollTimer) return;
    handoffActive = true;
    libBtn.style.opacity = "0.5";
    libBtn.style.cursor = "default";
    // Disable input while waiting for librarian
    inp.disabled = true;
    inp.placeholder = "Waiting for a librarian…";
    btn.disabled = true;
    // Show cancel button while waiting
    showCancelButton();
    pollTimer = setInterval(pollForMessages, 3000);
  }

  function stopPolling() {
    handoffActive = false;
    // Don't reset handoffHandler — prevents duplicate "joined" messages
    libBtn.style.opacity = "1";
    libBtn.style.cursor = "pointer";
    // Re-enable input
    inp.disabled = false;
    inp.placeholder = "Type your message…";
    btn.disabled = false;
    removeCancelButton();
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function showCancelButton() {
    removeCancelButton();
    var cancelDiv = document.createElement("div");
    cancelDiv.id = "lc-cancel-handoff";
    cancelDiv.className = "lc-m b";
    cancelDiv.style.cssText = "text-align:center;max-width:90%;padding:10px 14px";
    cancelDiv.innerHTML =
      '<button style="background:none;border:1px solid #c0392b;color:#c0392b;border-radius:14px;' +
      'padding:6px 16px;font-size:.82rem;cursor:pointer;transition:all .15s" ' +
      'aria-label="Cancel librarian request">Cancel request</button>';
    cancelDiv.querySelector("button").addEventListener("click", cancelHandoff);
    msgs.appendChild(cancelDiv);
    scroll();
  }

  function removeCancelButton() {
    var el = document.getElementById("lc-cancel-handoff");
    if (el) el.remove();
  }

  function cancelHandoff() {
    fetch(CHATBOT_API + "/api/cancel-handoff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "", session_id: sid })
    })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.status === "ok") {
          stopPolling();
          _origAddMsg("Librarian request cancelled. I'm Hero, back to help! 👋 What else can I do for you?", "b");
        } else if (d.error) {
          // Staff already claimed — remove cancel button, keep polling
          removeCancelButton();
        }
      })
      .catch(function() {});
  }

  function pollForMessages() {
    fetch(CHATBOT_API + "/api/poll/" + encodeURIComponent(sid) + "?since=" + lastPollTs)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.handled_by && d.handled_by !== handoffHandler) {
          handoffHandler = d.handled_by;
          removeCancelButton();
          // Re-enable input now that a librarian is here
          inp.disabled = false;
          inp.placeholder = "Type your message…";
          btn.disabled = false;
          _origAddMsg("A librarian has joined the chat! 👋", "b");
        }
        // Process new messages
        if (d.messages && d.messages.length > 0) {
          d.messages.forEach(function(m) {
            if (m.timestamp <= lastPollTs) return;
            if (m.role === "librarian") {
              _origAddMsg("👩‍💼 Librarian: " + m.content, "b", m.timestamp);
            } else if (m.role === "assistant") {
              // Skip the "Hero is back" end-handoff message — we show our own UI for that
              if (m.content && m.content.indexOf("Hero, back to help") !== -1) {
                // don't display
              } else {
                _origAddMsg(m.content, "b", m.timestamp);
              }
            }
            if (m.timestamp > lastPollTs) lastPollTs = m.timestamp;
          });
        }
        // Then check if handoff just ended — show rating AFTER messages
        if (!d.handoff_active && handoffActive) {
          stopPolling();
          showHandoffRating();
        }
      })
      .catch(function() {});
  }

  function showHandoffRating() {
    var rateDiv = document.createElement("div");
    rateDiv.className = "lc-m b";
    rateDiv.style.cssText = "text-align:center;max-width:90%;padding:14px 18px";
    rateDiv.innerHTML =
      '<div style="margin-bottom:8px;font-size:0.9rem;color:#333">How was your experience with the librarian?</div>' +
      '<div class="lc-handoff-rate">' +
      '<button class="lc-rate-btn" data-rating="1" aria-label="Good experience">👍 Good</button>' +
      '<button class="lc-rate-btn" data-rating="-1" aria-label="Bad experience">👎 Could be better</button>' +
      '</div>';
    msgs.appendChild(rateDiv);
    scroll();
    rateDiv.querySelectorAll(".lc-rate-btn").forEach(function(btn) {
      btn.addEventListener("click", function() {
        var rating = parseInt(btn.getAttribute("data-rating"));
        rateDiv.innerHTML = '<div style="color:#555;font-size:0.88rem">Thanks for your feedback! ' + (rating === 1 ? '😊' : '🙏') + '</div>';
        fetch(CHATBOT_API + "/api/rate-handoff", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sid, rating: rating })
        }).catch(function() {});
      });
    });
  }

  // Detect handoff activation from bot responses
  var _origAddMsg = addMsg;
  addMsg = function(t, c, ts) {
    _origAddMsg(t, c, ts);
    if (c === "b" && t && t.indexOf("notified a librarian") !== -1) {
      // Fresh handoff request — reset handler and start polling
      handoffHandler = null;
      lastPollTs = Date.now() / 1000;
      startPolling();
    }
  };

  // On load, check if there's an active handoff we should resume polling for
  (function resumeHandoffIfActive() {
    if (!sid) return;
    fetch(CHATBOT_API + "/api/poll/" + encodeURIComponent(sid) + "?since=0")
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.handoff_active) {
          lastPollTs = Date.now() / 1000;
          // If a librarian already claimed, set handoffHandler so we don't
          // show the "joined" message again on reload
          if (d.handled_by) {
            handoffHandler = d.handled_by;
          }
          startPolling();
          // If librarian already joined, re-enable input (startPolling disables it)
          if (d.handled_by) {
            inp.disabled = false;
            inp.placeholder = "Type your message…";
            btn.disabled = false;
            removeCancelButton();
          }
        }
      })
      .catch(function() {});
  })();

  // Notify server when patron closes/navigates away so session is marked expired
  window.addEventListener("beforeunload", function () {
    stopPolling();
    if (sid) {
      var blob = new Blob(
        [JSON.stringify({ message: "", session_id: sid })],
        { type: "application/json" }
      );
      navigator.sendBeacon(CHATBOT_API + "/api/close-session", blob);
    }
  });
})();
