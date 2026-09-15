/* global document */
const controls = [...document.querySelectorAll('[data-scene]')];
const panels = [...document.querySelectorAll('[data-scene-panel]')];
function show(scene) {
  controls.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.scene === scene)));
  panels.forEach(panel => { panel.hidden = panel.dataset.scenePanel !== scene; });
}
controls.forEach(button => button.addEventListener('click', () => show(button.dataset.scene)));
document.querySelector('#participant-demo').addEventListener('submit', event => {
  event.preventDefault(); show('listen'); controls.find(button => button.dataset.scene === 'listen').focus();
});
let questionState = 'queued';
const label = document.querySelector('#question-state');
const feedback = document.querySelector('#question-feedback');
const discard = document.querySelector('#discard-demo');
const asked = document.querySelector('#asked-demo');
discard.addEventListener('click', () => {
  const restore = questionState === 'discarded'; questionState = restore ? 'queued' : 'discarded';
  label.textContent = restore ? 'Suggested follow-up' : 'Discarded';
  discard.textContent = restore ? 'Discard' : 'Restore'; asked.disabled = !restore;
  asked.textContent = 'Mark asked'; feedback.textContent = 'Preview only · No meeting data changed.';
});
asked.addEventListener('click', () => {
  questionState = questionState === 'queued' ? 'asked' : questionState === 'asked' ? 'answered' : 'queued';
  label.textContent = questionState === 'queued' ? 'Suggested follow-up' : questionState === 'asked' ? 'Asked' : 'Answered';
  asked.textContent = questionState === 'queued' ? 'Mark asked' : questionState === 'asked' ? 'Mark answered' : 'Reopen';
  feedback.textContent = 'Preview only · Question status is your decision.';
});
const dialog = document.querySelector('#source-dialog');
let trigger;
document.querySelectorAll('[data-evidence]').forEach(button => button.addEventListener('click', () => {
  trigger = button; dialog.showModal();
}));
document.querySelector('#close-source').addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => trigger?.focus());

const search = document.querySelector('#tour-search');
search.addEventListener('input', () => {
  const meeting = document.querySelector('[data-meeting]');
  const matches = meeting.dataset.meeting.toLowerCase().includes(search.value.trim().toLowerCase());
  meeting.hidden = !matches;
  document.querySelector('#tour-search-empty').hidden = matches;
});
document.querySelector('[data-meeting]').addEventListener('click', () => { show('listen'); controls.find(button => button.dataset.scene === 'listen').focus(); });
