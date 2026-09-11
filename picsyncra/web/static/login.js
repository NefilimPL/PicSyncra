const form = document.querySelector("#loginForm");
const message = document.querySelector("#loginMessage");
const usernameInput = form?.querySelector('[name="username"]');
const LAST_LOGIN_USERNAME_KEY = "picsyncra-last-login-username";

try {
  const previousUsername = localStorage.getItem(LAST_LOGIN_USERNAME_KEY) || "";
  if (usernameInput && previousUsername) {
    usernameInput.value = previousUsername;
  }
} catch (_error) {
  // Browsers can disable localStorage; login still works without it.
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "";
  const username = String(new FormData(form).get("username") || "").trim();
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "X-Requested-With": "XMLHttpRequest" },
    body: new FormData(form),
  });
  if (response.ok) {
    try {
      if (username) {
        localStorage.setItem(LAST_LOGIN_USERNAME_KEY, username);
      }
    } catch (_error) {}
    window.location.href = "/";
    return;
  }
  const payload = await response.json().catch(() => ({}));
  message.textContent = payload.detail || "Logowanie nie powiodlo sie.";
});
