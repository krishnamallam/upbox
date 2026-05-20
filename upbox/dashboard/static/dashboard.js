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

  // Track the highest request id we've shown so we can flag genuinely new
  // rows when the feed refreshes (the CSS `.new` class drives the pulse).
  let maxSeenId = 0;

  async function refreshFeed() {
    if (paused || !feed) return;
    try {
      const q = currentQuery();
      const [feedHtml, sidebarHtml, statsHtml] = await Promise.all([
        fetchText("/requests/recent" + q),
        fetchText("/sidebar" + q),
        fetchText("/stats" + q),
      ]);
      if (feedHtml !== null) {
        replaceFromHtml(feed, feedHtml);
        markNewRows();
      }
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

  function markNewRows() {
    if (!feed) return;
    const rows = feed.querySelectorAll("table.feed tbody tr[data-id]");
    rows.forEach(function (tr) {
      const id = Number(tr.getAttribute("data-id"));
      if (id > maxSeenId) tr.classList.add("new");
    });
    if (rows.length > 0) {
      const topId = Number(rows[0].getAttribute("data-id"));
      if (topId > maxSeenId) maxSeenId = topId;
    }
  }

  let currentDetailId = null;
  let currentTab = "body";

  window.upboxDetail = async function (id, tab) {
    if (!detail) return;
    if (tab) currentTab = tab;
    currentDetailId = id;

    document
      .querySelectorAll("table.feed tbody tr.sel")
      .forEach((tr) => tr.classList.remove("sel"));
    const row = document.querySelector('table.feed tbody tr[data-id="' + id + '"]');
    if (row) row.classList.add("sel");

    try {
      const url = "/requests/" + encodeURIComponent(id) + "?tab=" + encodeURIComponent(currentTab);
      const html = await fetchText(url);
      if (html === null) {
        detail.replaceChildren(emptyMessage("Request not found."));
        return;
      }
      replaceFromHtml(detail, html);
      wireDetailTabs();
      wireCopyButtons();
    } catch (e) {
      detail.replaceChildren(emptyMessage("Failed to load detail."));
    }
  };

  function wireDetailTabs() {
    const tabBar = detail && detail.querySelector(".tabs");
    if (!tabBar || tabBar.dataset.wired === "1") return;
    tabBar.dataset.wired = "1";
    tabBar.addEventListener("click", function (ev) {
      const a = ev.target && ev.target.closest("a[data-tab]");
      if (!a) return;
      ev.preventDefault();
      const tab = a.getAttribute("data-tab");
      if (currentDetailId != null && tab) {
        window.upboxDetail(currentDetailId, tab);
      }
    });
  }

  function wireCopyButtons() {
    if (!detail) return;
    detail.querySelectorAll("button.copy[data-copy-target]").forEach(function (btn) {
      if (btn.dataset.wired === "1") return;
      btn.dataset.wired = "1";
      btn.addEventListener("click", async function () {
        const sel = btn.getAttribute("data-copy-target");
        const node = detail.querySelector(sel);
        if (!node) return;
        const text = node.innerText || node.textContent || "";
        try {
          await navigator.clipboard.writeText(text);
          const orig = btn.textContent;
          btn.textContent = "copied";
          btn.classList.add("ok");
          setTimeout(function () {
            btn.textContent = orig;
            btn.classList.remove("ok");
          }, 1200);
        } catch (e) {
          // ignore — secure-context only
        }
      });
    });
  }

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

  function selectAdjacentRow(direction) {
    if (!feed) return;
    const rows = Array.from(feed.querySelectorAll("table.feed tbody tr[data-id]"));
    if (rows.length === 0) return;
    const current = rows.findIndex((tr) => tr.classList.contains("sel"));
    let next;
    if (current === -1) {
      next = direction > 0 ? 0 : rows.length - 1;
    } else {
      next = Math.max(0, Math.min(rows.length - 1, current + direction));
    }
    const id = Number(rows[next].getAttribute("data-id"));
    if (id) window.upboxDetail(id);
    rows[next].scrollIntoView({ block: "nearest" });
  }

  function focusSearch() {
    const input = document.getElementById("search-input");
    if (input) {
      input.focus();
      input.select();
    }
  }

  function hasActiveFilters() {
    const u = new URL(window.location.href);
    return ["range", "status", "tool", "q"].some((k) => u.searchParams.has(k));
  }

  document.addEventListener("keydown", function (ev) {
    const inField = ev.target && ["INPUT", "TEXTAREA"].includes(ev.target.tagName);
    if (ev.key === "Escape") {
      if (inField) {
        ev.target.blur();
        return;
      }
      if (hasActiveFilters()) {
        window.location.href = "/";
        return;
      }
      if (detail) {
        detail.replaceChildren(
          emptyMessage("Click a request to inspect headers and body excerpt.")
        );
      }
      return;
    }
    if (inField) return;
    if (ev.key === " ") {
      ev.preventDefault();
      setPaused(!paused);
    } else if (ev.key === "/") {
      ev.preventDefault();
      focusSearch();
    } else if (ev.key === "f") {
      ev.preventDefault();
      window.location.href = "/";
    } else if (ev.key === "ArrowDown") {
      ev.preventDefault();
      selectAdjacentRow(1);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      selectAdjacentRow(-1);
    }
  });

  wireStatsBar();
  markNewRows();
  setInterval(refreshFeed, REFRESH_MS);
})();
