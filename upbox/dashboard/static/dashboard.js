// upbox dashboard — vanilla JS, no framework.
//
// XSS note: HTML fragments returned by /requests/recent and /requests/{id}
// come from our own Jinja2 templates which auto-escape user-supplied
// content (captured headers, body excerpts). innerHTML use below is
// therefore safe within the trust boundary of upbox's own template
// rendering. If a future endpoint serves third-party HTML, swap to a
// safer DOM API.

(function () {
  "use strict";

  const REFRESH_MS = 2000;
  const feed = document.getElementById("feed");
  const detail = document.getElementById("detail");

  async function refreshFeed() {
    try {
      const r = await fetch("/requests/recent", { headers: { "X-Upbox": "1" } });
      if (!r.ok) return;
      feed.innerHTML = await r.text();
    } catch (e) {
      // Silent — dashboard is local, transient network errors aren't actionable.
    }
  }

  window.upboxDetail = async function (id) {
    try {
      const r = await fetch("/requests/" + encodeURIComponent(id));
      if (!r.ok) {
        detail.innerHTML = '<p class="muted">Request not found.</p>';
        return;
      }
      detail.innerHTML = await r.text();
    } catch (e) {
      detail.innerHTML = '<p class="muted">Failed to load detail.</p>';
    }
  };

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "r" && !ev.metaKey && !ev.ctrlKey && document.activeElement === document.body) {
      refreshFeed();
      ev.preventDefault();
    }
    if (ev.key === "Escape") {
      detail.innerHTML =
        '<p class="muted">Click a request to see headers and body excerpt.</p>';
    }
  });

  setInterval(refreshFeed, REFRESH_MS);
})();
