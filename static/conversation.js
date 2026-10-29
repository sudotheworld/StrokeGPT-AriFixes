/* Text-only chat and response-scoped ratings. */
function initConversation(document, fetch, notify, environment = {}) {
  const chat = document.getElementById('chat');
  const input = document.getElementById('composerInput');
  const send = document.querySelector('.send');
  const stars = Array.from(document.querySelectorAll('.star'));
  const note = document.getElementById('feedbackNote');
  const dimension = document.getElementById('feedbackDimension');
  const target = document.getElementById('feedbackTarget');
  const summary = document.getElementById('ratingSummary');
  const unrate = document.getElementById('removeRating');
  const recall = document.getElementById('preferenceRecall');
  const exportButton = document.getElementById('exportConversation');
  const clear = document.getElementById('clearConversation');
  const autoStart = document.getElementById('autoStart');
  const autoStop = document.getElementById('autoStop');
  const autoLimit = document.getElementById('autoLimit');
  const autoTopic = document.getElementById('autoTopic');
  const autoStatus = document.getElementById('autoStatus');
  let autoRunning = false, autoCount = 0, autoBudget = 0, autoSpeaker = 'A', autoWake;
  const humanQueue = [];
  const draftKey = 'conversation.textDraft.v1';
  const storage = environment.storage;
  function storeDraft(value) {
    const draft = [...humanQueue, value].filter(Boolean).join('\n');
    try { if (draft) storage?.setItem(draftKey, draft); else storage?.removeItem(draftKey); } catch (_) {}
  }
  try { input.value = storage?.getItem(draftKey) ?? ''; } catch (_) {}
  input.addEventListener('input', () => storeDraft(input.value));
  let selected = null, saving = false, sending = false, working = false, ready = false;
  const busy = () => saving || sending || working;
  const request = async (url, options = {}) => {
    const controller = new AbortController();
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => { controller.abort(); reject(Error('Request timed out')); },
        environment.timeoutMs ?? (url === '/api/conversation' && options.method === 'POST' ? 200000 : 15000));
    });
    try {
      return await Promise.race([timeout, (async () => {
        const response = await fetch(url, {...options, signal: controller.signal});
        if (!response.ok) throw Error('Request failed');
        const data = await response.json();
        if (data?.ok !== true) throw Error('Request not acknowledged');
        return data;
      })()]);
    } finally { clearTimeout(timer); }
  };
  const post = (body, method = 'POST') => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const meanings = ['Strongly dislike', 'Dislike a lot', 'Dislike', 'Somewhat dislike', 'Slightly dislike',
    'Neutral', 'Slightly like', 'Somewhat like', 'Like', 'Like a lot', 'Strongly like'];
  stars.forEach(button => {
    const score = Number(button.getAttribute('data-score'));
    const label = (score > 0 ? '+' : '') + score + ': ' + meanings[score + 5];
    button.setAttribute('aria-label', label); button.setAttribute('title', label);
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || button.disabled) return;
      event.preventDefault();
      const index = stars.indexOf(button);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? stars.length - 1 :
        (index + (event.key === 'ArrowRight' ? 1 : -1) + stars.length) % stars.length;
      stars[next].focus(); // Navigation does not submit a rating; Enter/Space activate native buttons.
    });
  });
  function refresh() {
    const rating = selected?.ratings[dimension.value];
    stars.forEach(button => {
      const active = rating !== undefined && Number(button.getAttribute('data-score')) === rating.score;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
      button.disabled = !selected || busy() || autoRunning;
    });
    note.disabled = dimension.disabled = !selected || busy() || autoRunning;
    if (unrate) unrate.disabled = rating === undefined || busy() || autoRunning;
    if (recall) recall.disabled = !ready || busy() || autoRunning;
    if (exportButton) exportButton.disabled = !ready || busy() || autoRunning;
    if (clear) clear.disabled = !ready || busy() || autoRunning;
    send.disabled = !ready || working || saving || (sending && !autoRunning);
    input.disabled = working || saving || (sending && !autoRunning);
    if (autoStart) autoStart.disabled = !ready || busy() || autoRunning;
    if (autoStop) autoStop.disabled = !autoRunning;
    if (autoLimit) autoLimit.disabled = autoRunning || busy();
    if (autoTopic) autoTopic.disabled = autoRunning || busy();
    if (autoStatus) autoStatus.textContent = autoRunning
      ? 'Running: ' + autoCount + (autoBudget === 0 ? ' turns; until stopped' : '/' + autoBudget + ' turns') + '. Queued messages: ' + humanQueue.length
      : 'Paused. Automatic conversation runs only while this page stays open.';
    if (summary) summary.textContent = selected ? Object.entries(selected.ratings)
      .map(([key, value]) => key + ': ' + (value.score > 0 ? '+' : '') + value.score).join(' · ') || 'No aspects rated yet.' : '';
    target.textContent = selected ? 'Rating reply: ' + selected.reply.slice(0, 90) : 'Send a message, then select a reply to rate.';
  }
  function select(turn) {
    if (busy()) return;
    selected = turn; note.value = turn.ratings[dimension.value]?.note ?? ''; refresh();
  }
  function addTurn(turn) {
    const speakerLabel = turn.speaker ? 'Speaker ' + turn.speaker : 'Assistant';
    const promptLabel = turn.automatic ? 'Discussion' : 'You';
    for (const [label, text] of [[promptLabel, turn.message], [speakerLabel, turn.reply]]) {
      const box = document.createElement('div');
      box.className = label === 'You' ? 'msg you' : 'msg';
      const heading = document.createElement('b'); heading.textContent = label;
      const content = document.createElement('p'); content.textContent = text;
      box.appendChild(heading); box.appendChild(content);
      if (label === speakerLabel) {
        const choose = document.createElement('button');
        choose.className = 'action'; choose.textContent = 'Rate this reply';
        choose.addEventListener('click', () => select(turn)); box.appendChild(choose);
      }
      chat.appendChild(box);
    }
    chat.scrollTop = chat.scrollHeight;
  }
  dimension.addEventListener('change', () => { note.value = selected?.ratings[dimension.value]?.note ?? ''; refresh(); });
  stars.forEach(button => button.addEventListener('click', async () => {
    const score = Number(button.getAttribute('data-score'));
    if (!selected || busy() || button.disabled || !Number.isInteger(score) || Math.abs(score) > 5) return;
    const turn = selected, key = dimension.value, text = note.value.trim();
    saving = true; refresh();
    try {
      await request('/api/conversation/feedback', post({response_id: turn.response_id, dimension: key, score, note: text}));
      turn.ratings[key] = {score, note: text}; notify('Saved ' + key + ' rating ' + score);
    } catch (_) { notify('Failed to save feedback. Please try again.'); }
    finally { saving = false; refresh(); }
  }));
  unrate?.addEventListener('click', async () => {
    if (!selected || busy() || unrate.disabled) return;
    const turn = selected, key = dimension.value;
    saving = true; refresh();
    try {
      await request('/api/conversation/feedback', post({response_id: turn.response_id, dimension: key}, 'DELETE'));
      delete turn.ratings[key]; note.value = ''; notify('Rating removed. This aspect is now unrated.');
    } catch (_) { notify('Could not remove rating. Please retry.'); }
    finally { saving = false; refresh(); }
  });
  recall?.addEventListener('change', async () => {
    if (!ready || busy() || autoRunning) return;
    const desired = recall.checked; working = true; refresh();
    try { await request('/api/conversation/preferences', post({recall: desired}, 'PUT')); }
    catch (_) { recall.checked = !desired; notify('Could not change preference recall. Please retry.'); }
    finally { working = false; refresh(); }
  });
  exportButton?.addEventListener('click', async () => {
    if (!ready || busy()) return;
    working = true; refresh();
    try {
      const data = await request('/api/conversation/export');
      environment.download(JSON.stringify(data, null, 2), 'conversation.json');
      notify('Conversation export downloaded.');
    } catch (_) { notify('Could not export conversation. Please retry.'); }
    finally { working = false; refresh(); }
  });
  clear?.addEventListener('click', async () => {
    if (!ready || busy() || !environment.confirm('Delete this browser’s saved conversation and ratings? This cannot be undone.')) return;
    working = true; refresh();
    try {
      await request('/api/conversation', {method: 'DELETE'});
      chat.replaceChildren(); selected = null; input.value = ''; note.value = ''; storeDraft('');
      notify('Conversation and ratings deleted.');
    } catch (_) { notify('Could not delete conversation. Please retry.'); }
    finally { working = false; refresh(); }
  });
  async function performTurn(message, speaker = null, automatic = false) {
    sending = true; refresh();
    try {
      const data = await request('/api/conversation', post({message, speaker, automatic}));
      if (typeof data.response_id !== 'string' || typeof data.reply !== 'string') throw Error('Invalid reply');
      const turn = {response_id: data.response_id, message, reply: data.reply, ratings: {}, speaker: data.speaker ?? speaker, automatic};
      addTurn(turn); sending = false; select(turn);
      return true;
    } catch (_) {
      notify('Could not confirm message. Your text is kept. Reload history before retrying to check whether it saved.');
      return false;
    } finally { sending = false; refresh(); }
  }
  function stopAutomatic() {
    autoRunning = false;
    if (autoWake) autoWake();
    if (humanQueue.length) {
      input.value = [...humanQueue.splice(0), input.value].filter(Boolean).join('\n');
      storeDraft(input.value);
    }
    refresh();
  }
  async function submit() {
    if (!ready || !input.value.trim() || working || saving) return;
    const message = input.value.trim();
    if (autoRunning) {
      if (humanQueue.length >= 5) { notify('Five messages are queued. Wait for a reply before adding more.'); return; }
      humanQueue.push(message); input.value = ''; storeDraft('');
      notify('Your message is queued for the next reply.');
      if (autoWake) autoWake();
      refresh(); return;
    }
    if (sending) return;
    if (await performTurn(message)) { input.value = ''; storeDraft(''); }
  }
  autoStop?.addEventListener('click', stopAutomatic);
  autoStart?.addEventListener('click', async () => {
    if (!ready || busy() || autoRunning) return;
    const limit = Number(autoLimit.value);
    const topic = autoTopic.value.trim();
    if (!autoLimit.value.trim() || !Number.isInteger(limit) || limit < 0 || limit > 200 || !topic || topic.length > 4000) {
      notify('Choose 0 (until stopped) or 1 to 200 turns and enter a discussion topic (up to 4000 characters).'); return;
    }
    autoRunning = true; autoBudget = limit; autoCount = 0; autoSpeaker = 'A'; refresh();
    let first = true;
    try {
      while (autoRunning && (autoBudget === 0 || autoCount < autoBudget)) {
        const human = humanQueue.shift();
        const message = human ?? (first ? topic : 'Continue the text discussion.');
        const automatic = !human && !first;
        const ok = await performTurn(message, autoSpeaker, automatic);
        if (!ok) {
          if (!automatic) humanQueue.unshift(message);
          break;
        }
        storeDraft(input.value);
        first = false; autoCount++; autoSpeaker = autoSpeaker === 'A' ? 'B' : 'A'; refresh();
        if (autoRunning && (autoBudget === 0 || autoCount < autoBudget) && humanQueue.length === 0) {
          await new Promise(resolve => {
            const timer = setTimeout(() => { autoWake = null; resolve(); }, environment.autoDelayMs ?? 2000);
            autoWake = () => { clearTimeout(timer); autoWake = null; resolve(); };
          });
        }
      }
    } finally {
      stopAutomatic();
      notify('Automatic conversation paused after ' + autoCount + ' turns.');
    }
  });
  send.addEventListener('click', submit);
  input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); submit(); } });
  refresh();
  const loaded = request('/api/conversation').then(data => {
    if (!Array.isArray(data.turns)) throw Error('Invalid history');
    data.turns.forEach(addTurn);
    if (data.turns.length) select(data.turns[data.turns.length - 1]);
    if (recall) recall.checked = data.recall !== false;
    ready = true; refresh();
  }).catch(() => {
    target.textContent = 'Could not load conversation. Reload this page to retry.';
    notify('Could not load conversation. Reload this page to retry.');
  });
  return {loaded};
}
if (typeof module !== 'undefined') module.exports = {initConversation};
else {
  let storage;
  try { storage = window.localStorage; } catch (_) {}
  initConversation(document, window.fetch.bind(window), toast, {
    storage, confirm: message => window.confirm(message),
    download(text, filename) {
      const url = URL.createObjectURL(new Blob([text], {type: 'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = filename;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
}
