import { userApi } from "./api.js";

const form = document.querySelector("#register-form");
const name = document.querySelector("#display-name");
const email = document.querySelector("#email");
const password = document.querySelector("#password");
const confirmation = document.querySelector("#confirm-password");
const inputs = [name, email, password, confirmation];
const submit = document.querySelector("#submit-button");
const label = document.querySelector("#submit-label");
const alert = document.querySelector("#form-error");
const status = document.querySelector("#form-status");
let submitting = false;

function setError(input, message) {
  document.getElementById(`${input.id}-error`).textContent = message;
  input.setAttribute("aria-invalid", String(Boolean(message)));
  input.closest(".outlined-field").classList.toggle("invalid", Boolean(message));
}

function validate(input) {
  let message = "";
  if (input === name) {
    if (!input.value.trim()) message = "Enter your display name.";
    else if (input.value.trim().length > 120) message = "Use no more than 120 characters.";
  } else if (input === email) {
    input.value = input.value.trim();
    if (!input.value) message = "Enter your email address.";
    else if (input.validity.typeMismatch || input.value.length > 254) message = "Enter a valid email address.";
  } else if (input === password) {
    if (!input.value) message = "Enter a password.";
    else if (input.value.length < 12 || input.value.length > 128) message = "Use 12–128 characters.";
  } else if (input === confirmation) {
    if (!input.value) message = "Confirm your password.";
    else if (input.value !== password.value) message = "Passwords do not match.";
  }
  setError(input, message);
  return !message;
}

for (const input of inputs) {
  input.addEventListener("blur", () => validate(input));
  input.addEventListener("input", () => {
    alert.hidden = true;
    if (input.getAttribute("aria-invalid") === "true") validate(input);
    if (input === password && confirmation.value) validate(confirmation);
  });
}

for (const button of document.querySelectorAll("[data-password-target]")) {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordTarget);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "Hide" : "Show";
    button.setAttribute("aria-pressed", String(show));
    button.setAttribute("aria-label", `${show ? "Hide" : "Show"} ${input === confirmation ? "confirmation password" : "password"}`);
  });
}

function setBusy(busy) {
  submitting = busy;
  form.setAttribute("aria-busy", String(busy));
  for (const control of form.querySelectorAll("input, button")) control.disabled = busy;
  label.textContent = busy ? "Creating account…" : "Create account";
  submit.querySelector(".button-spinner").hidden = !busy;
  status.textContent = busy ? "Creating your account." : "";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submitting) return;
  alert.hidden = true;
  const valid = inputs.map(validate).every(Boolean);
  if (!valid) {
    inputs.find(input => input.getAttribute("aria-invalid") === "true").focus();
    return;
  }
  const account = { displayName: name.value.trim(), email: email.value.trim(), password: password.value };
  setBusy(true);
  try {
    await userApi.register(account);
    form.reset();
    form.hidden = true;
    document.querySelector("#auth-footer").hidden = true;
    document.querySelector("#registration-success").hidden = false;
    const title = document.querySelector("#page-title");
    title.textContent = "Account created successfully";
    document.querySelector("#page-subtitle").textContent = "You can now sign in to VAST-Earthquake.";
    title.focus();
  } catch (error) {
    if (error.status === 409 && error.code === "email_exists") {
      setError(email, "An account with this email already exists. Try signing in.");
      // Focus after controls are enabled again below.
    } else {
      alert.textContent = error.status === 400
        ? "Please check your name, email, and password, then try again."
        : error.status === 0 ? error.message : "We couldn't create your account. Please try again.";
      alert.hidden = false;
    }
  } finally {
    setBusy(false);
    if (!form.hidden && email.getAttribute("aria-invalid") === "true") email.focus();
  }
});
