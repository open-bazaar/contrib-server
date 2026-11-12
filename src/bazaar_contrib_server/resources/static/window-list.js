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
      this.items = [];
      this.ends = [];
      this.rows = new Map();
      this.index = new WeakMap();
      this.anchor = null;
      this.width = element.clientWidth;
      this.observer = new ResizeObserver((entries) => {
        let changed = false;
        for (const entry of entries) {
          if (entry.target === element) {
            if (this.width !== element.clientWidth) {
              this.width = element.clientWidth;
              for (const item of this.items) item.height = 128;
              changed = true;
            }
          } else if (this.index.has(entry.target)) {
            const item = this.items[this.index.get(entry.target)];
            const height = this.height(entry.target);
            if (item.height !== height) { item.height = height; changed = true; }
          }
        }
        if (changed) this.layout();
        else this.render();
      });
      this.top = document.createElement("div");
      this.bottom = document.createElement("div");
      for (const space of [this.top, this.bottom]) {
        space.setAttribute("aria-hidden", "true");
        space.className = "window-space";
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
      if (this.root === this.element) return parseFloat(getComputedStyle(this.element).paddingTop);
      return this.element.getBoundingClientRect().top + this.element.clientTop
        + parseFloat(getComputedStyle(this.element).paddingTop)
        - this.viewportTop() + this.root.scrollTop;
    }

    take() {
      const fresh = [...this.element.children].filter((row) => row.matches(this.element.dataset.windowList) && !this.index.has(row));
      for (const row of fresh) {
        const index = this.items.length;
        row.removeAttribute("data-window-index");
        this.items.push({ html: row.outerHTML, height: this.height(row) });
        row.dataset.windowIndex = index;
        this.index.set(row, index);
        this.rows.set(index, row);
        this.observer.observe(row);
      }
      // New pages arrive after the lower space and before their next-page link.
      if (fresh.length) fresh.at(-1).after(this.bottom);
      this.layout();
    }

    layout() {
      const root = this.viewport();
      let height = 0;
      this.ends = this.items.map((item) => height += item.height);
      const scroll = this.anchor
        ? this.origin() + (this.ends[this.anchor.index - 1] || 0) - this.anchor.offset
        : root.scrollTop;
      this.render(scroll);
      root.scrollTop = scroll;
      this.render();
      this.remember();
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
        for (const [index, row] of this.rows) {
          if (index < start || index >= end) {
            this.observer.unobserve(row);
            Alpine.destroyTree(row);
            insertContent({ target: row, swapSpec: { style: "delete" }, fragment: document.createDocumentFragment() });
            this.rows.delete(index);
          }
        }
        let next = this.top.nextElementSibling;
        for (let index = start; index < end; index++) {
          if (this.rows.has(index)) { next = this.rows.get(index).nextElementSibling; continue; }
          const fragment = document.createElement("template");
          fragment.innerHTML = this.items[index].html;
          const row = fragment.content.firstElementChild;
          row.dataset.windowIndex = index;
          this.element.insertBefore(row, next);
          this.index.set(row, index);
          this.rows.set(index, row);
          Alpine.initTree(row);
          htmx.process(row);
          this.observer.observe(row);
        }
        this.top.style.height = `${this.ends[start - 1] || 0}px`;
        this.bottom.style.height = `${(this.ends.at(-1) || 0) - (this.ends[end - 1] || 0)}px`;
      });
      this.element.dispatchEvent(new Event("bazaar:window", { bubbles: true }));
    }

    remember() {
      const top = this.viewportTop();
      const row = [...this.element.children].find((row) => this.index.has(row) && row.getBoundingClientRect().bottom > top);
      this.anchor = row ? { index: this.index.get(row), offset: row.getBoundingClientRect().top - top } : null;
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
        list.remember();
      }
    }
  }, true);
  document.addEventListener("htmx:before:swap", (event) => {
    for (const [element, list] of lists) {
      const replaced = event.detail.tasks.some(({ target, swapSpec }) => {
        if (typeof target === "string") target = document.querySelector(target);
        return /^(innerHTML|outerHTML|innerMorph|outerMorph|outerSync|textContent|delete)$/.test(swapSpec.style)
          && target.contains(element);
      });
      if (replaced) {
        list.observer.disconnect();
        lists.delete(element);
      }
    }
  });
  document.addEventListener("htmx:after:swap", take);
  document.addEventListener("DOMContentLoaded", take);
})();
