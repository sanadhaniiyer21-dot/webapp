/* =========================================================================
   Site behaviour: navigation, theme, reveals, the offline strip, the service
   worker registration, the newsletter form and the shortlist buttons.

   The assistant lives in chat.js. Page-specific behaviour lives in teas.js,
   faq.js and brew.js.
   ========================================================================= */

import { csrfToken, getShortlist, isOnline, toggleShortlist } from './store.js';

document.documentElement.classList.add('js');

// ------------------------------------------------------------ navigation

const menuToggle = document.querySelector('.menu-toggle');
const siteNav = document.getElementById('site-nav');

if (menuToggle && siteNav) {
  menuToggle.addEventListener('click', () => {
    const open = menuToggle.getAttribute('aria-expanded') === 'true';
    menuToggle.setAttribute('aria-expanded', String(!open));
    siteNav.setAttribute('data-open', String(!open));
    document.body.style.overflow = !open ? 'hidden' : '';
  });

  // Escape closes the overlay and puts focus back on the button.
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (menuToggle.getAttribute('aria-expanded') !== 'true') return;
    menuToggle.setAttribute('aria-expanded', 'false');
    siteNav.setAttribute('data-open', 'false');
    document.body.style.overflow = '';
    menuToggle.focus();
  });
}

// ----------------------------------------------------------------- theme

const themeToggle = document.querySelector('.theme-toggle');

if (themeToggle) {
  themeToggle.addEventListener('click', () => {
    const root = document.documentElement;
    const explicit = root.getAttribute('data-theme');
    const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const currentlyDark = explicit ? explicit === 'dark' : systemDark;
    const next = currentlyDark ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    // Stored as a raw string, not JSON: the inline script in base.html reads
    // it before this module loads and compares it directly.
    try {
      window.localStorage.setItem('maison-theme', next);
    } catch (error) { /* private mode: the choice lasts for this page only */ }
  });
}

// --------------------------------------------------------------- reveals

const revealTargets = document.querySelectorAll('.reveal');

if (revealTargets.length) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (reduced || !('IntersectionObserver' in window)) {
    revealTargets.forEach((element) => element.setAttribute('data-revealed', 'true'));
  } else {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.setAttribute('data-revealed', 'true');
          observer.unobserve(entry.target);
        });
      },
      { rootMargin: '0px 0px -12% 0px', threshold: 0.05 }
    );
    revealTargets.forEach((element) => observer.observe(element));
  }
}

// --------------------------------------------------------- offline strip

const offlineStrip = document.getElementById('offline-strip');

function updateOfflineStrip() {
  if (!offlineStrip) return;
  offlineStrip.hidden = isOnline();
}

window.addEventListener('online', updateOfflineStrip);
window.addEventListener('offline', updateOfflineStrip);
updateOfflineStrip();

// The offline page's Try again button.
document.querySelectorAll('[data-reload]').forEach((button) => {
  button.addEventListener('click', () => window.location.reload());
});

// ------------------------------------------------------- service worker

/*
 * Registered only in a secure context. A service worker will not install over
 * plain http except on localhost, so this quietly does nothing in a setup
 * where it cannot work rather than throwing in the console.
 */
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {
      /* Offline support is an enhancement. The site works without it. */
    });
  });
}

// ------------------------------------------------------------- shortlist

function paintShortlistButtons() {
  const saved = getShortlist();
  document.querySelectorAll('[data-shortlist]').forEach((button) => {
    const slug = button.getAttribute('data-shortlist');
    const on = saved.includes(slug);
    button.setAttribute('aria-pressed', String(on));
    button.textContent = on ? 'On your shortlist' : 'Add to my shortlist';
  });

  const summary = document.querySelector('[data-shortlist-summary]');
  if (summary) {
    if (saved.length) {
      summary.hidden = false;
      summary.textContent =
        saved.length === 1
          ? '1 tea on your shortlist. The assistant will take it into account.'
          : `${saved.length} teas on your shortlist. The assistant will take them into account.`;
    } else {
      summary.hidden = true;
    }
  }
}

document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-shortlist]');
  if (!button) return;
  event.preventDefault();
  toggleShortlist(button.getAttribute('data-shortlist'));
  paintShortlistButtons();
});

paintShortlistButtons();
// teas.js re-renders the grid, so let it ask for a repaint.
document.addEventListener('maison:grid-updated', paintShortlistButtons);

// ------------------------------------------------------------ newsletter

const subscribeForm = document.querySelector('[data-subscribe-form]');

if (subscribeForm) {
  const status = subscribeForm.querySelector('[data-subscribe-status]');
  const submit = subscribeForm.querySelector('button[type="submit"]');

  function say(message, state) {
    if (!status) return;
    status.textContent = message;
    status.setAttribute('data-state', state);
  }

  subscribeForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(subscribeForm);

    const payload = {
      first_name: (data.get('first_name') || '').toString().trim(),
      email: (data.get('email') || '').toString().trim(),
      consent: data.get('consent') === 'yes'
    };

    if (!payload.first_name || !payload.email) {
      say('Please give a first name and an email address.', 'error');
      return;
    }
    if (!payload.consent) {
      say('Please tick the consent box so we know you want the letter.', 'error');
      return;
    }

    submit.disabled = true;
    say('Sending.', 'busy');

    try {
      // CSRF protected, not exempt: this form sits on a normal page, so it can
      // carry a token, and it should.
      const response = await fetch('/api/subscribe/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken()
        },
        body: JSON.stringify(payload)
      });
      const body = await response.json().catch(() => ({}));

      if (response.status === 201) {
        subscribeForm.reset();
        say('Thank you. The next letter goes out at the start of the month.', 'ok');
      } else if (response.status === 409) {
        say('That address is already on the list, so there is nothing to do.', 'ok');
      } else {
        say(body.error || 'That did not go through. Please try again.', 'error');
      }
    } catch (error) {
      say('No connection just now. Please try again in a moment.', 'error');
    } finally {
      submit.disabled = false;
    }
  });
}
