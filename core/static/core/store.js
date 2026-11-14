/* =========================================================================
   Shared helpers: browser storage, CSRF, and the shortlist.

   Every storage read and write here is wrapped. In a private window, or with
   site data blocked, localStorage can throw on access rather than return
   null, and an unguarded read would take the whole page down with it.
   ========================================================================= */

const SHORTLIST_KEY = 'maison-shortlist';
const SESSION_KEY = 'maison-session';
const CODES_KEY = 'maison-error-codes';

/** Read a JSON value from localStorage. Returns `fallback` on any problem. */
export function readLocal(key, fallback = null) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch (error) {
    return fallback;
  }
}

/** Write a JSON value to localStorage. Returns whether it was stored. */
export function writeLocal(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch (error) {
    return false;
  }
}

/**
 * A random id for this browser tab, used to group one visitor's messages.
 *
 * sessionStorage, not localStorage: it should end when the tab does. It is
 * not tied to a person and is never used to identify one.
 */
export function sessionId() {
  try {
    let id = window.sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
      window.sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch (error) {
    return 'nostore';
  }
}

/** The CSRF token, from the hidden input Django renders into the form. */
export function csrfToken() {
  const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
  if (input && input.value) return input.value;

  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

// ------------------------------------------------------------- shortlist

/** The tea slugs this visitor has shortlisted on this device. */
export function getShortlist() {
  const value = readLocal(SHORTLIST_KEY, []);
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [];
}

/** Add or remove a slug. Returns true if it is now on the list. */
export function toggleShortlist(slug) {
  const current = getShortlist();
  const index = current.indexOf(slug);
  if (index === -1) {
    current.push(slug);
  } else {
    current.splice(index, 1);
  }
  writeLocal(SHORTLIST_KEY, current.slice(0, 40));
  return index === -1;
}

// ---------------------------------------------------------- error codes

/**
 * Keep a copy of the error code table on the device.
 *
 * This is what lets the assistant explain a code with no connection, which is
 * exactly when a visitor is most likely to be looking at an error.
 */
export function saveErrorCodes(codes) {
  if (Array.isArray(codes) && codes.length) writeLocal(CODES_KEY, codes);
}

export function cachedErrorCodes() {
  const value = readLocal(CODES_KEY, []);
  return Array.isArray(value) ? value : [];
}

/** Fetch the codes and store them. Quiet on failure: this is an optimisation. */
export async function refreshErrorCodes() {
  try {
    const response = await fetch('/api/error-codes/', { headers: { Accept: 'application/json' } });
    if (!response.ok) return cachedErrorCodes();
    const payload = await response.json();
    saveErrorCodes(payload.error_codes || []);
    return payload.error_codes || [];
  } catch (error) {
    return cachedErrorCodes();
  }
}

// ----------------------------------------------------------------- misc

/** Escape text before putting it in innerHTML. */
export function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Whether the browser currently believes it is online. */
export function isOnline() {
  return typeof navigator.onLine === 'boolean' ? navigator.onLine : true;
}
