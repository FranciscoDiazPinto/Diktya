import test from 'node:test';
import assert from 'node:assert/strict';
import {createAudit} from '../modules/audit.mjs';
class Element {
  constructor() { this.value='';this.children=[];this.events={};this.textContent=''; }
  addEventListener(name, fn) {this.events[name]=fn;}
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children=nodes;}
  click() {this.clicked=true;}
  remove() {this.removed=true;}
}
const row={occurred_at:'2026-11-05T12:00:00Z',source:'auth',actor_id:1,action:'<img src=x>',outcome:'success',resource_type:'user',resource_id:'1',snapshot:false};
function setup(request=async()=>({items:[row],total:51})) {
  const nodes=new Map(), calls=[], downloads=[], revoked=[];const state={session:1};
  const document={querySelector(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement(){return new Element();},body:{append(link){downloads.push(link);}}};
  const window={URL:{createObjectURL(){return 'blob:audit';},revokeObjectURL(url){revoked.push(url);}}};
  const api={authedRequest(path,options){calls.push({path,options});return request(path,options);}};
  const audit=createAudit({document,window,state,api});
  return {audit,state,calls,downloads,revoked,$:id=>document.querySelector('#audit-'+id)};
}
const admin={permissions:['audit:read']};
test('audit is restricted and changing account clears rows and filters',async()=>{
  const ui=setup();await ui.audit.configureUser({permissions:['changes:read']});assert.equal(ui.calls.length,0);
  await ui.audit.configureUser(admin);ui.$('action').value='private';assert.equal(ui.$('body').children.length,1);
  ui.audit.reset();assert.equal(ui.$('body').children.length,0);assert.equal(ui.$('action').value,'');
  await ui.$('export').events.click();assert.equal(ui.calls.length,1);
});
test('audit filters, pagination and text rendering',async()=>{
  const ui=setup();await ui.audit.configureUser(admin);
  assert.equal(ui.$('body').children[0].children[3].textContent,row.action);
  assert.equal(ui.$('body').children[0].children[3].innerHTML,undefined);
  ui.$('source').value='auth';ui.$('actor').value='5';ui.$('action').value='auth.login';
  await ui.$('filters').events.submit({preventDefault(){}});
  assert.match(ui.calls.at(-1).path,/actor_id=5/);assert.match(ui.calls.at(-1).path,/source=auth/);
  await ui.$('next').events.click();assert.match(ui.calls.at(-1).path,/offset=50/);
  await ui.$('clear').events.click();assert.equal(ui.$('source').value,'');assert.match(ui.calls.at(-1).path,/offset=0/);
});
test('late list and export from an old session never render or download',async()=>{
  let resolve;const ui=setup(()=>new Promise(r=>{resolve=r;}));
  const loading=ui.audit.configureUser(admin);ui.state.session++;ui.audit.reset();resolve({items:[row],total:1});await loading;
  assert.equal(ui.$('body').children.length,0);
  const ready=ui.audit.configureUser(admin);resolve({items:[row],total:1});await ready;
  const exporting=ui.$('export').events.click();ui.state.session++;ui.audit.reset();resolve(new Blob(['private']));await exporting;
  assert.equal(ui.downloads.length,0);
});
test('CSV uses applied filters and revokes the temporary download URL',async()=>{
  const ui=setup(async(path)=>path.includes('/export')?new Blob(['csv']):({items:[row],total:1}));
  await ui.audit.configureUser(admin);ui.$('source').value='auth';await ui.$('filters').events.submit();
  ui.$('source').value='support';await ui.$('export').events.click();
  assert.match(ui.calls.at(-1).path,/source=auth/);assert.equal(ui.calls.at(-1).options.raw,true);
  assert.equal(ui.downloads[0].download,'netbot-auditoria.csv');assert.equal(ui.downloads[0].removed,true);assert.deepEqual(ui.revoked,['blob:audit']);
});
test('newer filters suppress an earlier response',async()=>{
  const pending=[];const ui=setup(()=>new Promise(r=>pending.push(r)));
  const first=ui.audit.configureUser(admin);ui.$('source').value='support';const second=ui.$('filters').events.submit();
  pending[1]({items:[],total:0});await second;pending[0]({items:[row],total:1});await first;
  assert.equal(ui.$('body').children.length,0);assert.equal(ui.$('page').textContent,'0 registros');
});

 test('failed export reports the error and allows retry',async()=>{
  let attempts=0;const ui=setup(async path=>{if(path.includes('/export')){if(++attempts===1)throw new Error('Reduce el rango');return new Blob(['csv']);}return {items:[row],total:1};});
  await ui.audit.configureUser(admin);await ui.$('export').events.click();assert.equal(ui.$('status').textContent,'Reduce el rango');assert.equal(ui.$('export').disabled,false);
  await ui.$('export').events.click();assert.equal(ui.downloads.length,1);
});
