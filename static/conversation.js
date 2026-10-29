/* Text-only chat and response-scoped ratings. */
function initConversation(document, fetch, notify) {
  const chat = document.getElementById('chat');
  const input = document.getElementById('composerInput');
  const send = document.querySelector('.send');
  const stars = Array.from(document.querySelectorAll('.star'));
  const note = document.getElementById('feedbackNote');
  const dimension = document.getElementById('feedbackDimension');
  const target = document.getElementById('feedbackTarget');
  let selected = null, saving = false, sending = false, ready = false;
  const request = async (url, options) => {
    const response = await fetch(url, options);
    if (!response.ok) throw Error('Request failed');
    const data = await response.json();
    if (data?.ok !== true) throw Error('Request not acknowledged');
    return data;
  };
  const post = body => ({method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  function refresh() {
    const rating = selected?.ratings[dimension.value];
    stars.forEach(button => {
      const active = rating !== undefined && Number(button.getAttribute('data-score')) === rating.score;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
      button.disabled = !selected || saving;
    });
    note.disabled = dimension.disabled = !selected || saving;
    target.textContent = selected ? 'Rating reply: ' + selected.reply.slice(0, 90) : 'Send a message, then select a reply to rate.';
  }
  function select(turn) {
    if (saving) return;
    selected = turn;
    note.value = turn.ratings[dimension.value]?.note ?? '';
    refresh();
  }
  function addTurn(turn) {
    for (const [label, text] of [['You', turn.message], ['Assistant', turn.reply]]) {
      const box = document.createElement('div');
      box.className = label === 'You' ? 'msg you' : 'msg';
      const heading = document.createElement('b'); heading.textContent = label;
      const content = document.createElement('p'); content.textContent = text;
      box.appendChild(heading); box.appendChild(content);
      if (label === 'Assistant') {
        const choose = document.createElement('button');
        choose.className = 'action'; choose.textContent = 'Rate this reply';
        choose.addEventListener('click', () => select(turn)); box.appendChild(choose);
      }
      chat.appendChild(box);
    }
    chat.scrollTop = chat.scrollHeight;
  }
  dimension.addEventListener('change', () => {
    note.value = selected?.ratings[dimension.value]?.note ?? '';
    refresh();
  });
  stars.forEach(button => button.addEventListener('click', async () => {
    const score = Number(button.getAttribute('data-score'));
    if (!selected || saving || button.disabled || !Number.isInteger(score) || Math.abs(score) > 5) return;
    const turn = selected, key = dimension.value, text = note.value.trim();
    saving = true; refresh();
    try {
      await request('/api/conversation/feedback', post({response_id: turn.response_id, dimension: key, score, note: text}));
      turn.ratings[key] = {score, note: text};
      notify('Saved ' + key + ' rating ' + score);
    } catch (_) { notify('Failed to save feedback. Please try again.'); }
    finally { saving = false; refresh(); }
  }));
  async function submit() {
    if (!ready || sending || !input.value.trim()) return;
    const message = input.value.trim();
    sending = true; send.disabled = true; input.disabled = true;
    try {
      const data = await request('/api/conversation', post({message}));
      if (typeof data.response_id !== 'string' || typeof data.reply !== 'string') throw Error('Invalid reply');
      const turn = {response_id: data.response_id, message, reply: data.reply, ratings: {}};
      addTurn(turn); select(turn); input.value = '';
    } catch (_) { notify('Could not send message. Your text is kept; please retry.'); }
    finally { sending = false; send.disabled = false; input.disabled = false; }
  }
  send.addEventListener('click', submit);
  input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); submit(); } });
  // History must load before sending so a slow restore cannot overwrite new replies.
  send.disabled = true; refresh();
  const loaded = request('/api/conversation').then(data => {
    if (!Array.isArray(data.turns)) throw Error('Invalid history');
    data.turns.forEach(addTurn);
    if (data.turns.length) select(data.turns[data.turns.length - 1]);
    ready = true; send.disabled = false;
  }).catch(() => {
    target.textContent = 'Could not load conversation. Reload this page to retry.';
    notify('Could not load conversation. Reload this page to retry.');
  });
  return {loaded};
}
if (typeof module !== 'undefined') module.exports = {initConversation};
else initConversation(document, window.fetch.bind(window), toast);
