import test from 'node:test';
import assert from 'node:assert/strict';
import {createChangePlans} from '../modules/change-plans.mjs';

class Element {
  constructor(){this.value='';this.children=[];this.events={};this.textContent='';this.attributes={};}
  addEventListener(name,fn){this.events[name]=fn;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this.attributes[key]=value;}
  get text(){return [this.textContent,...this.children.map(child=>child.text)].join(' ');}
  button(label){return this.children.find(child=>child.type==='button'&&child.textContent===label);}
}
class Option{constructor(label,value){this.label=label;this.value=value;}}
const vlanPlan=(extra={})=>({id:'v1',ssid:'<b>Feria</b>',status:'preview',current_network_id:'n20',target_network_id:'n30',target_vlan:30,
  impact:'Los clientes se desconectarán.',purpose:'Migrar',revision:'r'.repeat(64),expires_at:'2099-01-01T00:00:00Z',execution_results:[],...extra});
const restartPlan=(extra={})=>({id:'r1',device_id:'ap1',device_name:'AP Hall',access_point:true,status:'preview',impact:'7 cliente(s) conectados se desconectarán durante el reinicio.',
  purpose:'Sin respuesta',revision:'s'.repeat(64),expires_at:'2099-01-01T00:00:00Z',execution_results:[],...extra});

