import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../../maria_ui/static/js/chat_work.js',import.meta.url),'utf8');
const settle=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
function fixture() {
  class Node {
    constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.events={};this.value='';this.textContent='';}
    appendChild(child){this.children.push(child);return child;}
    replaceChildren(){this.children=[];}
    addEventListener(event,callback){this.events[event]=callback;}
  }
  const nodes=new Map(['workProject','workTasks','workStatus'].map(id=>[id,new Node()]));
  const docEvents={},winEvents={},timers=new Map(),calls=[],busy=[];let serial=0;
  const document={hidden:false,createElement:tag=>new Node(tag),addEventListener:(name,cb)=>{docEvents[name]=cb;},removeEventListener:name=>delete docEvents[name]};
  const window={atob,setTimeout:(cb,ms)=>{timers.set(++serial,{cb,ms});return serial;},clearTimeout:id=>timers.delete(id),addEventListener:(name,cb)=>{winEvents[name]=cb;}};
  let catalog={projects:[{key:'host/project',name:'Projekt <img onerror=evil()>',computerName:'Testowy komputer',available:true}],selectedProjectKey:'host/project'};
  let ledger={tasks:[]},respond=null;
  const M={$:id=>nodes.get(id),apiFetch:async(path,opts)=>{
    calls.push({path,opts});
    if(respond)return respond(path,opts);
    if(opts)return {success:true};
    return path.endsWith('/projects')?structuredClone(catalog):structuredClone(ledger);
  }};
  vm.runInNewContext(source,{window,document,console,TextDecoder});
  const api=window.MariaChatWork(M,{selectionBusy:value=>busy.push(value)});
  return {window,document,docEvents,winEvents,nodes,timers,calls,busy,api,set catalog(value){catalog=value;},set ledger(value){ledger=value;},set respond(value){respond=value;}};
}
const content=node=>node.textContent+' '+node.children.map(content).join(' ');
const task=(extra={})=>({key:'receipt-1',projectKey:'host/project',projectName:'Projekt',computerName:'Testowy komputer',status:'running',available:true,stale:false,resultText:'',...extra});
{
  const f=fixture();f.ledger={tasks:[task({status:'completed',completionEventId:'old',historical:true,resultText:'<script>evil()</script>',artifacts:[{path:'folder/a b.txt',name:'Dowód',available:true}]})]};
  await settle(); await f.api.refresh();
  assert.match(f.nodes.get('workStatus').textContent,/Stan zadań/,'initial completed import is silent');
  const card=f.nodes.get('workTasks').children[0];
  assert.equal(card.dataset.state,'completed');assert.match(content(card),/nie jest niezależną weryfikacją/);
  assert.ok(content(card).includes('<script>evil()</script>'),'executor output is literal text');
  assert.ok(f.nodes.get('workProject').children[1].textContent.includes('<img onerror=evil()>'));
  const artifactButton=card.children.find(node=>node.tag==='button');
  f.respond=async()=>({content:btoa('<script>literal artifact</script>'),name:'a b.txt',mime:'text/plain',size:32});
  // Actual decoded size is required; a mismatched descriptor is rejected.
  await artifactButton.events.click();assert.match(content(card),/Nie udało/);
  const artifactText='<script>literal artifact</script>';
  f.respond=async()=>({content:btoa(artifactText),name:'a b.txt',mime:'text/plain',size:artifactText.length});
  await artifactButton.events.click();
  assert.equal(f.calls.at(-1).path,'/api/work/tasks/receipt-1/artifact?path=folder%2Fa%20b.txt');
  assert.ok(content(card).includes(artifactText),'artifact markup is shown literally');
  assert.ok(card.children.some(node=>node.children.some(child=>child.tag==='pre')));
  f.respond=null;card.open=true;
  f.ledger={tasks:[task({status:'completed',completionEventId:'new',resultText:'Nowy wynik'})]};
  await f.api.refresh();assert.match(f.nodes.get('workStatus').textContent,/Nowy raport/);
  assert.equal(f.nodes.get('workTasks').children[0].open,true,'poll preserves expanded report');
  await f.api.refresh();assert.doesNotMatch(f.nodes.get('workStatus').textContent,/Nowy raport/,'completion announced once');
  assert.ok(f.calls.every(call=>!call.opts),'hydration and polling use GET only');
  assert.ok([...f.timers.values()].every(timer=>timer.ms===15000));
  f.api.dispose();assert.equal(f.timers.size,0);
}
{
  const f=fixture();f.ledger={tasks:[task({status:'completed',stale:true}),task({key:'offline',status:'completed',available:false}),task({key:'human',status:'completed',requiresHuman:true,humanStep:'Potwierdź na urządzeniu'})]};
  await settle(); await f.api.refresh();
  assert.deepEqual(f.nodes.get('workTasks').children.map(card=>card.dataset.state),['uncertain','uncertain','human']);
  assert.match(content(f.nodes.get('workTasks')),/Potwierdź na urządzeniu/);
  f.respond=async()=>null;await f.api.refresh();
  assert.ok(f.nodes.get('workTasks').children.every(card=>card.dataset.state==='uncertain'),'failed refresh downgrades all prior green');
  assert.match(f.nodes.get('workStatus').textContent,/nieaktualne/);
  f.api.dispose();
}
{
  const f=fixture();await settle();const before=f.calls.length;
  f.document.hidden=true;f.docEvents.visibilitychange();assert.equal(f.timers.size,0);
  await f.api.refresh();assert.equal(f.calls.length,before,'hidden page does not poll');
  f.document.hidden=false;f.docEvents.visibilitychange();await settle();assert.equal(f.calls.length,before+2);
  const releases=[];
  f.respond=()=>new Promise(resolve=>{releases.push(resolve);});
  const refresh=f.api.refresh();f.document.hidden=true;f.docEvents.visibilitychange();
  // Both GETs are delayed and invalidated by the page lifetime.
  releases[0]({projects:[],selectedProjectKey:''});releases[1]({tasks:[task({resultText:'Późny prywatny wynik'})]});
  await refresh;f.api.dispose();
  assert.doesNotMatch(content(f.nodes.get('workTasks')),/Późny/);
}
{
  const f=fixture();await settle();
  f.catalog={projects:[{key:'new',name:'Nowy',computerName:'Host'}],selectedProjectKey:'new'};
  f.nodes.get('workProject').value='new';
  await f.nodes.get('workProject').events.change();await settle();
  const posts=f.calls.filter(call=>call.opts);
  assert.equal(posts.length,1);assert.equal(posts[0].path,'/api/work/selection');
  assert.deepEqual(JSON.parse(posts[0].opts.body),{key:'new'});
  assert.deepEqual(f.busy,[true,false]);assert.equal(f.nodes.get('workProject').value,'new');
  assert.ok(!f.calls.some(call=>/send|cancel|analy|jobs/.test(call.path)),'selection never submits work');
  f.api.dispose();
}
console.log('work cards: hydration, once-only completion, literal DOM, artifacts, stale/offline/human, visible polling and selection: PASS');
{
  const f=fixture();await settle();const releases=[];
  f.respond=(path,opts)=>opts?{success:true}:new Promise(resolve=>releases.push(resolve));
  const oldRead=f.api.refresh();
  f.nodes.get('workProject').value='new-target';
  await f.nodes.get('workProject').events.change();
  assert.deepEqual(f.busy,[true],'selection remains blocked while obsolete read is outstanding');
  f.respond=async path=>path.endsWith('/projects')?{projects:[{key:'new-target',name:'Nowy projekt',computerName:'Host'}],selectedProjectKey:'new-target'}:{tasks:[]};
  releases[0]({projects:[],selectedProjectKey:'old-target'});releases[1]({tasks:[]});
  await oldRead;await settle();
  assert.deepEqual(f.busy,[true,false],'fresh confirmation follows stale read without waiting 15s');
  assert.equal(f.nodes.get('workProject').value,'new-target');f.api.dispose();
}
console.log('selection during in-flight polling discards old catalog and confirms current target: PASS');
