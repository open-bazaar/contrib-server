// The 0.2 search window, shared by lists: keep the loaded HTML and measured
// heights, draw the viewport and a screen on either side, and hold the row
// being read when a measurement changes. Paging remains the page's work.
(() => {
  const lists = new Map();
  let insertContent;
  htmx.registerExtension("window-list", {
    init(api) { insertContent = api.insertContent; },
  });

  class WindowList {
    constructor(element) {
      this.element = element;
      element.windowList = this;
      this.items = [];
      this.ends = [];
      this.rows = new Map();
      this.index = new WeakMap();
      this.outside = new Set();
      this.start = this.end = 0;
      this.anchor = null;
      this.pinned = false;
      this.width = element.clientWidth;
      this.observer = new ResizeObserver(() => {
        if (this.width !== element.clientWidth) {
          this.width = element.clientWidth;
          for (const item of this.items) item.height = 128;
        }
        for (const [item, row] of this.rows) item.height = this.height(row);
        this.layout();
      });
      this.top = document.createElement("div");
      this.bottom = document.createElement("div");
      for (const space of [this.top, this.bottom]) {
        space.setAttribute("aria-hidden", "true");
        space.className = "window-space";
        space.style.flex = "none";
      }
      element.prepend(this.top);
      element.append(this.bottom);
      this.observer.observe(element);
      this.take();
    }

    height(row) {
      const style = getComputedStyle(row);
      return row.getBoundingClientRect().height + parseFloat(style.marginTop) + parseFloat(style.marginBottom);
    }

    viewport() {
      let root = this.element;
      while (root && !/auto|scroll/.test(getComputedStyle(root).overflowY)) root = root.parentElement;
      root ||= document.scrollingElement;
      if (root !== this.root) {
        if (this.root && this.root !== this.element) this.observer.unobserve(this.root);
        this.root = root;
        this.observer.observe(root);
      }
      return root;
    }

    viewportTop() {
      return this.root === document.scrollingElement ? 0
        : this.root.getBoundingClientRect().top + this.root.clientTop;
    }

    origin() {
      return this.top.getBoundingClientRect().top - this.viewportTop() + this.root.scrollTop;
    }

    take() {
      let items = [];
      const mounted = [];
      for (const [item, row] of this.rows) {
        if (row.parentElement !== this.element) {
          this.observer.unobserve(row);
          this.rows.delete(item);
        }
      }
      for (const row of this.outside) {
        if (row.parentElement !== this.element) {
          this.observer.unobserve(row);
          this.outside.delete(row);
        }
      }
      for (const row of this.element.children) {
        if (row === this.top) items = items.concat(this.items.slice(0, this.start));
        else if (row === this.bottom) items = items.concat(this.items.slice(this.end));
        else if (row.matches(this.element.dataset.windowList)) {
          let item = this.index.get(row);
          if (!item) {
            item = { html: row.outerHTML, height: this.height(row), data: { ...row.dataset } };
            this.index.set(row, item);
            this.rows.set(item, row);
          }
          items.push(item);
          mounted.push(row);
          this.observer.observe(row);
        } else {
          this.outside.add(row);
          this.observer.observe(row);
        }
      }
      this.items = items;
      items.forEach((item, index) => {
        item.position = index;
        const row = this.rows.get(item);
        if (row) row.dataset.windowIndex = index;
      });
      // A page may arrive above the upper space or below the lower one.
      if (mounted.length) {
        mounted[0].before(this.top);
        mounted.at(-1).after(this.bottom);
        this.start = this.index.get(mounted[0]).position;
        this.end = this.index.get(mounted.at(-1)).position + 1;
      }
      this.layout();
    }

    layout() {
      const root = this.viewport();
      let height = 0;
      this.ends = this.items.map((item) => height += item.height);
      let scroll = root.scrollTop;
      if (this.anchor === "end") scroll = this.origin() + height;
      else if (this.anchor) {
        const { item, offset } = this.anchor;
        scroll = this.origin() + (this.ends[item.position - 1] || 0)
          - (this.pinned ? (root.clientHeight - item.height) / 2 : offset);
      }
      this.render(scroll);
      root.scrollTop = this.anchor === "end" ? root.scrollHeight : scroll;
      this.render();
      if (!this.pinned) this.remember();
    }

    render(scroll = this.viewport().scrollTop) {
      const root = this.viewport();
      if (!root.clientHeight) return;
      scroll -= this.origin();
      const bounds = [];
      for (const edge of [Math.max(0, scroll - root.clientHeight), scroll + root.clientHeight * 2]) {
        let left = 0, right = this.ends.length;
        while (left < right) {
          const middle = (left + right) >>> 1;
          if (this.ends[middle] <= edge) left = middle + 1;
          else right = middle;
        }
        bounds.push(left);
      }
      const [start, edge] = bounds;
      const end = Math.min(this.items.length, edge + 1);
      Alpine.mutateDom(() => {
        for (const [item, row] of this.rows) {
          if (item.position < start || item.position >= end) {
            item.html = row.outerHTML;
            this.observer.unobserve(row);
            Alpine.destroyTree(row);
            insertContent({ target: row, swapSpec: { style: "delete" }, fragment: document.createDocumentFragment() });
            this.rows.delete(item);
          }
        }
        let next = this.top.nextElementSibling;
        for (let index = start; index < end; index++) {
          const item = this.items[index];
          if (this.rows.has(item)) { next = this.rows.get(item).nextElementSibling; continue; }
          const fragment = document.createElement("template");
          fragment.innerHTML = item.html;
          const row = fragment.content.firstElementChild;
          row.dataset.windowIndex = index;
          this.element.insertBefore(row, next);
          this.index.set(row, item);
          this.rows.set(item, row);
          Alpine.initTree(row);
          htmx.process(row);
          this.observer.observe(row);
        }
        this.top.style.height = `${this.ends[start - 1] || 0}px`;
        this.bottom.style.height = `${(this.ends.at(-1) || 0) - (this.ends[end - 1] || 0)}px`;
      });
      this.start = start;
      this.end = end;
      this.element.dispatchEvent(new Event("bazaar:window", { bubbles: true }));
    }

    remember() {
      if (this.element.hasAttribute("data-window-follow")
        && Math.ceil(this.root.scrollTop + this.root.clientHeight) >= this.root.scrollHeight) {
        this.anchor = "end";
        return;
      }
      const top = this.viewportTop();
      const row = [...this.element.children].find((row) => this.index.has(row) && row.getBoundingClientRect().bottom > top);
      this.anchor = row ? { item: this.index.get(row), offset: row.getBoundingClientRect().top - top } : null;
    }

    scrollTo(item, align = "center") {
      this.pinned = align === "center";
      this.anchor = align === "end" ? "end" : { item, offset: 0 };
      this.layout();
    }
  }

  const take = () => {
    for (const [element, list] of lists) {
      if (!element.isConnected) { list.observer.disconnect(); lists.delete(element); }
    }
    for (const element of document.querySelectorAll("[data-window-list]")) {
      if (lists.has(element)) lists.get(element).take();
      else lists.set(element, new WindowList(element));
    }
  };
  document.addEventListener("scroll", (event) => {
    for (const list of lists.values()) {
      if (event.target === list.viewport() || event.target === document && list.root === document.scrollingElement) {
        list.render();
        if (!list.pinned) list.remember();
      }
    }
  }, true);
  for (const name of ["wheel", "touchmove", "keydown", "pointerdown"]) {
    document.addEventListener(name, (event) => {
      for (const list of lists.values()) {
        if (list.pinned && list.viewport().contains(event.target)) {
          list.pinned = false;
          list.remember();
        }
      }
    }, { capture: true, passive: true });
  }
  document.addEventListener("htmx:before:swap", (event) => {
    for (const [element, list] of lists) {
      const replaced = event.detail.tasks.some(({ target, swapSpec }) => {
        if (typeof target === "string") target = document.querySelector(target);
        return /^(innerHTML|outerHTML|innerMorph|outerMorph|outerSync|textContent|delete)$/.test(swapSpec.style)
          && target.contains(element);
      });
      if (replaced) {
        list.observer.disconnect();
        delete element.windowList;
        lists.delete(element);
      } else if (!list.pinned) list.remember();
    }
  });
  document.addEventListener("htmx:after:swap", take);
  document.addEventListener("DOMContentLoaded", take);
})();
