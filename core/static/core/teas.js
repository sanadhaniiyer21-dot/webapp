/* =========================================================================
   The catalogue filters.

   The grid is rendered on the server first, so the page works with no
   JavaScript and with a bookmarked filter URL. This script takes over once
   it loads and re-renders from GET /api/teas/, which keeps filtering
   instant and gives the skeleton, empty and error states somewhere to live.
   ========================================================================= */

import { escapeHtml } from './store.js';

const form = document.querySelector('[data-filters]');
const grid = document.querySelector('[data-tea-grid]');

if (form && grid) {
  const skeleton = document.querySelector('[data-tea-skeleton]');
  const emptyState = document.querySelector('[data-tea-empty]');
  const errorState = document.querySelector('[data-tea-error]');
  const countLabel = document.querySelector('[data-tea-count]');
  const retryButton = document.querySelector('[data-tea-retry]');
  const search = form.querySelector('#filter-q');
  const toggle = form.querySelector('[data-filters-toggle]');

  const state = {
    category: readParam('category'),
    caffeine: readParam('caffeine'),
    mood: readParam('mood'),
    q: readParam('q')
  };

  let inFlight = null;

  function readParam(name) {
    return new URLSearchParams(window.location.search).get(name) || '';
  }

  // The filter rail collapses on small screens.
  if (toggle) {
    toggle.addEventListener('click', () => {
      const open = form.getAttribute('data-open') === 'true';
      form.setAttribute('data-open', String(!open));
      toggle.setAttribute('aria-expanded', String(!open));
    });
  }

  // Pills.
  form.addEventListener('click', (event) => {
    const pill = event.target.closest('[data-filter]');
    if (!pill) return;
    event.preventDefault();

    const key = pill.getAttribute('data-filter');
    state[key] = pill.getAttribute('data-value') || '';

    form.querySelectorAll(`[data-filter="${key}"]`).forEach((other) => {
      other.setAttribute(
        'aria-pressed',
        String((other.getAttribute('data-value') || '') === state[key])
      );
    });

    load();
  });

  // Search, settled so it does not fire on every keystroke.
  if (search) {
    let timer = null;
    search.addEventListener('input', () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        state.q = search.value.trim();
        load();
      }, 260);
    });
  }

  // The form still submits normally if this script fails to load.
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (search) state.q = search.value.trim();
    load();
  });

  if (retryButton) retryButton.addEventListener('click', load);

  function queryString() {
    const params = new URLSearchParams();
    Object.entries(state).forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    return params.toString();
  }

  function setBusy(busy) {
    if (skeleton) {
      skeleton.hidden = !busy;
      skeleton.setAttribute('data-busy', String(busy));
    }
    grid.style.opacity = busy ? '0.35' : '';
  }

  function teaCard(tea) {
    const notes = (tea.flavour_notes || []).join(', ');
    const stockLine = tea.in_stock
      ? `<span class="small muted num">${escapeHtml(String(tea.brew_temp_c))} C</span>`
      : '<span class="tea-card__out">Out of stock</span>';

    return `
      <article class="tea-card-wrap">
        <a class="tea-card" href="${escapeHtml(tea.url)}">
          <div class="tea-card__art">
            <img src="${escapeHtml(imageFor(tea.slug))}" width="400" height="500"
                 loading="lazy" alt="${escapeHtml(tea.name)}, illustrated.">
          </div>
          <div class="tea-card__body">
            <h3 class="tea-card__name">${escapeHtml(tea.name)}</h3>
            <p class="tea-card__origin">${escapeHtml(tea.origin)}</p>
            <p class="tea-card__notes">${escapeHtml(notes)}</p>
            <div class="tea-card__foot">
              <span class="tea-card__price num">&#8377;${escapeHtml(String(tea.price_inr_50g))}</span>
              ${stockLine}
            </div>
          </div>
        </a>
        <button type="button" class="shortlist-button" data-shortlist="${escapeHtml(tea.slug)}"
                aria-pressed="false">Add to my shortlist</button>
      </article>`;
  }

  /*
   * Static paths are hashed by WhiteNoise in production, so the path cannot be
   * guessed here. The first server-rendered card carries the real prefix and
   * extension, which this reads once and reuses.
   */
  let imagePattern = null;

  function imageFor(slug) {
    if (imagePattern === null) {
      const sample = grid.querySelector('.tea-card__art img');
      const src = sample ? sample.getAttribute('src') : '';
      const match = src.match(/^(.*\/teas\/)[^/]*?(\.[a-z0-9]+)$/i);
      imagePattern = match ? { prefix: match[1], extension: match[2] } : false;
    }
    if (!imagePattern) return '';
    return imagePattern.prefix + slug + imagePattern.extension;
  }

  async function load() {
    const query = queryString();
    window.history.replaceState({}, '', query ? `/teas/?${query}` : '/teas/');

    if (inFlight) inFlight.abort();
    const controller = new AbortController();
    inFlight = controller;

    setBusy(true);
    if (errorState) errorState.hidden = true;

    try {
      const response = await fetch(`/api/teas/?${query}`, {
        headers: { Accept: 'application/json' },
        signal: controller.signal
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || `HTTP ${response.status}`);
      }

      const payload = await response.json();
      const teas = payload.teas || [];

      grid.innerHTML = teas.map(teaCard).join('');

      if (countLabel) {
        countLabel.textContent = `${payload.count} tea${payload.count === 1 ? '' : 's'}`;
      }
      if (emptyState) emptyState.hidden = teas.length > 0;

      // site.js owns the shortlist buttons, so tell it the grid changed.
      document.dispatchEvent(new CustomEvent('maison:grid-updated'));
    } catch (error) {
      if (error.name === 'AbortError') return;
      // The grid keeps whatever it last showed, which is still accurate.
      if (errorState) errorState.hidden = false;
      if (emptyState) emptyState.hidden = true;
    } finally {
      if (inFlight === controller) inFlight = null;
      setBusy(false);
    }
  }
}
