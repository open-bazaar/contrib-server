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
      light(address);
    }
    if (title && document.title !== title) document.title = title;
  });

  // The shell stays as it is and opens a place in its frame, for its own
  // links and for those its pages give the whole window; the place shown is
  // lit, as the server lights it, however the frame got there.
  const light = (address) => {
    const here = address.split("?")[0].replace(/\/?$/, "/");
    const links = [...document.querySelectorAll("a.nav[href]")];
    const lit = links
      .filter((link) => here.startsWith(link.getAttribute("href").replace(/\/?$/, "/")))
      .sort((a, b) => b.getAttribute("href").length - a.getAttribute("href").length)[0];
    for (const link of links) {
      link.classList.toggle("on", link === lit);
      if (link === lit) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    document.querySelector(".nav.more")?.classList.toggle("on", Boolean(lit?.closest(".overflow")));
  };
  const place = () => document.querySelector("iframe.frame[data-address-from]");
  // the shell's line for what is on its way: shown once a load takes a
  // moment, run out once the last one is there
  let loads = 0;
  let timers = [];
  const later = (wait, then) => timers.push(setTimeout(then, wait));
  const finish = (line) => {
    timers.forEach(clearTimeout);
    timers = [];
    if (!line.classList.contains("on")) return;
    line.classList.add("done");
    later(200, () => line.classList.remove("on"));
    later(500, () => line.classList.remove("done"));
  };
  window.bazaarLoading = (delta) => {
    const line = document.querySelector(".loading");
    if (!line) return;
    loads = Math.max(0, loads + delta);
    if (loads === 1 && delta > 0) {
      timers.forEach(clearTimeout);
      timers = [];
      later(150, () => {
        // from the start again, however far the last one had run
        line.classList.remove("on", "done");
        void line.offsetWidth;
        line.classList.add("on");
      });
    } else if (loads === 0) finish(line);
  };
  // a page put in the frame ends what the page before had on its way, whether
  // that page said so or not
  addEventListener("DOMContentLoaded", () => {
    place()?.addEventListener("load", () => {
      loads = 0;
      finish(document.querySelector(".loading"));
    });
  });
  window.bazaarOpen = (url) => {
    const frame = place();
    const [, module, ...rest] = url.pathname.split("/");
    window.bazaarLoading(1);
    frame.contentWindow.location.assign(`${frame.dataset.addressFrom}/${module}/${rest.join("/")}${url.search}`);
    light(url.pathname + url.search);
    const more = document.getElementById("more-places");
    if (more) more.checked = false;
  };
  document.addEventListener("click", (event) => {
    const link = event.target.closest?.(place() ? "a.nav[href]" : "a[target=_top][href], a[target=_parent][href]");
    const open = shell ? window.top.bazaarOpen : place() && window.bazaarOpen;
    if (!link || !open || link.origin !== location.origin) return;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    // the page around this one changes in place, as its own links change it;
    // around one right in the shell's frame, the frame is that page's place
    if (link.target !== "_parent") open(new URL(link.href));
    else if (window.parent === window.top) location.assign(link.href);
    else window.parent.htmx.ajax("GET", link.href, { target: "body", swap: "innerMorph show:top", push: "true" });
  });

  // A page changing in place leaves behind what it asked for before: an
  // answer meant for the page it was is not put into the page it became. It
  // has become another once the new one is put in, not when it is asked for.
  let changes = 0;
  document.addEventListener("htmx:before:request", (event) => {
    event.detail.ctx.change = changes;
  });

  // What a reader asks for shows on the shell's line while it is on its way;
  // what the page refreshes by itself does not.
  const loading = shell ? window.top.bazaarLoading : null;
  document.addEventListener("htmx:before:request", (event) => {
    const ctx = event.detail.ctx;
    if (!loading || (ctx.sourceEvent instanceof Event && !ctx.sourceEvent.isTrusted)) return;
    ctx.loading = true;
    loading(1);
  });
  document.addEventListener("htmx:finally:request", (event) => {
    if (event.detail.ctx.loading) loading(-1);
  });
  document.addEventListener("htmx:before:swap", (event) => {
    const ctx = event.detail.ctx;
    if (ctx.target === document.body) changes += 1;
    else if (ctx.change !== changes) event.preventDefault();
  });

  // What a page changes in place stays within its own module, whose build
  // drew it: a link or form leading elsewhere goes as the browser takes it.
  document.addEventListener("htmx:before:init", (event) => {
    const element = event.target;
    if (!element.matches?.("a[href], form") || element.matches("[hx-get], [hx-post], [hx-put], [hx-patch], [hx-delete]")) return;
    const module = location.pathname.match(/^\/ui\/[^/]+\//)?.[0];
    const address = new URL(element.getAttribute(element.matches("a") ? "href" : "action") ?? "", location.href);
    if (!module || address.origin !== location.origin || !address.pathname.startsWith(module)) event.preventDefault();
  });

  // A frame keeps what it learned of its page as the page around it changes
  // in place: whether it is shown, empty, and how tall.
  addEventListener("DOMContentLoaded", () => {
    window.htmx?.registerExtension("frames", {
      htmx_before_morph_attr: (element, detail) =>
        !(element instanceof HTMLIFrameElement && ["data-drawn", "data-empty", "style"].includes(detail.attrName)),
    });
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

  // Text copied for the reader, whether it was: the clipboard where the page
  // is served securely, the selection copied the old way where it is not,
  // over plain http to an address on the network.
  window.bazaarCopy = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.cssText = "position: fixed; top: 0; left: 0; opacity: 0";
      document.body.append(area);
      area.select();
      const copied = document.execCommand("copy");
      area.remove();
      return copied;
    }
  };

  // A page that changed how the account's pages look has the whole window drawn again.
  document.addEventListener("dressed", () => window.top.location.reload());

  // A page another build drew is not patched with pieces of this one.
  document.addEventListener("stale", () => document.querySelector("dialog[data-stale]")?.showModal());
  document.addEventListener("click", (event) => {
    if (event.target.closest?.("[data-refresh]")) window.top.location.reload();
  });
})();
