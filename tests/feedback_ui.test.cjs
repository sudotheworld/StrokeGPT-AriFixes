const {test} = require('node:test');
const assert = require('node:assert/strict');
const {initConversation} = require('../static/conversation.js');
function element(score) {
  return {value: '', disabled: false, textContent: '', children: [], handlers: {}, attrs: {},
    classList: {toggle(name, on) {this[name] = on;}},
    getAttribute: () => String(score), setAttribute(k,v) {this.attrs[k]=v;}, focus() {this.focused=true;}, replaceChildren() {this.children=[];},
    addEventListener(event, callback) {this.handlers[event]=callback;},
    appendChild(child) {this.children.push(child);},
  };
}
const rid = 'a'.repeat(32);
function setup(handler, environment = {}) {
  const ids = Object.fromEntries(['chat','composerInput','feedbackNote','feedbackDimension','feedbackTarget','ratingSummary','removeRating','preferenceRecall','exportConversation','clearConversation','autoStart','autoStop','autoLimit','autoTopic','autoStatus'].map(id => [id,element()]));
  ids.feedbackDimension.value='overall';
  const send=element(), stars=Array.from({length:11},(_,i)=>element(i-5));
  const document = {getElementById:id=>ids[id], querySelector:()=>send,
    querySelectorAll:()=>stars, createElement:()=>element()};
  const requests=[], toasts=[];
  const fetch=async (url, options)=> {
    requests.push({url, options});
    if (!options?.method) return {ok:true, json:async()=>({ok:true, turns:[{response_id:rid, message:'Hi',reply:'Hello',ratings:{}}]})};
    return handler(url, options);
  };
  return {...initConversation(document, fetch, text=>toasts.push(text), environment), ids, send, stars, requests, toasts};
}
const success = data => ({ok:true,json:async()=>({ok:true,...data})});
test('unrated, neutral, exact response payload, pending lock, and success', async()=>{
  let finish;
  const ui=setup(()=>new Promise(resolve=>finish=resolve)); await ui.loaded;
  assert.ok(ui.stars.every(s=>s.attrs['aria-pressed']==='false'));
  ui.ids.feedbackNote.value='  Clear ✓  ';
  const pending=ui.stars[5].handlers.click();
  assert.ok(ui.stars.every(s=>s.disabled));
  assert.ok(ui.ids.feedbackDimension.disabled);
  await ui.stars[6].handlers.click();
  assert.equal(ui.requests.length,2);
  const request=ui.requests[1];
  assert.equal(request.url,'/api/conversation/feedback');
  assert.deepEqual(JSON.parse(request.options.body),{response_id:rid,dimension:'overall',score:0,note:'Clear ✓'});
  finish(success()); await pending;
  assert.equal(ui.stars[5].attrs['aria-pressed'],'true');
  assert.ok(ui.stars.every(s=>!s.disabled));
  assert.deepEqual(ui.toasts,['Saved overall rating 0']);
  ui.ids.feedbackDimension.value='tone'; ui.ids.feedbackDimension.handlers.change();
  assert.ok(ui.stars.every(s=>s.attrs['aria-pressed']==='false'));
});
for(const [name,handler] of [
  ['HTTP',async()=>({ok:false})],['network',async()=>{throw Error('offline');}],
  ['application',async()=>({ok:true,json:async()=>({ok:false})})],
  ['invalid JSON',async()=>({ok:true,json:async()=>{throw Error('invalid');}})],
  ['missing acknowledgement',async()=>({ok:true,json:async()=>({})})],
]) test(name+' failure preserves rating and permits retry',async()=>{
  const ui=setup(handler); await ui.loaded;
  ui.ids.feedbackNote.value='keep this'; await ui.stars[10].handlers.click();
  assert.ok(ui.stars.every(s=>!s.disabled));
  assert.ok(ui.stars.every(s=>s.attrs['aria-pressed']==='false'));
  assert.equal(ui.ids.feedbackNote.value,'keep this');
  assert.deepEqual(ui.toasts,['Failed to save feedback. Please try again.']);
});
test('send renders literal text and selects returned reply for feedback',async()=>{
  const ui=setup(async url=>success(url==='/api/conversation'?{response_id:'b'.repeat(32),reply:'<script>literal</script>'}:{}));
  await ui.loaded; ui.ids.composerInput.value='Question'; await ui.send.handlers.click();
  assert.equal(ui.ids.composerInput.value,'');
  assert.equal(ui.ids.chat.children.at(-1).children[1].textContent,'<script>literal</script>');
  await ui.stars[10].handlers.click();
  assert.equal(JSON.parse(ui.requests.at(-1).options.body).response_id,'b'.repeat(32));
  ui.ids.chat.children[1].children[2].handlers.click();
  await ui.stars[0].handlers.click();
  assert.equal(JSON.parse(ui.requests.at(-1).options.body).response_id,rid);
});
test('failed send keeps draft and unlocks composer',async()=>{
  const ui=setup(async()=>{throw Error('offline');}); await ui.loaded;
  ui.ids.composerInput.value='keep draft'; await ui.send.handlers.click();
  assert.equal(ui.ids.composerInput.value,'keep draft');
  assert.equal(ui.send.disabled,false); assert.equal(ui.ids.composerInput.disabled,false);
  assert.equal(ui.ids.chat.children.length,2);
});
test('failed history prevents sending against an unrestored conversation',async()=>{
  const ui=setup(async()=>success()); await ui.loaded;
  // Separate init with a failed history fetch.
  const result=initConversation({getElementById:id=>ui.ids[id],querySelector:()=>ui.send,
    querySelectorAll:()=>ui.stars,createElement:()=>element()}, async()=>({ok:false}),()=>{});
  await result.loaded;
  assert.equal(ui.send.disabled,true);
});

