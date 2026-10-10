import { userApi, ApiError } from "./api.js";
import { saveToken } from "./session.js";

const form = document.querySelector("#login-form");
const email = document.querySelector("#email");
const password = document.querySelector("#password");
const inputs = [email, password];
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
  if (input === email) {
    input.value = input.value.trim();
    if (!input.value) message = "Enter your email address.";
    else if (input.validity.typeMismatch || input.value.length > 254) message = "Enter a valid email address.";
  } else {
    if (!input.value) message = "Enter your password.";
    else if (input.value.length > 128) message = "Use no more than 128 characters.";
  }
  setError(input, message);
  return !message;
}

for (const input of inputs) {
  input.addEventListener("blur", () => validate(input));
  input.addEventListener("input", () => {
    alert.hidden = true;
    if (input.getAttribute("aria-invalid") === "true") validate(input);
  });
}

const toggle = document.querySelector("[data-password-target]");
toggle.addEventListener("click", () => {
  const show = password.type === "password";
  password.type = show ? "text" : "password";
  toggle.textContent = show ? "Hide" : "Show";
  toggle.setAttribute("aria-pressed", String(show));
  toggle.setAttribute("aria-label", show ? "Hide password" : "Show password");
});

function setBusy(busy) {
  submitting = busy;
  form.setAttribute("aria-busy", String(busy));
  for (const control of form.querySelectorAll("input, button")) control.disabled = busy;
  label.textContent = busy ? "Signing in…" : "Sign in";
  document.querySelector(".button-spinner").hidden = !busy;
  status.textContent = busy ? "Signing you in." : "";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submitting) return;
  alert.hidden = true;
  if (!inputs.map(validate).every(Boolean)) {
    inputs.find(input => input.getAttribute("aria-invalid") === "true").focus();
    return;
  }
  setBusy(true);
  try {
    const response = await userApi.login(email.value.trim(), password.value);
    if (!response || typeof response.accessToken !== "string" || !response.accessToken.trim()
        || response.tokenType !== "Bearer") {
      throw new ApiError("The server returned an invalid response.", 200, "invalid_response");
    }
    try {
      saveToken(response.accessToken);
    } catch {
      throw new ApiError("Your browser couldn't save this session. Allow site storage and try again.", 0, "storage_unavailable");
    }
    form.reset();
    window.location.replace("index.html");
  } catch (error) {
    alert.textContent = error.status === 401
      ? "Email or password is incorrect, or your account is disabled."
      : error.status === 400 ? "Please check your email and password, then try again."
      : error.status === 0 || error.code === "invalid_response" ? error.message
      : "We couldn't sign you in. Please try again.";
    alert.hidden = false;
    setBusy(false);
  }
});
