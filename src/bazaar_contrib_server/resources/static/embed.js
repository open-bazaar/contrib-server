// Every page of the server, the shell included, runs this: it wears the
// shell's theme and language, tells the frame around it where it went, what
// it is called and how tall it is, and follows what its own frames tell it.
(() => {
  const root = document.documentElement;
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

  // A frame marked data-fit is as tall as its page; one marked with an
  // address carries this page's address and title along with its own.
  addEventListener("message", (event) => {
    if (event.origin !== location.origin || !event.data?.bazaar) return;
    const frame = [...document.querySelectorAll("iframe")].find((f) => f.contentWindow === event.source);
    if (!frame) return;
    const { path, title, height } = event.data.bazaar;
    if (frame.hasAttribute("data-fit")) frame.style.height = `${height}px`;
    const from = frame.dataset.addressFrom;
    if (from === undefined) return;
    if (path.startsWith(`${from}/`) || path.startsWith(`${from}?`) || path === from) {
      const address = (frame.dataset.addressTo + path.slice(from.length)).replace(/\/(?=\?|$)/, "") || "/";
      if (address !== location.pathname + location.search) history.replaceState(history.state, "", address);
    }
    if (title && document.title !== title) document.title = title;
    for (const heading of document.querySelectorAll("[data-title]")) heading.textContent = title;
  });

  // A page another build drew is not patched with pieces of this one.
  document.addEventListener("stale", () => document.querySelector("dialog[data-stale]")?.showModal());
  document.addEventListener("click", (event) => {
    if (event.target.closest?.("[data-refresh]")) window.top.location.reload();
  });
})();
