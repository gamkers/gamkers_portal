// Team portal: copy/share links, local photo preview, double-submit guard.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const url = button.dataset.copy;
      const label = button.querySelector("[data-copy-label]");
      const original = label ? label.textContent : "";
      const title = button.dataset.shareTitle;
      if (title && navigator.share && window.matchMedia("(pointer: coarse)").matches) {
        try { await navigator.share({ title, url }); return; } catch (error) { /* fall back to copy */ }
      }
      try {
        await navigator.clipboard.writeText(url);
        if (label) label.textContent = "Link copied!";
      } catch (error) {
        window.prompt("Copy this link:", url);
      }
      if (label) setTimeout(() => { label.textContent = original; }, 2000);
    });
  });

  const input = document.querySelector("[data-photo-input]");
  const preview = document.querySelector("[data-photo-preview]");
  if (input && preview) {
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (!file || !file.type.startsWith("image/")) return;
      const reader = new FileReader();
      reader.addEventListener("load", () => {
        preview.src = reader.result; // data: URL — allowed by the img-src CSP
        preview.classList.remove("tm-hidden");
        const empty = document.querySelector("[data-photo-preview-empty]");
        if (empty) empty.classList.add("tm-hidden");
      });
      reader.readAsDataURL(file);
    });
  }

  document.querySelectorAll("form[data-submit-once]").forEach((form) => {
    form.addEventListener("submit", () => {
      form.querySelectorAll("button[type=submit]").forEach((button) => { button.disabled = true; });
    });
  });
});
