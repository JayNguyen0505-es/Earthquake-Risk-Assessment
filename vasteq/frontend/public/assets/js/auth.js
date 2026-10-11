import { user } from "./api.js";
import { save } from "./session.js";
import { $, $$, msg, busy } from "./ui.js";

const form = $("form");
const reg = form.id === "register";
const name = $("#name");
const email = $("#email");
const pass = $("#pass");
const confirm = $("#confirm");
const fields = $$("input", form);
const alert = $("#error");
let pending = false;

function error(field, text) {
  $(`#${field.id}-error`).textContent = text;
  field.setAttribute("aria-invalid", !!text);
  field.closest(".field").classList.toggle("invalid", !!text);
}

function check(field) {
  let text = "";
  if (field === name) {
    if (!field.value.trim()) text = "Enter your display name.";
  } else if (field === email) {
    field.value = field.value.trim();
    if (!field.value) text = "Enter your email address.";
    else if (field.validity.typeMismatch) text = "Enter a valid email address.";
  } else if (field === pass) {
    if (!field.value) text = reg ? "Enter a password." : "Enter your password.";
    else if (reg && field.value.length < 12) text = "Use 12–128 characters.";
  } else if (field === confirm) {
    if (!field.value) text = "Confirm your password.";
    else if (field.value !== pass.value) text = "Passwords do not match.";
  }
  error(field, text);
  return !text;
}

for (const field of fields) {
  field.onblur = () => check(field);
  field.oninput = () => {
    msg(alert);
    if (field.getAttribute("aria-invalid") === "true") check(field);
    if (field === pass && confirm?.value) check(confirm);
  };
}

for (const btn of $$("[data-pass]")) {
  btn.onclick = () => {
    const field = $(`#${btn.dataset.pass}`);
    const show = field.type === "password";
    field.type = show ? "text" : "password";
    btn.textContent = show ? "Hide" : "Show";
    btn.setAttribute("aria-pressed", show);
    btn.setAttribute("aria-label", `${btn.textContent} ${field === confirm ? "confirmation password" : "password"}`);
  };
}

function wait(on) {
  pending = on;
  busy(form, on);
  $("#submit-text").textContent = reg
    ? (on ? "Creating account…" : "Create account") : (on ? "Signing in…" : "Sign in");
  $(".spinner").hidden = !on;
  $("#status").textContent = on ? (reg ? "Creating your account." : "Signing you in.") : "";
}

form.onsubmit = async e => {
  e.preventDefault();
  if (pending) return;
  msg(alert);
  if (!fields.map(check).every(Boolean)) {
    $("[aria-invalid=true]", form).focus();
    return;
  }
  wait(true);
  try {
    if (reg) {
      await user.register({ displayName: name.value.trim(), email: email.value, password: pass.value });
      form.reset();
      form.hidden = true;
      $("#auth-foot").hidden = true;
      $("#success").hidden = false;
      $("#title").textContent = "Account created successfully";
      $("#subtitle").textContent = "You can now sign in to VAST-Earthquake.";
      $("#title").focus();
    } else {
      const data = await user.login(email.value, pass.value);
      save(data.accessToken);
      form.reset();
      location.replace("index.html");
    }
  } catch (err) {
    if (reg && err.code === "email_exists") {
      error(email, "An account with this email already exists. Try signing in.");
    } else {
      msg(alert, !reg && err.status === 401
        ? "Email or password is incorrect, or your account is disabled."
        : err.status === 400 ? `Please check your ${reg ? "name, email, and password" : "email and password"}, then try again.`
        : err.status ? `We couldn't ${reg ? "create your account" : "sign you in"}. Please try again.` : err.message);
    }
  } finally {
    wait(false);
    if (!form.hidden && email.getAttribute("aria-invalid") === "true") email.focus();
  }
};
