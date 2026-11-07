// Lightweight animated "network" background (~3 KB, no dependencies).
// Replaces VANTA (three.js + p5.js, ~1.6 MB). Draws into a <canvas> inside any
// element with [data-net-bg]. Runs only while the element is on screen and the
// tab is visible, caps device-pixel-ratio and node count, and is skipped
// entirely for users who prefer reduced motion.
(function () {
  'use strict';
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  function NetBg(host) {
    var canvas = document.createElement('canvas');
    canvas.className = 'net-bg-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    host.insertBefore(canvas, host.firstChild);
    var ctx = canvas.getContext('2d');
    if (!ctx) return;

    var dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    var w = 0, h = 0, nodes = [], running = false, onScreen = false, raf = 0;
    var linkDist = 140, mouse = { x: -9999, y: -9999 };

    function resize() {
      var r = host.getBoundingClientRect();
      w = Math.max(1, r.width); h = Math.max(1, r.height);
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      var count = Math.round(Math.min(60, Math.max(18, (w * h) / 26000)));
      nodes = [];
      for (var i = 0; i < count; i++) {
        nodes.push({ x: Math.random() * w, y: Math.random() * h,
                     vx: (Math.random() - 0.5) * 0.35, vy: (Math.random() - 0.5) * 0.35 });
      }
    }

    function frame() {
      if (!running) return;
      ctx.clearRect(0, 0, w, h);
      var i, j, a, b, dx, dy, d2, max2 = linkDist * linkDist;
      for (i = 0; i < nodes.length; i++) {
        a = nodes[i];
        a.x += a.vx; a.y += a.vy;
        if (a.x < 0 || a.x > w) a.vx *= -1;
        if (a.y < 0 || a.y > h) a.vy *= -1;
      }
      ctx.lineWidth = 1;
      for (i = 0; i < nodes.length; i++) {
        a = nodes[i];
        for (j = i + 1; j < nodes.length; j++) {
          b = nodes[j]; dx = a.x - b.x; dy = a.y - b.y; d2 = dx * dx + dy * dy;
          if (d2 < max2) {
            ctx.strokeStyle = 'rgba(34,197,94,' + (0.22 * (1 - d2 / max2)).toFixed(3) + ')';
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
        dx = a.x - mouse.x; dy = a.y - mouse.y; d2 = dx * dx + dy * dy;
        if (d2 < 32000) {
          ctx.strokeStyle = 'rgba(74,222,128,' + (0.35 * (1 - d2 / 32000)).toFixed(3) + ')';
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(mouse.x, mouse.y); ctx.stroke();
        }
      }
      ctx.fillStyle = 'rgba(74,222,128,0.75)';
      for (i = 0; i < nodes.length; i++) {
        ctx.beginPath(); ctx.arc(nodes[i].x, nodes[i].y, 1.6, 0, 6.2832); ctx.fill();
      }
      raf = requestAnimationFrame(frame);
    }

    function update() {
      var should = onScreen && !document.hidden;
      if (should && !running) { running = true; raf = requestAnimationFrame(frame); }
      else if (!should && running) { running = false; cancelAnimationFrame(raf); }
    }

    host.addEventListener('mousemove', function (e) {
      var r = host.getBoundingClientRect(); mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top;
    }, { passive: true });
    host.addEventListener('mouseleave', function () { mouse.x = mouse.y = -9999; });

    var resizeTimer;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer); resizeTimer = setTimeout(resize, 200);
    }, { passive: true });
    document.addEventListener('visibilitychange', update);

    resize();
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        onScreen = entries[0].isIntersecting; update();
      }).observe(host);
    } else { onScreen = true; update(); }
  }

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-net-bg]'), function (el) { NetBg(el); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