function setup(routes={}) {
  const nodes=new Map(),calls=[],state={session:1},chatMessages=new Element(),opened=[];
  const document={querySelector(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement(){return new Element();}};
  const defaults={'/wifi-scopes':[{id:4,name:'Feria'}],'/ssid-vlan-change-plans':[],'/device-restart-plans':[],
    '/wifi-scopes/4/options':{simulated:false,networks:[{id:'n30',parent_interface:'igc1',tag:30}],aps:[{id:'ap1',name:'AP Hall'}]},
    '/wifi-scopes/4/ssids':[{id:'s1',ssid:'Feria'}]};
  const api={async authedRequest(path,options={}){
    const key=path.replace('/api/v1/changes','');calls.push({path:key,method:options.method||'GET',body:options.body&&JSON.parse(options.body)});
    const answer={...defaults,...routes}[key];
    if(answer instanceof Error)throw answer;
    return typeof answer==='function'?answer(options):answer;
  }};
  const textNode=(tag,value)=>{const node=new Element();node.tag=tag;node.textContent=value??'';return node;};
  let chatGeneration=0;
  const plans=createChangePlans({document,Option,state,api,textNode,chatMessages,captureChat:()=>chatGeneration,
    isChatCurrent:value=>value===chatGeneration,onOpenPlans:()=>opened.push(true)});
  return {plans,calls,state,chatMessages,opened,routes,$:id=>document.querySelector('#'+id),leaveChat(){chatGeneration++;}};
}
const tech={permissions:['changes:request','changes:approve']};
const admin={permissions:['changes:request','changes:approve','networks:manage']};

test('panel stays hidden and silent without the change permission',async()=>{
  const ui=setup();ui.plans.reset();await ui.plans.configureUser({permissions:['chat:use']});
  assert.equal(ui.$('changes-panel').hidden,true);assert.equal(ui.calls.length,0);
});

test('scope selection loads only authorized resources and enables both forms',async()=>{
  const ui=setup();ui.plans.reset();await ui.plans.configureUser(tech);
  assert.equal(ui.$('changes-panel').hidden,false);assert.equal(ui.$('restart-device-id-field').hidden,true);
  assert.equal(ui.$('vlan-change-prepare').disabled,true);
  ui.$('changes-scope').value='4';await ui.$('changes-scope').events.change();
  assert.deepEqual(ui.$('vlan-change-ssid').children.map(o=>o.value),['','s1']);
  assert.deepEqual(ui.$('restart-device').children.map(o=>o.label),['Selecciona un AP','AP Hall']);
  assert.equal(ui.$('vlan-change-prepare').disabled,false);assert.equal(ui.$('restart-prepare').disabled,false);
});

test('a VLAN change is only prepared; confirmation is a separate explicit request',async()=>{
  const ui=setup({'/ssid-vlan-change-plans':options=>options.method==='POST'?vlanPlan():[vlanPlan()]});
  ui.plans.reset();await ui.plans.configureUser(tech);
  ui.$('changes-scope').value='4';await ui.$('changes-scope').events.change();
  await ui.$('vlan-change-form').events.submit({preventDefault(){}});
  assert.match(ui.$('changes-status').textContent,/Selecciona SSID/);assert.equal(ui.calls.filter(c=>c.method==='POST').length,0);
  ui.$('vlan-change-ssid').value='s1';ui.$('vlan-change-network').value='n30';ui.$('vlan-change-purpose').value=' Migrar ';
  await ui.$('vlan-change-form').events.submit({preventDefault(){}});
  assert.deepEqual(ui.calls.find(c=>c.method==='POST').body,{scope_id:4,broadcast_id:'s1',network_id:'n30',purpose:'Migrar'});
  const card=ui.$('changes-plan-list').children[0];
  assert.match(card.text,/Impacto estimado/);assert.match(card.text,/<b>Feria<\/b>/); // texto, nunca HTML
  assert.equal(ui.calls.some(c=>c.path.endsWith('/confirm')),false);
  await card.button('Confirmar cambio de VLAN').events.click();
  const confirm=ui.calls.find(c=>c.path==='/ssid-vlan-change-plans/v1/confirm');
  assert.deepEqual(confirm.body,{revision:'r'.repeat(64)});
});

test('cancel never confirms and a failed confirmation can be retried',async()=>{
  const ui=setup({'/device-restart-plans':[restartPlan()],'/device-restart-plans/r1/confirm':new Error('La revisión no coincide.')});
  ui.plans.reset();await ui.plans.configureUser(tech);
  const card=ui.$('changes-plan-list').children[0],confirm=card.button('Confirmar reinicio');
  await confirm.events.click();
  assert.match(card.text,/La revisión no coincide/);assert.equal(confirm.disabled,false);
  await card.button('Cancelar').events.click();
  assert.ok(ui.calls.some(c=>c.path==='/device-restart-plans/r1/cancel'&&c.method==='POST'));
});

test('uncertain work is never retried from the browser; only administrators reconcile',async()=>{
  const stuck=vlanPlan({status:'uncertain',needs_reconciliation:true,execution_results:[{status:'uncertain'}]});
  const technician=setup({'/ssid-vlan-change-plans':[stuck]});technician.plans.reset();await technician.plans.configureUser(tech);
  const card=technician.$('changes-plan-list').children[0];
  assert.match(card.text,/no se reintenta automáticamente/);
  assert.equal(card.button('Conciliar leyendo el controlador'),undefined);assert.equal(card.button('Confirmar cambio de VLAN'),undefined);
  const manager=setup({'/ssid-vlan-change-plans':[stuck],'/reconcile/vlan/v1':{status:'completed'}});
  manager.plans.reset();await manager.plans.configureUser(admin);
  assert.equal(manager.$('restart-device-id-field').hidden,false);
  await manager.$('changes-plan-list').children[0].button('Conciliar leyendo el controlador').events.click();
  assert.ok(manager.calls.some(c=>c.path==='/reconcile/vlan/v1'&&c.method==='POST'));
});

test('results explain verification, restoration and restart outcomes',async()=>{
  const ui=setup({'/ssid-vlan-change-plans':[vlanPlan({status:'rolled_back',execution_results:[{status:'rolled_back'}]})],
    '/device-restart-plans':[restartPlan({status:'failed',execution_results:[{status:'did_not_return'}]})]});
  ui.plans.reset();await ui.plans.configureUser(tech);
  const [vlan,restart]=ui.$('changes-plan-list').children;
  assert.match(vlan.text,/se restauró el estado anterior/);assert.match(restart.text,/no volvió en línea/);
});

test('late responses from another session never render plans',async()=>{
  let release;const ui=setup({'/wifi-scopes':()=>new Promise(resolve=>{release=resolve;})});
  ui.plans.reset();const loading=ui.plans.configureUser(tech);
  ui.state.session++;ui.plans.reset();release([{id:4,name:'Feria'}]);await loading;
  assert.equal(ui.$('changes-scope').children.length,1);assert.equal(ui.$('changes-plan-list').children.length,0);
});

test('chat proposals create a plan only after the user asks and only in the same conversation',async()=>{
  const ui=setup({'/device-restart-plans':options=>options.method==='POST'?restartPlan():[restartPlan()]});
  ui.plans.reset();await ui.plans.configureUser(tech);
  ui.plans.renderRestartProposal({scope_id:4,device_id:'ap1',purpose:'Sin respuesta'});
  ui.plans.renderVlanProposal({scope_id:4,broadcast_id:'s1',network_id:'n30',purpose:'Migrar'});
  assert.equal(ui.calls.filter(c=>c.method==='POST').length,0);
  await ui.chatMessages.children[0].button('Preparar revisión en el panel').events.click();
  assert.deepEqual(ui.calls.find(c=>c.method==='POST').body,{scope_id:4,device_id:'ap1',purpose:'Sin respuesta'});
  assert.equal(ui.opened.length,1);
  ui.leaveChat();await ui.chatMessages.children[1].button('Preparar revisión en el panel').events.click();
  assert.equal(ui.calls.filter(c=>c.method==='POST').length,1);
});
