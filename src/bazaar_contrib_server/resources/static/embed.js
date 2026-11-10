// Every page of the server, the shell included, runs this: it wears the
// shell's theme and language, tells the frame around it where it went, what
// it is called and how tall it is, follows what its own frames tell it, and
// hands what it follows to the update bus the outermost window keeps.
(() => {
  const root = document.documentElement;
  // a page that belongs to the whole window, like the login page, leaves any frame it was opened in
  if (root.hasAttribute("data-top") && window.top !== window) {
    window.top.location.replace(location.href);
    return;
  }
  // the browser's zone, for every page the server draws after this one
  document.cookie = `bcs_tz=${Intl.DateTimeFormat().resolvedOptions().timeZone}; path=/; SameSite=Lax${
    location.protocol === "https:" ? "; Secure" : ""
  }`;
  let shell = null;
  try {
    if (window.top !== window) shell = window.top.document.documentElement;
  } catch {
    // a page framed by another site has no shell to follow
  }

  // A framed page lays out as the shell around it does, narrow or wide,
  // whatever the width of its own frame; a page on its own goes by its window.
  const wide = (shell ? window.top : window).matchMedia("(min-width: 960px)");
  const layout = () => {
    root.dataset.layout = wide.matches ? "wide" : "narrow";
  };
  layout();
  wide.addEventListener("change", layout);

  // An account that chose no theme follows the system, light or dark.
  const chosen = root.dataset.theme;
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const dress = () => {
    if (shell) {
      root.dataset.theme = shell.dataset.theme;
      root.lang = shell.lang;
    } else if (!chosen) {
      root.dataset.theme = dark.matches ? root.dataset.themeDark : root.dataset.themeLight;
    }
  };
  dress();
  if (shell) {
    new MutationObserver(dress).observe(shell, { attributes: true, attributeFilter: ["data-theme", "lang"] });
  } else {
    dark.addEventListener("change", dress);
  }

  const report = () => {
    if (window.parent === window) return;
    window.parent.postMessage(
      {
        bazaar: {
          path: location.pathname + location.search,
          title: document.title,
          height: root.offsetHeight,
        },
      },
      location.origin,
    );
  };
  for (const name of ["pushState", "replaceState"]) {
    const original = history[name];
    history[name] = function (...args) {
      const result = original.apply(this, args);
      report();
      return result;
    };
  }
  addEventListener("popstate", report);
  addEventListener("DOMContentLoaded", () => {
    report();
    new ResizeObserver(report).observe(document.body);
    new MutationObserver(report).observe(document.head, { subtree: true, childList: true, characterData: true });
  });

  // A frame is marked data-drawn once its page reports in, shown from then
  // on rather than the blank it starts as, or once its page has loaded when
  // that page does without these tools; marked data-fit it is as tall as its
  // page, and marked data-empty while its page draws nothing; one marked with
  // an address carries this page's address and title along with its own.
  document.addEventListener(
    "load",
    (event) => {
      if (event.target instanceof HTMLIFrameElement) event.target.toggleAttribute("data-drawn", true);
    },
    true,
  );
  addEventListener("message", (event) => {
    if (event.origin !== location.origin || !event.data?.bazaar) return;
    const frame = [...document.querySelectorAll("iframe")].find((f) => f.contentWindow === event.source);
    if (!frame) return;
    frame.toggleAttribute("data-drawn", true);
    const { path, title, height } = event.data.bazaar;
    if (frame.hasAttribute("data-fit")) {
      frame.style.height = `${height}px`;
      frame.toggleAttribute("data-empty", height === 0);
    }
    const from = frame.dataset.addressFrom;
    if (from === undefined) return;
    if (path.startsWith(`${from}/`) || path.startsWith(`${from}?`) || path === from) {
      const address = (frame.dataset.addressTo + path.slice(from.length)).replace(/\/(?=\?|$)/, "") || "/";
      if (address !== location.pathname + location.search) history.replaceState(history.state, "", address);
    }
    if (title && document.title !== title) document.title = title;
  });

  // The update bus, as 0.2's /poll: every page hands what it follows to the
  // one bus of the outermost window, which asks the server about all of it in
  // one request a round, at most every second, and tells each follower what
  // changed or that it may no longer see it.
  const outer = shell ? window.top : window;
  if (outer === window && !window.bazaarBus) {
    const records = new Set();
    let timer = null;
    let request = null;
    let next = 0;
    let stopped = false;
    const arm = () => {
      if (timer === null && !stopped && !document.hidden && records.size) timer = setTimeout(tick, 0);
    };
    const check = async () => {
      const groups = new Map();
      for (const record of records) {
        const identity = JSON.stringify([record.topic, record.scope, record.seen]);
        if (!groups.has(identity)) {
          groups.set(identity, { id: String(groups.size), topic: record.topic, scope: record.scope, seen: record.seen, records: [] });
        }
        groups.get(identity).records.push(record);
      }
      const asked = new Map([...groups.values()].map((group) => [group.id, group]));
      const controller = new AbortController();
      request = { controller, started: Date.now() };
      try {
        const response = await fetch("/api/server/poll", {
          method: "POST",
          credentials: "same-origin",
          signal: controller.signal,
          headers: { "Content-Type": "application/json", "X-Build": document.body.dataset.build || "" },
          body: JSON.stringify({
            subscriptions: [...groups.values()].map(({ id, topic, scope, seen }) => ({ id, topic, scope, seen })),
          }),
        });
        // a session that ran out sends the whole window to log in again
        if (response.redirected || response.status === 401) return window.location.reload();
        if (!response.ok) {
          next = Date.now() + 5000;
          return;
        }
        const answer = await response.json();
        if (answer.stale) {
          stopped = true;
          return document.dispatchEvent(new CustomEvent("stale"));
        }
        for (const change of answer.changes) {
          for (const record of asked.get(change.id)?.records ?? []) {
            if (!records.has(record)) continue;
            if (change.unavailable) records.delete(record);
            else record.seen = change.state;
            try {
              record.callback(change);
            } catch (error) {
              console.error(error);
            }
          }
        }
        next = Date.now() + 1000;
      } catch (error) {
        if (error.name !== "AbortError") console.warn("The update bus could not ask the server", error);
        next = Date.now() + 5000;
      } finally {
        request = null;
      }
    };
    const tick = () => {
      timer = null;
      if (stopped || document.hidden) return;
      // what was followed for an element that left its page is let go
      for (const record of records) {
        if (record.element && !record.element.isConnected) records.delete(record);
      }
      if (request && Date.now() - request.started >= 15000) request.controller.abort();
      if (!request && records.size && Date.now() >= next) void check();
      if (records.size) timer = setTimeout(tick, 1000);
    };
    // a hidden window asks nothing until it is seen again
    document.addEventListener("visibilitychange", arm);
    window.bazaarBus = {
      follow({ topic, scope = {}, seen = null, element = null }, callback) {
        const record = { topic, scope, seen, element, callback };
        records.add(record);
        arm();
        return () => records.delete(record);
      },
    };
  }
  // what this page follows: elements naming a topic hear of its changes; one
  // marked data-tally shows the state as a badge
  const leaving = [];
  const followed = new WeakSet();
  const follow = (element) => {
    if (followed.has(element)) return;
    followed.add(element);
    const stop = outer.bazaarBus.follow(
      {
        topic: element.dataset.topic,
        scope: JSON.parse(element.dataset.scope || "{}"),
        seen: element.dataset.seen ? JSON.parse(element.dataset.seen) : null,
        element,
      },
      (change) => {
        if (!element.isConnected) return stop();
        if (element.hasAttribute("data-tally")) {
          const state = change.state || {};
          element.textContent = state.text || "";
          element.className = `tally ${state.kind || ""}`;
          element.hidden = !state.text;
        }
        element.dispatchEvent(new CustomEvent("bazaar:change", { detail: change, bubbles: true }));
      },
    );
    leaving.push(stop);
  };
  const scan = (within) => {
    if (within.matches?.("[data-topic]")) follow(within);
    within.querySelectorAll?.("[data-topic]").forEach(follow);
  };
  addEventListener("DOMContentLoaded", () => scan(document));
  // htmx processes the whole page as it starts, and then each piece it swaps in
  document.addEventListener("htmx:after:process", (event) => scan(event.target));
  // a page kept for the back button goes on following when it comes back
  addEventListener("pagehide", (event) => {
    if (!event.persisted) leaving.forEach((stop) => stop());
  });

  // A page that changed how the account's pages look has the whole window drawn again.
  document.addEventListener("dressed", () => window.top.location.reload());

  // A page another build drew is not patched with pieces of this one.
  document.addEventListener("stale", () => document.querySelector("dialog[data-stale]")?.showModal());
  document.addEventListener("click", (event) => {
    if (event.target.closest?.("[data-refresh]")) window.top.location.reload();
  });
})();
