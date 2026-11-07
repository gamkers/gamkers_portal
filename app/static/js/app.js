document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});

document.addEventListener("click", async (event) => {
  const button = event.target instanceof Element
    ? event.target.closest("[data-copy-link]")
    : null;
  if (!button) return;
  const input = button.parentElement.querySelector("input");
  if (!input) return;

  try {
    await navigator.clipboard.writeText(input.value);
    button.textContent = "Copied";
  } catch {
    try {
      input.focus();
      input.select();
      const copied = document.execCommand("copy");
      button.textContent = copied ? "Copied" : "Copy failed";
    } catch {
      button.textContent = "Copy failed";
    }
  }
});
