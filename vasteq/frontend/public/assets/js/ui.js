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