test('labels and keyboard navigation do not submit ratings',async()=>{
  const ui=setup(async()=>success()); await ui.loaded;
  assert.equal(ui.stars[0].attrs['aria-label'],'-5: Strongly dislike');
  assert.equal(ui.stars[5].attrs['aria-label'],'0: Neutral');
  ui.stars[0].handlers.keydown({key:'End',preventDefault(){}});
  assert.equal(ui.stars[10].focused,true); assert.equal(ui.requests.length,1);
});
test('removing rating preserves neutral on a different aspect',async()=>{
  const ui=setup(async()=>success()); await ui.loaded;
  await ui.stars[5].handlers.click();
  assert.match(ui.ids.ratingSummary.textContent,/overall: 0/);
  await ui.ids.removeRating.handlers.click();
  assert.ok(ui.stars.every(s=>s.attrs['aria-pressed']==='false'));
  assert.equal(ui.requests.at(-1).options.method,'DELETE');
  assert.equal(ui.ids.removeRating.disabled,true);
});
test('draft restores, persists typing, and clears after success',async()=>{
  const data=new Map([['conversation.textDraft.v1','saved draft']]);
  const storage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};
  const ui=setup(async()=>success({response_id:rid,reply:'response'}),{storage}); await ui.loaded;
  assert.equal(ui.ids.composerInput.value,'saved draft');
  ui.ids.composerInput.value='new draft'; ui.ids.composerInput.handlers.input();
  assert.equal(data.get('conversation.textDraft.v1'),'new draft');
  await ui.send.handlers.click(); assert.equal(data.size,0);
});
test('recall failure rolls back checkbox',async()=>{
  const ui=setup(async()=>({ok:false})); await ui.loaded;
  ui.ids.preferenceRecall.checked=false; await ui.ids.preferenceRecall.handlers.change();
  assert.equal(ui.ids.preferenceRecall.checked,true);
});
test('export downloads JSON and deletion requires confirmation',async()=>{
  const downloads=[];
  const ui=setup(async()=>success({turns:[]}),{download:(...args)=>downloads.push(args),confirm:()=>false}); await ui.loaded;
  await ui.ids.exportConversation.handlers.click();
  assert.equal(downloads[0][1],'conversation.json');
  const count=ui.requests.length; await ui.ids.clearConversation.handlers.click();
  assert.equal(ui.requests.length,count);
});
test('confirmed deletion clears UI only after acknowledgement',async()=>{
  const ui=setup(async()=>success(),{confirm:()=>true}); await ui.loaded;
  await ui.ids.clearConversation.handlers.click();
  assert.equal(ui.ids.chat.children.length,0);
  assert.ok(ui.stars.every(s=>s.disabled));
});
test('timeout releases controls and preserves draft',async()=>{
  const ui=setup(()=>new Promise(()=>{}),{timeoutMs:5}); await ui.loaded;
  ui.ids.composerInput.value='keep'; await ui.send.handlers.click();
  assert.equal(ui.ids.composerInput.value,'keep'); assert.equal(ui.send.disabled,false);
});
test('automatic discussion alternates, prioritizes interjection, and stops at budget',async()=>{
  const turns=[]; let finish;
  const ui=setup(async(url,options)=>{
    const payload=JSON.parse(options.body); turns.push(payload);
    if(turns.length===1) await new Promise(resolve=>finish=resolve);
    return success({response_id:String(turns.length).padStart(32,'0'),reply:'reply',speaker:payload.speaker});
  },{autoDelayMs:0}); await ui.loaded;
  ui.ids.autoLimit.value='3'; ui.ids.autoTopic.value='Discuss science.';
  const running=ui.ids.autoStart.handlers.click();
  assert.equal(ui.send.disabled,false); assert.equal(ui.ids.composerInput.disabled,false);
  ui.ids.composerInput.value='What does that mean?'; await ui.send.handlers.click();
  finish(); await running;
  assert.deepEqual(turns.map(t=>t.speaker),['A','B','A']);
  assert.equal(turns[1].message,'What does that mean?'); assert.equal(turns[1].automatic,false);
  assert.equal(turns[2].automatic,true); assert.equal(ui.ids.autoStop.disabled,true);
});
test('stop permits current reply but prevents further generation and restores queued text',async()=>{
  let finish,calls=0;
  const ui=setup(async()=>{calls++; await new Promise(resolve=>finish=resolve);return success({response_id:rid,reply:'reply'});});
  await ui.loaded; ui.ids.autoLimit.value='0'; ui.ids.autoTopic.value='Topic';
  const running=ui.ids.autoStart.handlers.click();
  ui.ids.composerInput.value='queued human message'; await ui.send.handlers.click();
  ui.ids.autoStop.handlers.click(); finish(); await running;
  assert.equal(calls,1); assert.equal(ui.ids.composerInput.value,'queued human message');
});
test('automatic request failure pauses without an automatic retry',async()=>{
  let calls=0;
  const ui=setup(async()=>{calls++;throw Error('offline');}); await ui.loaded;
  ui.ids.autoLimit.value='10'; ui.ids.autoTopic.value='Preserve this topic';
  await ui.ids.autoStart.handlers.click();
  assert.equal(calls,1); assert.equal(ui.ids.autoStop.disabled,true);
  assert.equal(ui.ids.composerInput.value,'Preserve this topic');
});
test('queued interjection is preserved in browser draft before generation completes',async()=>{
  const saved=new Map(); let finish;
  const storage={getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)};
  const ui=setup(async()=>{await new Promise(resolve=>finish=resolve);return success({response_id:rid,reply:'reply'});},{storage});
  await ui.loaded; ui.ids.autoLimit.value='0'; ui.ids.autoTopic.value='Topic';
  const running=ui.ids.autoStart.handlers.click();
  ui.ids.composerInput.value='My interjection'; await ui.send.handlers.click();
  assert.equal(saved.get('conversation.textDraft.v1'),'My interjection');
  ui.ids.autoStop.handlers.click(); finish(); await running;
  assert.equal(ui.ids.composerInput.value,'My interjection');
});
test('failed unrate and delete leave saved content visible',async()=>{
  let fail=false;
  const ui=setup(async()=>fail?{ok:false}:success(),{confirm:()=>true}); await ui.loaded;
  await ui.stars[5].handlers.click(); fail=true;
  await ui.ids.removeRating.handlers.click();
  assert.equal(ui.stars[5].attrs['aria-pressed'],'true');
  await ui.ids.clearConversation.handlers.click();
  assert.equal(ui.ids.chat.children.length,2);
  assert.equal(ui.stars[5].attrs['aria-pressed'],'true');
});
