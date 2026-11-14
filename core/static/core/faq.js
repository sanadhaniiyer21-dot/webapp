/* =========================================================================
   The FAQ page.

   Checklist item 3 asks for the FAQ page to be loaded from the API, so this
   fetches GET /api/faqs/ and rebuilds the list from it. The server-rendered
   copy underneath is the fallback for no JavaScript and for a failed fetch;
   both come from the same SQL table, so they can never disagree.
   ========================================================================= */

import { escapeHtml } from './store.js';

const list = document.querySelector('[data-faq-list]');

if (list) {
  const search = document.querySelector('[data-faq-search]');
  const countLabel = document.querySelector('[data-faq-count]');
  const emptyState = document.querySelector('[data-faq-empty]');
  const errorState = document.querySelector('[data-faq-error]');
  const retryButton = document.querySelector('[data-faq-retry]');
  const index = document.querySelector('[data-faq-index]');

  let faqs = [];
  let category = '';
  let term = '';

  function render() {
    const lowered = term.toLowerCase();

    const matching = faqs.filter((faq) => {
      if (category && faq.category !== category) return false;
      if (!lowered) return true;
      return (
        faq.question.toLowerCase().includes(lowered) ||
        faq.answer.toLowerCase().includes(lowered)
      );
    });

    list.innerHTML = matching
      .map(
        (faq) => `
      <li data-faq-item data-category="${escapeHtml(faq.category)}">
        <h2>
          <button type="button" class="accordion__button" aria-expanded="false"
                  aria-controls="faq-panel-${faq.id}" id="faq-button-${faq.id}">
            <span>${escapeHtml(faq.question)}</span>
            <span class="accordion__sign" aria-hidden="true"></span>
          </button>
        </h2>
        <div class="accordion__panel" id="faq-panel-${faq.id}" role="region"
             aria-labelledby="faq-button-${faq.id}" hidden>
          <p>${escapeHtml(faq.answer)}</p>
          <p class="accordion__cat">${escapeHtml(faq.category)}</p>
        </div>
      </li>`
      )
      .join('');

    if (countLabel) {
      countLabel.textContent =
        matching.length === 1 ? '1 question' : `${matching.length} questions`;
    }
    if (emptyState) emptyState.hidden = matching.length > 0;
  }

  // One delegated listener, so it keeps working after every re-render.
  list.addEventListener('click', (event) => {
    const button = event.target.closest('.accordion__button');
    if (!button) return;
    const panel = document.getElementById(button.getAttribute('aria-controls'));
    if (!panel) return;
    const open = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!open));
    panel.hidden = open;
  });

  if (search) {
    let timer = null;
    search.addEventListener('input', () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        term = search.value.trim();
        render();
      }, 180);
    });
  }

  if (index) {
    index.addEventListener('click', (event) => {
      const button = event.target.closest('[data-faq-cat]');
      if (!button) return;
      category = button.getAttribute('data-faq-cat') || '';
      index.querySelectorAll('[data-faq-cat]').forEach((other) => {
        other.setAttribute(
          'aria-pressed',
          String((other.getAttribute('data-faq-cat') || '') === category)
        );
      });
      render();
    });
  }

  async function load() {
    if (errorState) errorState.hidden = true;
    try {
      const response = await fetch('/api/faqs/', { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      faqs = payload.faqs || [];
      render();
    } catch (error) {
      // Leave the server-rendered list in place: it is correct, just not live.
      if (errorState) errorState.hidden = false;
    }
  }

  if (retryButton) retryButton.addEventListener('click', load);

  load();
}
