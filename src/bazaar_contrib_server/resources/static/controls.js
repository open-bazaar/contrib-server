// What the browser would draw over a page, the page draws in its theme: the
// list a select opens, the line under a field left wrong, and the hint of
// what is pointed at.
(() => {
  const root = document.documentElement;
  // a select shows as its page draws it and opens only here, never the
  // browser's own list
  root.classList.add("chooses");
  const drawn = () => document.querySelector("template[data-controls]");

  // What opens over a page is drawn in the outermost window of the server,
  // over every frame, as the browser draws its own: the windows from this
  // page out to that one, whose scrolling moves the page under the reader.
  const windows = () => {
    const out = [window];
    try {
      while (out.at(-1) !== out.at(-1).parent && out.at(-1).frameElement) out.push(out.at(-1).parent);
    } catch {
      // a page framed by another site draws within its own frame
    }
    return out;
  };
  // where a box of this page is in the outermost window
  const placed = (element, out) => {
    const box = element.getBoundingClientRect();
    let top = box.top;
    let left = box.left;
    for (const here of out.slice(0, -1)) {
      const frame = here.frameElement.getBoundingClientRect();
      top += frame.top;
      left += frame.left;
    }
    return { top, left, bottom: top + box.height, right: left + box.width, width: box.width };
  };

  // A select's list: under its box on a wide screen, over it when there is
  // more room there; from the bottom on a narrow one. It is read and chosen
  // from with the select still focused, as the browser's own would be: the
  // keys move the select itself through its options, so a screen reader
  // reads each one, and only a choice changes it; closed without one, it
  // goes back to the option it had.
  let open = null;
  const close = (chosen = null) => {
    if (!open) return;
    const { select, layer, around, had } = open;
    open = null;
    layer.remove();
    select.setAttribute("aria-expanded", "false");
    for (const one of around) {
      one.removeEventListener("scroll", moved, true);
      one.removeEventListener("resize", left);
      one.document.removeEventListener("mousedown", away, true);
    }
    select.selectedIndex = chosen ?? had;
    if (chosen === null || chosen === had) return;
    // what follows is the reader's doing, as with the browser's own list
    for (const name of ["input", "change"]) {
      const event = new Event(name, { bubbles: true });
      event.byReader = true;
      select.dispatchEvent(event);
    }
  };
  const left = () => close();
  const moved = (event) => {
    if (!open?.layer.contains(event.target)) close();
  };
  // pressed anywhere but on the list or its box, it closes
  const away = (event) => {
    if (open && !open.layer.contains(event.target) && !open.select.parentElement.contains(event.target)) close();
  };
  const light = (item) => {
    if (!open || !item || item.getAttribute("aria-disabled") === "true") return;
    open.items.forEach((one) => one.classList.toggle("active", one === item));
    item.scrollIntoView({ block: "nearest" });
  };
  const move = (item) => {
    if (!item) return;
    light(item);
    open.select.selectedIndex = item.option.index;
  };
  const take = (item) => close(item.option.index);
  const named = (select) => {
    if (select.getAttribute("aria-label")) return select.getAttribute("aria-label");
    const label = select.id ? document.querySelector(`label[for="${CSS.escape(select.id)}"]`) : null;
    if (!label) return "";
    const words = label.cloneNode(true);
    words.querySelectorAll(".req").forEach((one) => one.remove());
    return words.textContent.trim();
  };
  const choose = (select) => {
    close();
    const around = windows();
    const outer = around.at(-1);
    const made = (tag, name) => Object.assign(outer.document.createElement(tag), { className: name });
    const list = made("div", "choices");
    list.setAttribute("role", "listbox");
    const items = [...select.options].map((option) => {
      const item = made("div", "choice");
      item.option = option;
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", String(option.selected));
      if (option.disabled) item.setAttribute("aria-disabled", "true");
      item.append(Object.assign(made("span", ""), { textContent: option.text }));
      if (option.selected) item.append(drawn().content.querySelector(".tick").cloneNode(true));
      list.append(item);
      return item;
    });
    const layer = made("div", "choosing");
    if (root.dataset.layout === "narrow") {
      const tray = made("div", "tray");
      tray.append(made("span", "grab"));
      const name = named(select);
      if (name) tray.append(Object.assign(made("b", ""), { textContent: name }));
      tray.append(list);
      layer.append(made("div", "scrim"), tray);
      outer.document.body.append(layer);
    } else {
      layer.append(list);
      outer.document.body.append(layer);
      const box = placed(select.parentElement, around);
      const below = outer.innerHeight - box.bottom - 14;
      const above = box.top - 14;
      const tall = list.offsetHeight;
      const under = tall <= below || below >= above;
      const height = Math.min(tall, under ? below : above);
      const width = Math.max(list.offsetWidth, box.width);
      Object.assign(list.style, {
        minWidth: `${box.width}px`,
        maxHeight: `${height}px`,
        top: `${under ? box.bottom + 6 : box.top - 6 - height}px`,
        left: `${Math.max(8, Math.min(box.left, outer.innerWidth - 8 - width))}px`,
      });
    }
    // the select keeps the focus: what is pressed over the list does not take it
    layer.addEventListener("mousedown", (event) => event.preventDefault());
    layer.addEventListener("click", (event) => {
      const item = event.target.closest(".choice");
      if (item && item.getAttribute("aria-disabled") !== "true") take(item);
      else if (event.target.closest(".scrim")) close();
    });
    layer.addEventListener("mousemove", (event) => {
      const item = event.target.closest(".choice");
      if (item && !item.classList.contains("active")) light(item);
    });
    for (const one of around) {
      one.addEventListener("scroll", moved, true);
      one.addEventListener("resize", left);
      one.document.addEventListener("mousedown", away, true);
    }
    open = { select, layer, items, around, had: select.selectedIndex };
    select.setAttribute("aria-expanded", "true");
    light(items[select.selectedIndex] ?? items.find((item) => !item.option.disabled));
  };

  // what pressed last: a select a finger or a pen opened is not focused,
  // since a phone opens its own list for a focused select
  let pressed = "mouse";
  document.addEventListener("pointerdown", (event) => (pressed = event.pointerType), true);
  document.addEventListener("click", (event) => {
    const select = event.target.closest?.(":has(> select)")?.querySelector(":scope > select");
    if (!select || select.disabled) return;
    event.preventDefault();
    if (open?.select === select) return close();
    if (pressed === "mouse") select.focus({ preventScroll: true });
    choose(select);
  });
  let typed = "";
  let typing = null;
  document.addEventListener(
    "keydown",
    (event) => {
      const select = event.target;
      if (!(select instanceof HTMLSelectElement) || event.ctrlKey || event.metaKey) return;
      if (open?.select !== select) {
        if ([" ", "Enter", "ArrowDown", "ArrowUp", "F4"].includes(event.key)) {
          event.preventDefault();
          choose(select);
        }
        return;
      }
      const items = open.items.filter((item) => item.getAttribute("aria-disabled") !== "true");
      const at = items.findIndex((item) => item.classList.contains("active"));
      const to = {
        ArrowDown: Math.min(at + 1, items.length - 1),
        ArrowUp: Math.max(at - 1, 0),
        Home: 0,
        End: items.length - 1,
        PageDown: Math.min(at + 10, items.length - 1),
        PageUp: Math.max(at - 10, 0),
      }[event.key];
      if (to !== undefined) move(items[to]);
      else if (event.key === "Enter" || (event.key === " " && !typed)) {
        if (items[at]) take(items[at]);
      } else if (event.key === "Escape") close();
      else if (event.key === "Tab") return close();
      else if (event.key.length === 1) {
        // letters typed together find the next option they begin
        clearTimeout(typing);
        typing = setTimeout(() => (typed = ""), 600);
        typed += event.key.toLowerCase();
        const next = [...items.slice(at + (typed.length === 1 ? 1 : 0)), ...items].find((item) =>
          item.option.text.trim().toLowerCase().startsWith(typed),
        );
        move(next);
      } else return;
      event.preventDefault();
      event.stopPropagation();
    },
    true,
  );
  addEventListener("blur", left);
  addEventListener("pagehide", left);
  // a page changed in place takes the select its list was for
  document.addEventListener("htmx:after:swap", () => {
    if (open && !open.select.isConnected) close();
  });

  // A field left wrong says so under itself, in the page's words, and once
  // it changes says no more; the first one is where the reader is taken.
  let first = null;
  const said = (field) => {
    const words = drawn()?.dataset ?? {};
    const state = field.validity;
    if (state.valueMissing) return field.matches("select, [type=radio], [type=checkbox]") ? words.choose : words.required;
    if (state.badInput) return words.number;
    if (state.rangeUnderflow) return words.under?.replace("{n}", field.min);
    if (state.stepMismatch && field.step === "1") return words.whole;
    return field.validationMessage;
  };
  document.addEventListener(
    "invalid",
    (event) => {
      const field = event.target;
      event.preventDefault();
      if (!first) {
        first = field;
        queueMicrotask(() => {
          first.focus();
          first = null;
        });
      }
      field.setAttribute("aria-invalid", "true");
      const lone = field.matches("[type=radio], [type=checkbox]");
      const after = lone ? field.closest(".field") : (field.closest(".input") ?? field);
      if (!after) return;
      let problem = lone ? after.querySelector(":scope > .problem") : after.nextElementSibling;
      if (!problem?.matches(".problem")) {
        problem = document.createElement("span");
        problem.className = "problem";
        problem.setAttribute("role", "alert");
        problem.append(drawn()?.content.querySelector(".mark")?.cloneNode(true) ?? "", document.createElement("span"));
        if (lone) after.append(problem);
        else after.after(problem);
      }
      problem.lastElementChild.textContent = said(field) || field.validationMessage;
      field.problem = problem;
    },
    true,
  );
  const mended = (event) => {
    const field = event.target;
    if (!field.problem) return;
    const radios =
      field.form && field.matches("[type=radio]")
        ? field.form.querySelectorAll(`[type=radio][name="${CSS.escape(field.name)}"]`)
        : [];
    for (const one of [field, ...radios]) {
      one.problem?.remove();
      one.problem = null;
      one.removeAttribute("aria-invalid");
    }
  };
  document.addEventListener("input", mended);
  document.addEventListener("change", mended);

  // A hint for what is pointed at with a mouse or reached by keyboard, from
  // its data-tip: under it, or over it where there is no room under.
  let tip = null;
  let tipped = null;
  let waiting = null;
  const drop = () => {
    clearTimeout(waiting);
    tip?.remove();
    tip = null;
  };
  const hide = () => {
    drop();
    tipped = null;
  };
  const hint = (target) => {
    hide();
    tipped = target;
    waiting = setTimeout(() => {
      if (!target.isConnected || open) return;
      const around = windows();
      const outer = around.at(-1);
      tip = Object.assign(outer.document.createElement("div"), { className: "tooltip", textContent: target.dataset.tip });
      tip.setAttribute("role", "tooltip");
      outer.document.body.append(tip);
      const box = placed(target, around);
      const under = box.bottom + 8 + tip.offsetHeight <= outer.innerHeight - 8;
      const middle = box.left + box.width / 2;
      const left = Math.max(8, Math.min(middle - tip.offsetWidth / 2, outer.innerWidth - 8 - tip.offsetWidth));
      tip.classList.add(under ? "under" : "over");
      Object.assign(tip.style, {
        left: `${left}px`,
        top: `${under ? box.bottom + 8 : box.top - 8 - tip.offsetHeight}px`,
      });
      tip.style.setProperty("--x", `${middle - left}px`);
    }, 400);
  };
  document.addEventListener("pointerover", (event) => {
    if (event.pointerType !== "mouse") return;
    const target = event.target.closest?.("[data-tip]") ?? null;
    if (target === tipped) return;
    if (target) hint(target);
    else hide();
  });
  document.addEventListener("pointerout", (event) => {
    if (!event.relatedTarget) hide();
  });
  document.addEventListener("focusin", (event) => {
    if (event.target.matches?.("[data-tip]:focus-visible")) hint(event.target);
  });
  document.addEventListener("focusout", hide);
  addEventListener("pagehide", hide);
  // pressed or scrolled, the hint goes and stays gone while still pointed at
  document.addEventListener("pointerdown", drop);
  document.addEventListener("scroll", drop, true);
})();
