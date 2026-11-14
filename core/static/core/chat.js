/* =========================================================================
   The tea sommelier widget.

   Runs on every page, including the 404, 500, generic error and offline
   pages, which do not extend base.html. So it must assume nothing about the
   page around it beyond the markup in core/templates/core/_assistant.html.

   Offline behaviour is the interesting part. When the network fails:

     * a question containing an error code is answered from the copy of
       /api/error-codes/ kept in localStorage, clearly marked as offline
     * anything else gets a plain explanation and a Try again button that
       resends the last message once the connection is back

   That is what keeps the error pages useful during the outage that produced
   them.
   ========================================================================= */

import {
  cachedErrorCodes,
  escapeHtml,
  getShortlist,
  isOnline,
  refreshErrorCodes,
  sessionId
} from './store.js';

const panel = document.querySelector('[data-assistant-panel]');
const launch = document.querySelector('[data-assistant-launch]');

// Not every page necessarily has the widget (a bare template under test, say).
if (panel && launch) {
  setUpAssistant();
}

function setUpAssistant() {
  const scrim = document.querySelector('[data-assistant-scrim]');
  const closeButton = panel.querySelector('[data-assistant-close]');
  const log = panel.querySelector('[data-assistant-log]');
  const form = panel.querySelector('[data-assistant-form]');
  const input = panel.querySelector('[data-assistant-input]');
  const sendButton = panel.querySelector('[data-assistant-send]');
  const counter = panel.querySelector('[data-assistant-count]');
  const chips = panel.querySelector('[data-assistant-chips]');
  const emailBlock = panel.querySelector('[data-assistant-email]');
  const emailInput = panel.querySelector('[data-assistant-email-input]');
  const emailToggle = panel.querySelector('[data-assistant-email-toggle]');

  const MAX = 500;
  let lastFocused = null;
  let busy = false;
  let lastMessage = '';
  let codesLoaded = false;

  // ------------------------------------------------------------- opening

  function open(prefill) {
    lastFocused = document.activeElement;
    panel.hidden = false;
    if (scrim) scrim.hidden = false;
    launch.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = window.innerWidth < 768 ? 'hidden' : '';

    // Refresh the saved error codes whenever the panel opens and we are
    // online, so the offline answers stay current.
    if (!codesLoaded) {
      codesLoaded = true;
      if (isOnline()) {
        refreshErrorCodes();
      }
    }

    if (prefill) {
      input.value = prefill.slice(0, MAX);
      updateCounter();
    }
    window.setTimeout(() => input.focus(), 30);
  }

  function close() {
    panel.hidden = true;
    if (scrim) scrim.hidden = true;
    launch.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
    // Focus goes back where it came from, not to the top of the page.
    if (lastFocused && typeof lastFocused.focus === 'function') {
      lastFocused.focus();
    } else {
      launch.focus();
    }
  }

  launch.addEventListener('click', () => (panel.hidden ? open() : close()));
  if (closeButton) closeButton.addEventListener('click', close);
  if (scrim) scrim.addEventListener('click', close);

  /*
   * Any element on any page can open the assistant, optionally with the
   * question already typed. This is what the "Ask the assistant about this
   * error" buttons on the error pages use: they prefill and send in one go.
   */
  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-open-assistant]');
    if (!trigger) return;
    event.preventDefault();
    const prompt = trigger.getAttribute('data-prompt') || '';
    open(prompt);
    if (prompt) {
      window.setTimeout(() => send(prompt), 120);
    }
  });

  // ------------------------------------------------------ keyboard access

  document.addEventListener('keydown', (event) => {
    if (panel.hidden) return;

    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }

    if (event.key !== 'Tab') return;

    // Focus trap: while the panel is open, Tab stays inside it.
    const focusable = panel.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled])'
    );
    const visible = Array.from(focusable).filter(
      (element) => element.offsetParent !== null || element === document.activeElement
    );
    if (!visible.length) return;

    const first = visible[0];
    const last = visible[visible.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  // ----------------------------------------------------------- the input

  function updateCounter() {
    if (counter) counter.textContent = `${input.value.length} / ${MAX}`;
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 128)}px`;
  }

  input.addEventListener('input', updateCounter);

  // Enter sends. Shift and Enter makes a new line.
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    send(input.value);
  });

  if (chips) {
    chips.addEventListener('click', (event) => {
      const chip = event.target.closest('[data-prompt]');
      if (!chip) return;
      send(chip.getAttribute('data-prompt'));
    });
  }

  if (emailToggle && emailBlock) {
    emailToggle.addEventListener('click', () => {
      emailBlock.hidden = !emailBlock.hidden;
      if (!emailBlock.hidden && emailInput) emailInput.focus();
      emailToggle.textContent = emailBlock.hidden
        ? 'Add an email for a reply'
        : 'Hide the email field';
    });
  }

  // ---------------------------------------------------------- rendering

  function addBubble(role, html, options = {}) {
    const bubble = document.createElement('div');
    bubble.className = `bubble bubble--${role}`;
    if (options.error) bubble.classList.add('bubble--error');
    bubble.innerHTML = html;
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
    return bubble;
  }

  /** Turn the assistant's plain text into paragraphs, escaped. */
  function asParagraphs(text) {
    return String(text)
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => `<p>${escapeHtml(line)}</p>`)
      .join('');
  }

  function showTyping() {
    return addBubble(
      'assistant',
      '<span class="typing" role="status" aria-label="The assistant is thinking">' +
        '<i></i><i></i><i></i></span>'
    );
  }

  /** The thumbs up and down row, and the source label. */
  function addMeta(bubble, payload) {
    const meta = document.createElement('div');
    meta.className = 'bubble__meta';

    const source = document.createElement('span');
    source.className = 'bubble__source';
    source.textContent = sourceLabel(payload.source);
    meta.appendChild(source);

    if (payload.message_id) {
      const vote = document.createElement('span');
      vote.className = 'vote';
      vote.appendChild(voteButton('up', payload.message_id, vote));
      vote.appendChild(voteButton('down', payload.message_id, vote));
      meta.appendChild(vote);
    }

    bubble.appendChild(meta);
  }

  function sourceLabel(source) {
    const labels = {
      faq: 'From the FAQ',
      error_code: 'From the error code table',
      catalog: 'From the catalogue',
      ticket: 'Ticket opened',
      llm: 'From the FAQ, reworded',
      fallback: 'Saved answer',
      offline: 'Saved on this device'
    };
    return labels[source] || 'Answer';
  }

  function voteButton(value, messageId, group) {
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-pressed', 'false');
    button.setAttribute(
      'aria-label',
      value === 'up' ? 'This answer helped' : 'This answer did not help'
    );
    button.innerHTML =
      value === 'up'
        ? '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M7 21V9l5-7 1 1-1.5 5H20l-2 11H7Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>'
        : '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M17 3v12l-5 7-1-1 1.5-5H4L6 3h11Z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>';

    button.addEventListener('click', async () => {
      group.querySelectorAll('button').forEach((other) =>
        other.setAttribute('aria-pressed', 'false')
      );
      button.setAttribute('aria-pressed', 'true');
      try {
        await fetch('/api/feedback/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message_id: messageId,
            session_id: sessionId(),
            value,
            page: window.location.pathname
          })
        });
      } catch (error) {
        /* Feedback is optional. Never interrupt the visitor over it. */
      }
    });

    return button;
  }

  function addTeaLinks(bubble, teas) {
    if (!Array.isArray(teas) || !teas.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'bubble__teas';
    teas.forEach((tea) => {
      if (!tea || !tea.url) return;
      const link = document.createElement('a');
      link.href = tea.url;
      link.textContent = tea.name || tea.slug;
      wrap.appendChild(link);
    });
    bubble.appendChild(wrap);
  }

  /** A Try again button that resends whatever failed. */
  function addRetry(bubble, message) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'button button--quiet button--small';
    button.style.marginTop = '0.75rem';
    button.textContent = 'Try again';
    button.addEventListener('click', () => {
      button.disabled = true;
      send(message);
    });
    bubble.appendChild(button);
  }

  // -------------------------------------------------- offline answering

  const CODE_PATTERN = /(?:^|[^\w-])(SITE-\d{4}|[1-5]\d{2})(?![\w-])/i;

  /**
   * Answer from the device when the network is gone.
   *
   * Returns HTML, or null if this question cannot be answered offline, in
   * which case the caller shows the Try again message instead.
   */
  function answerOffline(message) {
    const codes = cachedErrorCodes();
    if (!codes.length) return null;

    const match = CODE_PATTERN.exec(message);
    if (match) {
      const wanted = match[1].toUpperCase();
      const row = codes.find((item) => String(item.code).toUpperCase() === wanted);
      if (row) {
        return (
          `<p>${escapeHtml(row.code)}, ${escapeHtml(row.title)}. ` +
          `${escapeHtml(row.meaning)}</p>` +
          `<p>What to do: ${escapeHtml(row.fix)}</p>` +
          '<p class="small muted">You are offline, so that is from the copy of ' +
          'the error code table saved on this device.</p>'
        );
      }
    }

    if (/error code/i.test(message)) {
      const listed = codes.map((item) => `${item.code} ${item.title}`).join(', ');
      return (
        `<p>These are the codes this site can show: ${escapeHtml(listed)}.</p>` +
        '<p class="small muted">From the copy saved on this device, because you ' +
        'are offline.</p>'
      );
    }

    return null;
  }

  // -------------------------------------------------------------- sending

  async function send(rawMessage) {
    const message = String(rawMessage || '').trim();

    if (busy) return;
    if (!message) {
      input.focus();
      return;
    }
    if (message.length > MAX) {
      addBubble(
        'assistant',
        `<p>That is a little long for me. Please keep it under ${MAX} characters.</p>`,
        { error: true }
      );
      return;
    }

    busy = true;
    lastMessage = message;
    sendButton.disabled = true;
    input.value = '';
    updateCounter();

    addBubble('user', `<p>${escapeHtml(message)}</p>`);
    const thinking = showTyping();

    // Not online: answer from the device if we can, otherwise say so plainly.
    if (!isOnline()) {
      thinking.remove();
      const offlineAnswer = answerOffline(message);
      if (offlineAnswer) {
        const bubble = addBubble('assistant', offlineAnswer);
        addMeta(bubble, { source: 'offline' });
      } else {
        const bubble = addBubble(
          'assistant',
          '<p>You are offline, so I cannot look this up. I can still explain any ' +
            'error code. Everything else needs a connection.</p>',
          { error: true }
        );
        addRetry(bubble, message);
      }
      busy = false;
      sendButton.disabled = false;
      input.focus();
      return;
    }

    try {
      const response = await fetch('/api/chat/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          email: emailInput ? emailInput.value.trim() : '',
          page: window.location.pathname,
          session_id: sessionId(),
          shortlist: getShortlist()
        })
      });

      thinking.remove();
      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        // A 400 is the visitor's input. A 429 is the rate limit. Anything else
        // is ours. All three are explained rather than shown as a status code.
        const text =
          payload.error ||
          'Something went wrong at our end. Please try that again in a moment.';
        const bubble = addBubble('assistant', `<p>${escapeHtml(text)}</p>`, { error: true });
        if (response.status >= 500 || response.status === 429) {
          addRetry(bubble, message);
        }
        return;
      }

      const bubble = addBubble('assistant', asParagraphs(payload.reply || ''));
      addTeaLinks(bubble, payload.teas);
      addMeta(bubble, payload);

      // If a ticket was opened and no email was given, nudge the field open.
      if (payload.ticket_id && emailBlock && emailBlock.hidden && !(emailInput && emailInput.value)) {
        emailBlock.hidden = false;
        if (emailToggle) emailToggle.textContent = 'Hide the email field';
      }
    } catch (error) {
      // The request itself failed: the server is unreachable, or the
      // connection dropped between the check above and now.
      thinking.remove();
      const offlineAnswer = answerOffline(message);
      if (offlineAnswer) {
        const bubble = addBubble('assistant', offlineAnswer);
        addMeta(bubble, { source: 'offline' });
      } else {
        const bubble = addBubble(
          'assistant',
          '<p>I could not reach the shop just now. That is usually the connection, ' +
            'or the server restarting.</p>',
          { error: true }
        );
        addRetry(bubble, message);
      }
    } finally {
      busy = false;
      sendButton.disabled = false;
      input.focus();
    }
  }

  // Keep the saved codes fresh when a connection comes back.
  window.addEventListener('online', () => {
    refreshErrorCodes();
  });

  updateCounter();
}
