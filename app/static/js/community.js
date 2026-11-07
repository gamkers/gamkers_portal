// GAMKERS community landing — progressive enhancement only (CSP: script-src 'self').
(function () {
  'use strict';

  // Reveal on scroll
  var revealEls = document.querySelectorAll('.anim-fade-in, .anim-slide-left, .section-divider, .l-reveal, .l-stagger');

  // Cursor-following glow on landing cards (sets CSS vars only)
  Array.prototype.forEach.call(document.querySelectorAll('.l-card'), function (card) {
    card.addEventListener('mousemove', function (e) {
      var r = card.getBoundingClientRect();
      card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      card.style.setProperty('--my', (e.clientY - r.top) + 'px');
    }, { passive: true });
  });
  if ('IntersectionObserver' in window && revealEls.length) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('visible'); io.unobserve(e.target); }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add('visible'); });
  }

  // Sticky nav background on scroll
  var nav = document.querySelector('.c-nav');
  var links = Array.prototype.slice.call(document.querySelectorAll('.c-nav-links a[data-section]'));
  var sections = links
    .map(function (a) { return document.getElementById(a.getAttribute('data-section')); })
    .filter(Boolean);

  function onScroll() {
    if (nav) { nav.classList.toggle('scrolled', window.scrollY > 80); }
    var pos = window.scrollY + 120;
    var current = null;
    sections.forEach(function (sec) {
      if (pos >= sec.offsetTop && pos < sec.offsetTop + sec.offsetHeight) { current = sec.id; }
    });
    links.forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('data-section') === current);
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // Stat counters: count up once when scrolled into view
  var counters = document.querySelectorAll('[data-count]');
  function runCounter(el) {
    var raw = el.getAttribute('data-count') || '0';
    var target = parseFloat(raw) || 0;
    var decimals = (raw.split('.')[1] || '').length;
    var suffix = el.getAttribute('data-suffix') || '';
    var useComma = el.hasAttribute('data-comma');
    var start = null, dur = 1200;
    function fmt(n) {
      if (decimals) return n.toFixed(decimals);
      n = Math.round(n);
      return useComma ? n.toLocaleString('en-IN') : String(n);
    }
    function step(t) {
      if (start === null) start = t;
      var p = Math.min(1, (t - start) / dur);
      el.textContent = fmt(target * (1 - Math.pow(1 - p, 3))) + suffix;
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  if (counters.length) {
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || !('IntersectionObserver' in window)) {
      Array.prototype.forEach.call(counters, function (el) {
        var n = parseFloat(el.getAttribute('data-count')) || 0;
        el.textContent = (el.hasAttribute('data-comma') ? n.toLocaleString('en-IN') : n) + (el.getAttribute('data-suffix') || '');
      });
    } else {
      var cio = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { if (e.isIntersecting) { runCounter(e.target); cio.unobserve(e.target); } });
      }, { threshold: 0.4 });
      Array.prototype.forEach.call(counters, function (el) { cio.observe(el); });
    }
  }

  // Next-event countdown ticket
  var cd = document.querySelector('[data-countdown]');
  if (cd) {
    var targetTime = Date.parse(cd.getAttribute('data-countdown'));
    var parts = {
      d: cd.querySelector('[data-cd="d"]'), h: cd.querySelector('[data-cd="h"]'),
      m: cd.querySelector('[data-cd="m"]'), s: cd.querySelector('[data-cd="s"]')
    };
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    var tick = function () {
      var diff = Math.max(0, targetTime - Date.now());
      var s = Math.floor(diff / 1000);
      if (parts.d) parts.d.textContent = pad(Math.floor(s / 86400));
      if (parts.h) parts.h.textContent = pad(Math.floor((s % 86400) / 3600));
      if (parts.m) parts.m.textContent = pad(Math.floor((s % 3600) / 60));
      if (parts.s) parts.s.textContent = pad(s % 60);
      if (diff <= 0) { clearInterval(timer); }
    };
    var timer = setInterval(tick, 1000);
    tick();
  }

  // Product detail page: gallery thumbnails swap the main image
  var mainImg = document.querySelector('.pdp-main img');
  var caption = document.querySelector('.pdp-caption');
  var thumbs = Array.prototype.slice.call(document.querySelectorAll('.pdp-thumb'));
  thumbs.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var src = btn.getAttribute('data-src');
      var label = btn.getAttribute('data-label') || '';
      if (mainImg && src) {
        mainImg.src = src;
        mainImg.alt = label;
        // restart the fade-in animation
        mainImg.style.animation = 'none';
        void mainImg.offsetWidth;
        mainImg.style.animation = '';
      }
      if (caption) { caption.textContent = label; }
      thumbs.forEach(function (t) { t.classList.remove('active'); });
      btn.classList.add('active');
    });
  });

  // Event forms: lock the submit button after the first click (no double submissions)
  Array.prototype.forEach.call(document.querySelectorAll('form[data-submit-once]'), function (form) {
    form.addEventListener('submit', function () {
      Array.prototype.forEach.call(form.querySelectorAll('button[type="submit"]'), function (btn) {
        btn.disabled = true;
        btn.textContent = 'Submitting…';
      });
    });
  });

  // Event page: registration dialog (Luma-style modal)
  Array.prototype.forEach.call(document.querySelectorAll('[data-open-dialog]'), function (btn) {
    var dlg = document.getElementById(btn.getAttribute('data-open-dialog'));
    if (!dlg || typeof dlg.showModal !== 'function') return;
    btn.addEventListener('click', function () { dlg.showModal(); });
  });
  Array.prototype.forEach.call(document.querySelectorAll('dialog'), function (dlg) {
    Array.prototype.forEach.call(dlg.querySelectorAll('[data-close-dialog]'), function (b) {
      b.addEventListener('click', function () { dlg.close(); });
    });
    // click on the backdrop closes the dialog
    dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
    // Only reopen by itself after a failed submission, so its errors are visible.
    // Visitors (including old #register links) see the event details first.
    if (typeof dlg.showModal === 'function' && dlg.hasAttribute('data-autoopen')) {
      dlg.showModal();
    }
    if (window.location.hash === '#' + dlg.id && window.history.replaceState) {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  });

  // Share / copy link (product and event pages)
  Array.prototype.forEach.call(document.querySelectorAll('.pdp-share'), function (shareBtn) {
    shareBtn.addEventListener('click', function () {
      var url = window.location.origin + window.location.pathname;
      var title = shareBtn.getAttribute('data-title') || document.title;
      function copied() {
        shareBtn.classList.add('copied');
        var label = shareBtn.querySelector('.pdp-share-label');
        var original = label ? label.textContent : '';
        if (label) { label.textContent = 'Link copied!'; }
        setTimeout(function () {
          shareBtn.classList.remove('copied');
          if (label) { label.textContent = original; }
        }, 2000);
      }
      if (navigator.share) {
        navigator.share({ title: title, url: url }).catch(function () {});
      } else if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(copied).catch(function () {});
      }
    });
  });

  // Mobile menu toggle
  var toggle = document.querySelector('.c-nav-toggle');
  var mobile = document.querySelector('.c-nav-mobile');
  if (toggle && mobile) {
    toggle.addEventListener('click', function () {
      mobile.classList.toggle('open');
    });
    mobile.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () { mobile.classList.remove('open'); });
    });
  }
})();
