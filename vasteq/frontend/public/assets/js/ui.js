export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];

export function el(tag, text = "", cls = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = cls;
  return node;
}

export function msg(node, text = "") {
  node.textContent = text;
  node.hidden = !text;
}

export function busy(form, on) {
  form.setAttribute("aria-busy", on);
  for (const field of $$("input, select, button", form)) field.disabled = on;
}

export function toast(text, bad = false) {
  const box = el("div", "", `toast-item${bad ? " error" : ""}`);
  const close = el("button", "×", "btn");
  close.type = "button";
  close.setAttribute("aria-label", "Dismiss notification");
  box.append(el("p", text), close);
  $("#toasts").append(box);
  let timer;
  const stop = () => clearTimeout(timer);
  const hide = () => { stop(); box.remove(); };
  const start = () => { stop(); timer = setTimeout(hide, bad ? 10000 : 6000); };
  box.onmouseenter = box.onfocusin = stop;
  box.onmouseleave = box.onfocusout = start;
  close.onclick = hide;
  start();
}
