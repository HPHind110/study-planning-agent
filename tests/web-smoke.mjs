// Real browser integration test. The caller supplies a temporary database and profile.
import {spawn} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import assert from 'node:assert/strict';

const [edge,profile,base]=process.argv.slice(2);
const browser=spawn(edge,['--headless=new','--disable-gpu','--disable-extensions',
  '--disable-background-networking','--no-first-run','--remote-debugging-port=0',
  '--user-data-dir='+profile,'about:blank'],{stdio:'ignore',windowsHide:true});
const pending=new Map();
let requestId=0,sessionId,socket;
async function connect(){
  let address;
  for(let i=0;i<150;i++){
    try{address=await readFile(join(profile,'DevToolsActivePort'),'utf8');if(address.includes('/devtools/'))break}catch{}
    await new Promise(r=>setTimeout(r,100));
  }
  if(!address)throw Error('Edge did not start its local test endpoint');
  const [port,path]=address.trim().split(/\r?\n/);
  socket=new WebSocket('ws://127.0.0.1:'+port+path);
  await new Promise((ok,fail)=>{socket.onopen=ok;socket.onerror=fail});
  socket.onmessage=e=>{
    const msg=JSON.parse(e.data);
    if(pending.has(msg.id)){pending.get(msg.id)(msg);pending.delete(msg.id)}
  };
}
async function send(method,params={},session){
  const id=++requestId;
  const reply=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('Timeout '+method)),10000);
    pending.set(id,msg=>{clearTimeout(timer);resolve(msg)});
    socket.send(JSON.stringify({id,method,params,sessionId:session}));
  });
  if(reply.error)throw Error(JSON.stringify(reply.error));
  return reply.result;
}
async function js(expression){
  const r=await send('Runtime.evaluate',{expression,returnByValue:true},sessionId);
  if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);
  return r.result.value;
}
async function wait(expression){
  for(let n=0;n<100;n++){
    if(await js(expression))return;
    await new Promise(r=>setTimeout(r,50));
  }
  throw Error('Timeout '+expression+' '+await js('document.body.innerText'));
}
const click=selector=>js('document.querySelector('+JSON.stringify(selector)+').click()');
try{
  await connect();
  const {targetId}=await send('Target.createTarget',{url:'about:blank'});
  ({sessionId}=await send('Target.attachToTarget',{targetId,flatten:true}));
  await send('Page.navigate',{url:base},sessionId);
  await wait("document.querySelector('.week') && !busy");
  assert.equal(await js("document.querySelectorAll('.day').length"),7);
  const current=await js('selected');
  await click('[data-action="next"]');assert.notEqual(await js('selected'),current);
  await click('[data-action="today"]');assert.equal(await js('selected'),current);
  await click('[data-action="new"]');
  await js("document.querySelector('[name=name]').value='Browser assignment';document.querySelector('[name=course]').value='Systems';document.querySelector('#form').requestSubmit()");
  await wait("!busy && !document.querySelector('dialog').open && state.sessions.length");
  await click('[data-page="tasks"]');await click('[data-action="edit"]');await click('[data-action="log"]');
  await js("document.querySelector('[name=actual]').value=35;document.querySelector('[name=remaining]').value=0;document.querySelector('#form').requestSubmit()");
  await wait("!busy && !document.querySelector('dialog').open");
  await js("document.querySelector('#filter').value='done';document.querySelector('#filter').dispatchEvent(new Event('change',{bubbles:true}))");
  assert.ok(await js("document.querySelector('#view').textContent.includes('Browser assignment')"));
  await click('[data-page="history"]');
  assert.ok(await js("document.querySelector('#view').textContent.includes('35 phút')"));
  await click('[data-page="courses"]');
  await click('[data-action="courseNew"]');
  await js("document.querySelector('[name=name]').value='Systems';document.querySelector('#form').requestSubmit()");
  await wait("!busy && document.querySelector('#error').textContent.length>0");
  assert.ok(await js("document.querySelector('dialog').open"));
  await click('[data-action="close"]');
  await click('[data-action="settings"]');
  await js("document.querySelector('[name=cap]').value=75;document.querySelector('#form').requestSubmit()");
  await wait("!busy && state.settings.cap===75");
  await click('[data-page="calendar"]');
  await click('[data-action="evNew"]');
  await js("document.querySelector('[name=name]').value='Academic meeting';document.querySelector('#form').requestSubmit()");
  await wait("!busy && Object.values(state.events||{}).some(ev=>ev.name==='Academic meeting')");
  await click('[data-page="overview"]');
  assert.ok(await js("document.querySelector('#view').textContent.includes('Academic meeting')"));
  await click('[data-page="workload"]');
  assert.ok(await js("document.querySelectorAll('#view table').length>=3"));
  await click('[data-page="exchange"]');
  await click('[data-action="import"]');
  await js(`{
    const transfer=new DataTransfer();
    transfer.items.add(new File([JSON.stringify({tasks:[{id:'browser-import',name:'Imported task',
      course:'Systems',due:offset(today(),5)+' 22:00',estimate:80}]})],'input.json'));
    document.querySelector('[name=file]').files=transfer.files;
    document.querySelector('#form').requestSubmit();
  }`);
  await wait("!busy && document.querySelector('#dialogTitle').textContent.includes('Xem trước')");
  assert.ok(await js("!state.tasks['browser-import']"));
  await js("document.querySelector('#form').requestSubmit()");
  await wait("!busy && state.tasks['browser-import']?.left===80");
}finally{
  try{if(socket?.readyState===1)await send('Browser.close')}finally{socket?.close();if(browser.exitCode===null)browser.kill()}
}

