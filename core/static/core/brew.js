/* =========================================================================
   The brew timer.

   Every figure comes from data attributes the server wrote from the Tea row,
   so the timer and the tea page can never disagree. No network calls at all,
   which is why it keeps working offline.
   ========================================================================= */

const select = document.querySelector('[data-brew-select]');
const ring = document.querySelector('[data-brew-ring]');

if (select && ring) {
  const progress = document.querySelector('[data-brew-progress]');
  const readout = document.querySelector('[data-brew-readout]');
  const phase = document.querySelector('[data-brew-phase]');
  const summary = document.querySelector('[data-brew-summary]');
  const startButton = document.querySelector('[data-brew-start]');
  const resetButton = document.querySelector('[data-brew-reset]');
  const nextButton = document.querySelector('[data-brew-next]');
  const soundToggle = document.querySelector('[data-brew-sound]');

  // 2 * pi * r, with r = 88 from the SVG.
  const CIRCUMFERENCE = 552.9;

  let total = 180;
  let remaining = 180;
  let steep = 0;       // 0 is the first steep
  let resteeps = 0;
  let ticker = null;

  function currentOption() {
    return select.options[select.selectedIndex];
  }

  function readTea() {
    const option = currentOption();
    if (!option) return;

    const base = parseInt(option.getAttribute('data-seconds'), 10) || 180;
    resteeps = parseInt(option.getAttribute('data-resteeps'), 10) || 0;

    // Each later steep gets 30 seconds more than the one before it.
    total = base + steep * 30;
    remaining = total;

    if (summary) {
      summary.textContent =
        `${option.getAttribute('data-grams')} g per 200 ml, ` +
        `water at ${option.getAttribute('data-temp')} C` +
        (resteeps ? `, up to ${resteeps} more steep${resteeps === 1 ? '' : 's'}` : '');
    }
    paint();
  }

  function format(seconds) {
    const minutes = Math.floor(seconds / 60);
    const rest = seconds % 60;
    return `${minutes}:${String(rest).padStart(2, '0')}`;
  }

  function paint() {
    if (readout) readout.textContent = format(Math.max(remaining, 0));
    if (progress) {
      const done = total > 0 ? (total - remaining) / total : 0;
      progress.setAttribute('stroke-dashoffset', String(CIRCUMFERENCE * done));
    }
    if (phase) {
      phase.textContent = steep === 0 ? 'First steep' : `Steep ${steep + 1}`;
    }
    if (nextButton) {
      nextButton.hidden = !(remaining === 0 && steep < resteeps);
    }
  }

  /** A short tone, drawn rather than loaded. Off unless the visitor asks. */
  function chime() {
    if (!soundToggle || !soundToggle.checked) return;
    try {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) return;
      const context = new Context();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = 'sine';
      oscillator.frequency.value = 528;
      gain.gain.setValueAtTime(0.0001, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.18, context.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 1.1);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start();
      oscillator.stop(context.currentTime + 1.2);
    } catch (error) {
      /* Sound is optional and never worth an error. */
    }
  }

  function stop() {
    if (ticker) {
      window.clearInterval(ticker);
      ticker = null;
    }
    if (startButton) startButton.textContent = 'Start';
  }

  function start() {
    if (ticker) {
      stop();
      return;
    }
    if (remaining <= 0) readTea();

    if (startButton) startButton.textContent = 'Pause';

    ticker = window.setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        remaining = 0;
        stop();
        paint();
        chime();
        if (phase) {
          phase.textContent =
            steep < resteeps ? 'Time is up. Pour it out.' : 'Time is up. That is the last steep.';
        }
        return;
      }
      paint();
    }, 1000);
  }

  function reset() {
    stop();
    steep = 0;
    readTea();
  }

  function nextSteep() {
    if (steep >= resteeps) return;
    stop();
    steep += 1;
    readTea();
    start();
  }

  select.addEventListener('change', reset);
  if (startButton) startButton.addEventListener('click', start);
  if (resetButton) resetButton.addEventListener('click', reset);
  if (nextButton) nextButton.addEventListener('click', nextSteep);

  // A tea can be preselected from a tea page: /brew/?tea=<slug>
  const wanted = new URLSearchParams(window.location.search).get('tea');
  if (wanted) {
    const option = Array.from(select.options).find((item) => item.value === wanted);
    if (option) select.value = wanted;
  }

  readTea();
}
