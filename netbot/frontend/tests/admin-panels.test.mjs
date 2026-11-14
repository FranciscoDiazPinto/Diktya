import test from 'node:test';
import assert from 'node:assert/strict';
import {createUsers,describeError} from '../modules/users.mjs';
import {createAccount} from '../modules/account.mjs';
import {createSystemStatus} from '../modules/system-status.mjs';
import {createAudit} from '../modules/audit.mjs';

class Element {
  constructor(){this.value='';this.children=[];this.events={};this.textContent='';this.checked=false;}
  addEventListener(name,fn){this.events[name]=fn;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  click(){} remove(){}
  get text(){return [this.textContent,...this.children.map(child=>child.text)].join(' ');}
}
function harness(request) {
  const nodes=new Map(),calls=[],state={session:1},timers=[];
  const document={querySelector(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement(){return new Element();},body:{append(){}}};
  const api={async authedRequest(path,options={}){calls.push({path,method:options.method||'GET',body:options.body&&JSON.parse(options.body)});return request(path,options);}};
  const textNode=(tag,value)=>{const node=new Element();node.textContent=value??'';return node;};
  const window={setInterval(fn,ms){timers.push({fn,ms});return timers.length;},clearInterval(id){timers[id-1].cleared=true;},URL:{createObjectURL(){return 'blob:x';},revokeObjectURL(){}}};
  return {document,api,state,calls,textNode,window,timers,$:id=>document.querySelector('#'+id)};
}
const user={id:2,email:'tech@example.com',full_name:'<i>Tec</i>',is_active:true,roles:['tecnico']};

test('user administration is invisible without users:manage',async()=>{
  const h=harness(async()=>[user]);const users=createUsers(h);users.reset();
  await users.configureUser({permissions:['users:read']});
  assert.equal(h.calls.length,0);assert.equal(h.$('users-body').children.length,0);
});

test('create, edit, deactivate and unlock use the administrative API and render text only',async()=>{
  const h=harness(async(path,options)=>options.method?{...user}:[user]);const users=createUsers(h);users.reset();
  await users.configureUser({permissions:['users:manage']});
  const row=h.$('users-body').children[0];
  assert.equal(row.children[1].textContent,'<i>Tec</i>');assert.equal(row.children[1].innerHTML,undefined);
  await h.$('user-form').events.submit({preventDefault(){}});
  assert.match(h.$('users-status').textContent,/contraseña temporal/);
  h.$('user-email').value=' nuevo@example.com ';h.$('user-password').value='clave-temporal-segura';
  await h.$('user-form').events.submit({preventDefault(){}});
  assert.deepEqual(h.calls.find(c=>c.method==='POST').body,{email:'nuevo@example.com',password:'clave-temporal-segura',full_name:null,roles:['visor']});
  assert.equal(h.$('user-password').value,''); // la clave no permanece en el formulario
  await row.children[4].children[0].events.click();
  assert.equal(h.$('user-email').disabled,true);h.$('user-active').checked=false;
  await h.$('user-form').events.submit({preventDefault(){}});
  const patch=h.calls.find(c=>c.method==='PATCH');
  assert.equal(patch.path,'/admin/users/2');assert.deepEqual(patch.body,{full_name:'<i>Tec</i>',roles:['tecnico'],is_active:false});
  await row.children[4].children[1].events.click();
  assert.ok(h.calls.some(c=>c.path==='/admin/users/2/unlock'&&c.method==='POST'));
});

test('validation errors name the affected field',()=>{
  const error=Object.assign(new Error('x'),{body:{detail:[{loc:['body','password'],msg:'Usa al menos 12 caracteres.'}]}});
  assert.equal(describeError(error),'password: Usa al menos 12 caracteres.');
  assert.equal(describeError(new Error('El correo ya existe.')),'El correo ya existe.');
});

test('own password change validates locally, never keeps the secrets and signs out on success',async()=>{
  let signedOut=0;const h=harness(async()=>null);
  const account=createAccount({...h,onPasswordChanged:()=>signedOut++});account.reset();account.configureUser(user);
  const fill=(a,b,c)=>{h.$('account-current').value=a;h.$('account-new').value=b;h.$('account-repeat').value=c;};
  fill('actual','corta','corta');await h.$('account-form').events.submit({preventDefault(){}});
  assert.match(h.$('account-status').textContent,/12 caracteres/);
  fill('actual','nueva-clave-larga-1','nueva-clave-larga-2');await h.$('account-form').events.submit({preventDefault(){}});
  assert.match(h.$('account-status').textContent,/no coincide/);assert.equal(h.calls.length,0);
  fill('actual','nueva-clave-larga-1','nueva-clave-larga-1');await h.$('account-form').events.submit({preventDefault(){}});
  assert.deepEqual(h.calls[0],{path:'/auth/password',method:'POST',body:{current_password:'actual',new_password:'nueva-clave-larga-1'}});
  assert.equal(signedOut,1);assert.equal(h.$('account-new').value,'');assert.equal(h.$('account-current').value,'');
});

test('a wrong current password is reported without signing out',async()=>{
  let signedOut=0;const h=harness(async()=>{throw Object.assign(new Error('No autorizado'),{status:403});});
  createAccount({...h,onPasswordChanged:()=>signedOut++});
  h.$('account-current').value='x';h.$('account-new').value='nueva-clave-larga-1';h.$('account-repeat').value='nueva-clave-larga-1';
  await h.$('account-form').events.submit({preventDefault(){}});
  assert.match(h.$('account-status').textContent,/actual no es correcta/);assert.equal(signedOut,0);
});

test('system status shows agents and warns when the change executor is not running',async()=>{
  const agents=[{agent_id:'monitoring',status:'ok',last_success_at:'2026-11-13T12:00:00Z',consecutive_failures:0},
    {agent_id:'tickets',status:'failed',last_success_at:null,consecutive_failures:3,last_error:'OSError',last_error_at:'2026-11-13T12:00:00Z'}];
  const h=harness(async path=>path.endsWith('/status')?agents:{provider:'anthropic',model:'claude-opus-5-5',detail:'Conexión verificada.'});
  const system=createSystemStatus(h);system.reset();
  await system.configureUser({permissions:['chat:use']});assert.equal(h.calls.length,0);
  await system.configureUser({permissions:['monitoring:read']});
  assert.equal(h.$('agents-body').children.length,2);
  assert.match(h.$('agents-body').children[1].text,/Con errores.*OSError/);
  assert.match(h.$('system-status').textContent,/ejecutor de cambios no está activo/);
  assert.equal(h.$('llm-health').textContent,'anthropic · claude-opus-5-5: Conexión verificada.');
  system.reset();assert.equal(h.timers[0].cleared,true);assert.equal(h.$('agents-body').children.length,0);
});

test('technician audit reads only /audit/mine and cannot export',async()=>{
  const h=harness(async()=>({items:[],total:0}));const audit=createAudit(h);
  await audit.configureUser({permissions:['changes:request']});
  assert.equal(h.calls[0].path.startsWith('/api/v1/audit/mine?'),true);
  assert.equal(h.$('audit-actor').disabled,true);assert.equal(h.$('audit-export').disabled,true);
  await h.$('audit-export').events.click();assert.equal(h.calls.length,1);
  audit.reset();assert.equal(h.$('audit-actor').disabled,false);
  await audit.configureUser({permissions:['audit:read','changes:request']});
  assert.equal(h.calls[1].path.startsWith('/api/v1/audit?'),true);
});
