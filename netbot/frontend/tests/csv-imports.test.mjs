import test from 'node:test';
import assert from 'node:assert/strict';
import { createCsvImports } from '../modules/csv-imports.mjs';
class Element {
  constructor(text='',value='') { this.textContent=text; this.value=value; this.children=[]; this.events={}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  addEventListener(event,handler) { this.events[event]=handler; }
  setAttribute() {}
}
const batch = () => ({id:'batch-a',filename:'test.csv',status:'preview',source:'mock',simulated:true,expires_at:'2030-01-01T00:00:00Z',valid_count:2,invalid_count:1,results:[],rows:[
  {row_number:2,data:{parent_interface:'igc1',tag:20,ssid:'SSID-A',event_name:'Evento',purpose:'Clientes'},errors:[]},
  {row_number:3,data:null,errors:['VLAN inválida']},
  {row_number:4,data:{parent_interface:'igc1',tag:30,ssid:'SSID-B',event_name:'Evento',purpose:'Staff'},errors:[]},
]});
function setup(request) {
 const nodes=new Map(); const state={session:1}; let confirmed=0;
 const document={querySelector(selector) { if(!nodes.has(selector)) nodes.set(selector,new Element()); return nodes.get(selector); },createElement(){return new Element();}};
 const controller=createCsvImports({document,Option:Element,state,api:{authedRequest:request},textNode:(tag,text)=>new Element(text),onConfirmed(){confirmed++;}});
 return {nodes,state,controller,get confirmed(){return confirmed;}, async upload(){const input=nodes.get('#csv-file'); input.files=[{name:'test.csv',size:10,arrayBuffer:async()=>new TextEncoder().encode('synthetic').buffer}]; input.events.change(); await nodes.get('#csv-form').events.submit({preventDefault(){}});}};
}
test('CSV sends bytes outside chat and confirms only selected valid row numbers',async()=>{
 const calls=[]; const ui=setup(async(path,options)=>{ calls.push({path,options}); if(path.endsWith('/confirm')) {const result=batch();result.status='confirmed';result.results=[{row_number:2,reservation:{id:9,tag:20,status:'reserved'}}];return result;} return batch(); });
 await ui.upload();
 assert.ok(calls[0].options.body instanceof Uint8Array);
 assert.equal(calls[0].options.headers['Content-Type'],'text/csv; charset=utf-8');
 const controls=ui.nodes.get('#csv-rows').children.map(row=>row.children[0].children[0]);
 assert.equal(controls[1].disabled,true);
 controls[2].checked=false; controls[2].events.change();
 assert.equal(calls.length,1);
 await ui.nodes.get('#csv-confirm').events.click();
 assert.deepEqual(JSON.parse(calls[1].options.body),{row_numbers:[2]});
 assert.equal(ui.confirmed,1); assert.equal(ui.nodes.get('#csv-confirm').disabled,true);
 assert.ok(calls.every(call=>!call.path.includes('/chat/')));
});
test('late preview is discarded after account changes',async()=>{
 let resolve; const pending=new Promise(r=>{resolve=r;}); const ui=setup(()=>pending);
 const upload=ui.upload(); await new Promise(r=>setImmediate(r));
 ui.state.session++; ui.controller.reset(); await ui.controller.configureUser({permissions:[]});
 resolve(batch()); await upload;
 assert.equal(ui.nodes.get('#csv-panel').hidden,true);
 assert.equal(ui.nodes.get('#csv-preview').hidden,true);
 assert.equal(ui.nodes.get('#csv-rows').children.length,0);
});
test('conflict blocks confirmation until a new validation',async()=>{
 const ui=setup(async(path)=>{if(path.endsWith('/confirm')) throw Object.assign(new Error('Conflicto'),{status:409});return batch();});
 await ui.upload(); await ui.nodes.get('#csv-confirm').events.click();
 assert.equal(ui.nodes.get('#csv-confirm').disabled,true);
 assert.equal(ui.nodes.get('#csv-status').textContent,'Conflicto');
 await ui.upload(); assert.equal(ui.nodes.get('#csv-confirm').disabled,false);
});
test('oversized file is rejected before API access',async()=>{
 let calls=0;const ui=setup(async()=>{calls++;return batch();});
 ui.nodes.get('#csv-file').files=[{name:'large.csv',size:1048577}];
 await ui.nodes.get('#csv-form').events.submit({preventDefault(){}});
 assert.equal(calls,0); assert.match(ui.nodes.get('#csv-status').textContent,/tamaño máximo/);
});
test('own persisted preview is restored and cancelled without creating reservations',async()=>{
 const calls=[];const ui=setup(async(path)=>{calls.push(path);if(path.endsWith('/options')) return {max_bytes:1024,max_rows:5,ttl_seconds:900};if(path.endsWith('/csv-imports')) return [{id:'batch-a',filename:'test.csv',status:'preview'}];const result=batch(); if(path.endsWith('/cancel')) result.status='cancelled';return result;});
 await ui.controller.configureUser({permissions:['vlan:reserve']});
 assert.equal(ui.nodes.get('#csv-preview').hidden,false);
 assert.equal(ui.nodes.get('#csv-upload').disabled,false);
 await ui.nodes.get('#csv-cancel').events.click();
 assert.equal(ui.nodes.get('#csv-confirm').disabled,true); assert.equal(ui.confirmed,0);
 assert.ok(!calls.some(path=>path.endsWith('/confirm')));
});
