// upbox dashboard — vanilla JS, no framework.
//
// HTML fragments returned by /requests/recent, /sidebar, /stats, and
// /requests/{id} are server-rendered through Jinja2 with autoescape on
// (the FastAPI/Starlette default). We never echo client-side state into
// templates. So even though we're inserting server HTML into the DOM, the
// content is escaped at render time on the server side.
//
// We use DOMParser + replaceChildren instead of innerHTML to keep the
// pattern consistent with modern safer-by-default DOM APIs.

(function () {
  "use strict";

  const REFRESH_MS = 2000;
  const feed = document.getElementById("feed");
  const sidebar = document.getElementById("sidebar");
  const statsBar = document.getElementById("stats-bar");
  const detail = document.getElementById("detail");

  let paused = false;

  function currentToolParam() {
    const u = new URL(window.location.href);
    const tool = u.searchParams.get("tool");
    return tool ? "?tool=" + encodeURIComponent(tool) : "";
  }

  function replaceFromHtml(target, html) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    target.replaceChildren(...doc.body.childNodes);
  }

  async function fetchText(url) {
    const r = await fetch(url);
    return r.ok ? await r.text() : null;
  }

  async function refreshFeed() {
    if (paused || !feed) return;
    try {
      const q = currentToolParam();
      const [feedHtml, sidebarHtml, statsHtml] = await Promise.all([
        fetchText("/requests/recent" + q),
        fetchText("/sidebar" + q),
        fetchText("/stats"),
      ]);
      if (feedHtml !== null) replaceFromHtml(feed, feedHtml);
      if (sidebarHtml !== null && sidebar) {
        // /sidebar returns the full <aside> wrapper; copy its inner content
        // into our existing <aside> so the wrapper stays mounted.
        const doc = new DOMParser().parseFromString(sidebarHtml, "text/html");
        const fresh = doc.querySelector("#sidebar");
        if (fresh) sidebar.replaceChildren(...fresh.childNodes);
      }
      if (statsHtml !== null && statsBar) replaceFromHtml(statsBar, statsHtml);
      wirePauseButton();
    } catch (e) {
      // Silent — local dashboard, transient errors aren't actionable.
    }
  }

  window.upboxDetail = async function (id) {
    if (!detail) return;
    document
      .querySelectorAll(".feed-table tbody tr.selected")
      .forEach((tr) => tr.classList.remove("selected"));
    const row = document.querySelector('.feed-table tbody tr[data-id="' + id + '"]');
    if (row) row.classList.add("selected");

    try {
      const html = await fetchText("/requests/" + encodeURIComponent(id));
      if (html === null) {
        detail.replaceChildren(emptyMessage("Request not found."));
        return;
      }
      replaceFromHtml(detail, html);
    } catch (e) {
      detail.replaceChildren(emptyMessage("Failed to load detail."));
    }
  };

  function emptyMessage(text) {
    const div = document.createElement("div");
    div.className = "detail-empty";
    div.textContent = text;
    return div;
  }

  function setPaused(next) {
    paused = next;
    const label = document.getElementById("pause-label");
    const indicator = document.getElementById("live-indicator");
    if (label) label.textContent = paused ? "▶ Resume" : "⏸ Pause";
    if (indicator) {
      indicator.classList.toggle("paused", paused);
      indicator.textContent = paused ? "Paused" : "Live";
    }
  }

  function wirePauseButton() {
    const btn = document.getElementById("btn-pause");
    if (!btn || btn.dataset.wired === "1") return;
    btn.dataset.wired = "1";
    btn.addEventListener("click", () => setPaused(!paused));
    // Sync label after server re-render
    const label = document.getElementById("pause-label");
    const indicator = document.getElementById("live-indicator");
    if (label) label.textContent = paused ? "▶ Resume" : "⏸ Pause";
    if (indicator) {
      indicator.classList.toggle("paused", paused);
      indicator.textContent = paused ? "Paused" : "Live";
    }
  }

  document.addEventListener("keydown", function (ev) {
    if (document.activeElement && document.activeElement.tagName === "TEXTAREA") return;
    if (ev.key === "f") {
      window.location.href = "/";
      ev.preventDefault();
    } else if (ev.key === " ") {
      setPaused(!paused);
      ev.preventDefault();
    } else if (ev.key === "Escape" && detail) {
      detail.replaceChildren(
        emptyMessage("Click a request to inspect headers and body excerpt.")
      );
    }
  });

  wirePauseButton();
  setInterval(refreshFeed, REFRESH_MS);
})();
