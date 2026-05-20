// upbox dashboard — vanilla JS, no framework.
//
// Server fragments (returned by /requests/recent, /sidebar, /stats,
// /requests/{id}) are Jinja2-rendered with autoescape on (FastAPI/Starlette
// default). We never echo client-side state into templates, so even though
// we insert server HTML into the DOM, the content is escaped at render time.
//
// We use DOMParser + replaceChildren instead of innerHTML to keep the pattern
// consistent with modern safer-by-default DOM APIs.

(function () {
  "use strict";

  const REFRESH_MS = 2000;
  const feed = document.getElementById("feed");
  const sidebar = document.getElementById("sidebar");
  const statsBar = document.getElementById("stats-bar");
  const detail = document.getElementById("detail");

  let paused = false;

  function currentQuery() {
    const u = new URL(window.location.href);
    const params = new URLSearchParams();
    const tool = u.searchParams.get("tool");
    const status = u.searchParams.get("status");
    if (tool) params.set("tool", tool);
    if (status) params.set("status", status);
    const qs = params.toString();
    return qs ? "?" + qs : "";
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
      const q = currentQuery();
      const [feedHtml, sidebarHtml, statsHtml] = await Promise.all([
        fetchText("/requests/recent" + q),
        fetchText("/sidebar" + q),
        fetchText("/stats" + q),
      ]);
      if (feedHtml !== null) replaceFromHtml(feed, feedHtml);
      if (sidebarHtml !== null && sidebar) {
        // /sidebar returns the full <aside> wrapper; copy its inner content
        // so our existing wrapper stays mounted.
        const doc = new DOMParser().parseFromString(sidebarHtml, "text/html");
        const fresh = doc.querySelector("#sidebar");
        if (fresh) sidebar.replaceChildren(...fresh.childNodes);
      }
      if (statsHtml !== null && statsBar) replaceFromHtml(statsBar, statsHtml);
      wireStatsBar();
    } catch (e) {
      // Silent — local dashboard, transient errors aren't actionable.
    }
  }

  window.upboxDetail = async function (id) {
    if (!detail) return;
    document
      .querySelectorAll("table.feed tbody tr.sel")
      .forEach((tr) => tr.classList.remove("sel"));
    const row = document.querySelector('table.feed tbody tr[data-id="' + id + '"]');
    if (row) row.classList.add("sel");

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

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("upbox-theme", theme); } catch (e) { /* private mode */ }
    const dark = document.getElementById("theme-dark");
    const light = document.getElementById("theme-light");
    if (dark) dark.classList.toggle("on", theme === "dark");
    if (light) light.classList.toggle("on", theme === "light");
  }

  function wireStatsBar() {
    const btn = document.getElementById("btn-pause");
    if (btn && btn.dataset.wired !== "1") {
      btn.dataset.wired = "1";
      btn.addEventListener("click", () => setPaused(!paused));
    }
    const label = document.getElementById("pause-label");
    const indicator = document.getElementById("live-indicator");
    if (label) label.textContent = paused ? "▶ Resume" : "⏸ Pause";
    if (indicator) {
      indicator.classList.toggle("paused", paused);
      indicator.textContent = paused ? "Paused" : "Live";
    }

    const dark = document.getElementById("theme-dark");
    const light = document.getElementById("theme-light");
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    if (dark && dark.dataset.wired !== "1") {
      dark.dataset.wired = "1";
      dark.addEventListener("click", () => applyTheme("dark"));
    }
    if (light && light.dataset.wired !== "1") {
      light.dataset.wired = "1";
      light.addEventListener("click", () => applyTheme("light"));
    }
    if (dark) dark.classList.toggle("on", current === "dark");
    if (light) light.classList.toggle("on", current === "light");
  }

  // Restore theme from localStorage on first load — before any paint.
  try {
    const saved = localStorage.getItem("upbox-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  } catch (e) { /* private mode */ }

  document.addEventListener("keydown", function (ev) {
    const inField = ev.target && ["INPUT", "TEXTAREA"].includes(ev.target.tagName);
    if (inField) return;
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

  wireStatsBar();
  setInterval(refreshFeed, REFRESH_MS);
})();
