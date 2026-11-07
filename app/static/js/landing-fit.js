// Fit every full-screen landing section to exactly one viewport.
// CSS locks .l-sec.full to 100svh; if a section's content is still taller
// than the space available (short laptop screens, many events), this scales
// that section's content down with CSS `zoom` until it fits. Below a readable
// floor it gives up and lets the section grow instead of clipping content.
(function () {
  'use strict';
  var MIN_SCALE_DESKTOP = 0.6;
  var MIN_SCALE_MOBILE = 0.74;

  function fitOne(sec) {
    var wrap = sec.querySelector(':scope > .l-wrap');
    if (!wrap) return;
    wrap.style.zoom = '';
    sec.classList.remove('fit-released');
    var cs = getComputedStyle(sec);
    if (cs.height === 'auto' || cs.overflow !== 'hidden') return; // fixed-height mode is off
    var avail = sec.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    // getBoundingClientRect reports the rendered (zoomed) size
    var need = wrap.getBoundingClientRect().height;
    if (need <= avail) return;
    var floor = window.innerWidth < 900 ? MIN_SCALE_MOBILE : MIN_SCALE_DESKTOP;
    var scale = 1;
    // zoom reflows text, so converge in a few passes
    for (var i = 0; i < 4 && need > avail; i++) {
      scale = Math.max(floor, Math.floor(scale * (avail / need) * 1000) / 1000 - 0.005);
      wrap.style.zoom = scale;
      need = wrap.getBoundingClientRect().height;
      if (scale === floor) break;
    }
    if (need > avail + 2) {
      wrap.style.zoom = '';
      sec.classList.add('fit-released'); // too much to fit legibly: let it grow
    }
  }

  function fitAll() {
    Array.prototype.forEach.call(document.querySelectorAll('.l-sec.full'), fitOne);
  }

  var t;
  function schedule() { clearTimeout(t); t = setTimeout(fitAll, 120); }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fitAll); else fitAll();
  window.addEventListener('load', fitAll);
  window.addEventListener('resize', schedule, { passive: true });
  window.addEventListener('orientationchange', schedule);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitAll);
  // late images (banners, lazy photos) can change heights
  Array.prototype.forEach.call(document.querySelectorAll('.l-sec.full img'), function (img) {
    if (!img.complete) img.addEventListener('load', schedule, { once: true });
  });
})();
