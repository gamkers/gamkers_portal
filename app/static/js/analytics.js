// Hover/focus tooltips for the analytics charts. Values are also in the table views.
document.addEventListener("DOMContentLoaded", () => {
  const tooltip = document.querySelector(".an-tooltip");
  if (!tooltip) return;
  const valueEl = tooltip.querySelector(".an-tooltip-value");
  const labelEl = tooltip.querySelector(".an-tooltip-label");

  const place = (x, y) => {
    const box = tooltip.getBoundingClientRect();
    const left = Math.min(Math.max(8, x - box.width / 2), window.innerWidth - box.width - 8);
    const top = y - box.height - 12 < 8 ? y + 16 : y - box.height - 12;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  };

  const show = (target, x, y) => {
    valueEl.textContent = target.dataset.tipValue;
    labelEl.textContent = target.dataset.tipLabel;
    tooltip.hidden = false;
    place(x, y);
  };

  const hide = () => {
    tooltip.hidden = true;
  };

  document.querySelectorAll("[data-tip-value]").forEach((target) => {
    target.addEventListener("pointermove", (event) => show(target, event.clientX, event.clientY));
    target.addEventListener("pointerleave", hide);
    target.addEventListener("focus", () => {
      const box = target.getBoundingClientRect();
      show(target, box.left + box.width / 2, box.top);
    });
    target.addEventListener("blur", hide);
  });
  window.addEventListener("scroll", hide, { passive: true });
});
