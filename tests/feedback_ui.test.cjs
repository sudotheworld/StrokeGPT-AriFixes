const {test} = require('node:test');
const assert = require('node:assert/strict');
const {initConversation} = require('../static/conversation.js');
function element(score) {
  return {value: '', disabled: false, textContent: '', children: [], handlers: {}, attrs: {},
    classList: {toggle(name, on) {this[name] = on;}},
    getAttribute: () => String(score), setAttribute(k,v) {this.attrs[k]=v;},
    addEventListener(event, callback) {this.handlers[event]=callback;},
    appendChild(child) {this.children.push(child);},
  };
}
const rid = 'a'.repeat(32);
function setup(handler) {
  const ids = Object.fromEntries(['chat','composerInput','feedbackNote','feedbackDimension','feedbackTarget'].map(id => [id,element()]));
  ids.feedbackDimension.value='overall';
  const send=element(), stars=Array.from({length:11},(_,i)=>element(i-5));
  const document = {getElementById:id=>ids[id], querySelector:()=>send,
    querySelectorAll:()=>stars, createElement:()=>element()};
  const requests=[], toasts=[];
  const fetch=async (url, options)=> {
    requests.push({url, options});
    if (!options) return {ok:true, json:async()=>({ok:true, turns:[{response_id:rid, message:'Hi',reply:'Hello',ratings:{}}]})};
    return handler(url, options);
  };
  return {...initConversation(document, fetch, text=>toasts.push(text)), ids, send, stars, requests, toasts};
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
