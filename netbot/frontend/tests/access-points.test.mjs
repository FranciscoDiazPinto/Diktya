import test from 'node:test';
import assert from 'node:assert/strict';
import {createAccessPoints} from '../modules/access-points.mjs';

class Element {
  constructor(text='',value=''){this.textContent=text;this.value=value;this.children=[];this.events={};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  addEventListener(name,handler){this.events[name]=handler;}
}
const deferred=()=>{let resolve;return {promise:new Promise(r=>{resolve=r;}),resolve:v=>resolve(v)};};
const stamp='2026-10-30T12:00:00Z';
const ap=(id='a')=>({id,name:`AP ${id}`,state:'online',controller_state:'ONLINE',last_heartbeat_at:null,uptime_seconds:null,telemetry_available:false});
const envelope=data=>({source:'mock',status:'ok',collected_at:stamp,stale:false,issues:[],data});
const contents=node=>[node.textContent,...node.children.map(contents)].join(' ');

function setup(handler) {
  const ids=['ap-network','ap-body','access-points-panel','ap-nav','ap-status','ap-interface-summary','ap-pagination','ap-refresh','ap-network-label','ap-page','ap-previous','ap-next'];
  const nodes=new Map(ids.map(id=>['#'+id,new Element()]));
  const state={session:1},calls=[],timers=new Map();let id=0;
  const request=async path=>{calls.push(path);return handler(path);};
  const controller=createAccessPoints({document:{querySelector:s=>nodes.get(s),createElement:()=>new Element()},
    window:{setInterval(fn){const n=++id;timers.set(n,fn);return n;},clearInterval:n=>timers.delete(n)},
    Option:Element,state,api:{authedRequest:request,monitoringRequest:request},
    textNode:(tag,text)=>new Element(text),formatDuration:s=>`${s}s`});
  controller.reset();
  return {controller,state,calls,nodes,timers,$:id=>nodes.get('#'+id)};
}

test('technical user selects an authorized network and never requests global monitoring',async()=>{
  const ui=setup(async path=>path==='/api/v1/networks'?[{id:1,name:'Red A',ssid:'A'}]:{
    access_points:envelope([ap()]),interfaces:envelope([{interface_id:'opt1',status:'up'}])});
  await ui.controller.configureUser({permissions:['networks:read:details']});
  assert.equal(ui.$('access-points-panel').hidden,false);
  ui.$('ap-network').value='1';ui.$('ap-network').events.change();
  await new Promise(r=>setImmediate(r));
  assert.deepEqual(ui.calls,['/api/v1/networks','/api/v1/networks/1/telemetry']);
  assert.match(contents(ui.$('ap-body')),/AP a/);
  assert.match(ui.$('ap-interface-summary').textContent,/opt1/);
});

test('customer never sees or requests technical telemetry',async()=>{
  const ui=setup(()=>{throw Error('should not request');});
  await ui.controller.configureUser({permissions:['chat:use','networks:read:own']});
  assert.equal(ui.$('access-points-panel').hidden,true);assert.equal(ui.calls.length,0);
});

test('old response cannot appear after switching network or account',async()=>{
  const pending=deferred();
  const ui=setup(path=>path==='/api/v1/networks'?[{id:1,name:'A'},{id:2,name:'B'}]:path.includes('/1/')?pending.promise:{access_points:envelope([ap('b')]),interfaces:envelope([])});
  await ui.controller.configureUser({permissions:['networks:read:details']});
  ui.$('ap-network').value='1';ui.$('ap-network').events.change();
  ui.$('ap-network').value='2';ui.$('ap-network').events.change();
  await new Promise(r=>setImmediate(r));
  assert.match(contents(ui.$('ap-body')),/AP b/);
  pending.resolve({access_points:envelope([ap('a')]),interfaces:envelope([])});
  await new Promise(r=>setImmediate(r));
  assert.doesNotMatch(contents(ui.$('ap-body')),/AP a/);
  ui.state.session+=1;ui.controller.reset();
  assert.equal(contents(ui.$('ap-body')).trim(),'');assert.equal(ui.timers.size,0);
});

test('stale global inventory is marked historical and remote heartbeat stays unknown',async()=>{
  const ui=setup(async()=>({...envelope({items:[ap()],total_count:1}),status:'degraded',stale:true}));
  await ui.controller.configureUser({permissions:['monitoring:read']});
  assert.match(ui.$('ap-status').textContent,/SIMULACIÓN.*DATOS ANTERIORES/);
  assert.match(contents(ui.$('ap-body')),/Anterior: En línea/);
  assert.match(contents(ui.$('ap-body')),/No disponible/);
});

test('global pagination uses server total and never loads unbounded data',async()=>{
  const ui=setup(async path=>envelope({items:[ap(path.includes('offset=25')?'second':'first')],total_count:30}));
  await ui.controller.configureUser({permissions:['monitoring:read']});
  assert.equal(ui.$('ap-next').disabled,false);
  ui.$('ap-next').events.click();await new Promise(r=>setImmediate(r));
  assert.match(ui.calls[1],/limit=25&offset=25/);
  assert.match(contents(ui.$('ap-body')),/AP second/);
  assert.equal(ui.$('ap-next').disabled,true);
});

test('revocation clears previous AP and interface rather than showing cached privileged data',async()=>{
  let forbidden=false;
  const ui=setup(async()=>{if(forbidden)throw Object.assign(Error('Forbidden'),{status:403});return envelope({items:[ap()],total_count:1});});
  await ui.controller.configureUser({permissions:['monitoring:read']});
  forbidden=true;await ui.controller.poll();
  assert.doesNotMatch(contents(ui.$('ap-body')),/AP a/);
  assert.equal(ui.$('ap-interface-summary').textContent,'');
});
