import test from 'node:test';
import assert from 'node:assert/strict';
import {createSession} from '../modules/session.mjs';

class Element {
  constructor() {this.style={};this.classList={add(){},remove(){}};this.firstChild={textContent:''};this.events={};}
  addEventListener(name,callback){this.events[name]=callback;}
  reset(){}
  focus(){this.focused=true;}
}
const deferred=()=>{let resolve;return {promise:new Promise(r=>{resolve=r;}),resolve:value=>resolve(value)};};

function setup(handler=async()=>({})) {
  const ids=['guest-back','login-screen','app-shell','login-form','login-submit','login-error','toggle-password','logout-button','user-name','user-role','user-avatar','email','password'];
  const nodes=new Map(ids.map(id=>['#'+id,new Element()]));
  const timers=new Map(),events={},calls=[];
  let time=100000,id=0,tokens=null,signedOut=null;
  const state={user:null,session:0};
  const api={getStoredTokens:()=>tokens,setTokens:value=>{tokens=value;},clearTokens:()=>{tokens=null;},
    apiRequest:async(path,options={})=>{calls.push({path,options});return handler(path,options);},
    authedRequest:async(path)=>handler(path)};
  const session=createSession({document:{querySelector:s=>nodes.get(s),addEventListener:(n,f)=>{events[n]=f;}},
    window:{setTimeout(f,ms){const n=++id;timers.set(n,{f,at:time+ms});return n;},clearTimeout:n=>timers.delete(n),addEventListener:(n,f)=>{events[n]=f;}},
    now:()=>time,state,api,FormData:class{get(key){return key==='email'?'demo@example.com':'demo-password';}},
    showToast(){},onAuthenticated(){},onSignedOut:value=>{signedOut=value;}});
  const person={id:1,email:'demo@example.com',roles:['cliente']};
  const token=exp=>'header.'+Buffer.from(JSON.stringify({exp})).toString('base64url')+'.signature';
  return {nodes,state,session,calls,events,person,token,
    get tokens(){return tokens;},set tokens(value){tokens=value;},get signedOut(){return signedOut;},
    advance(ms){time+=ms;for(const [n,t]of[...timers])if(t.at<=time){timers.delete(n);t.f();}},
    elapse(ms){time+=ms;}};
}

test('idle session expires at JWT deadline, masks password, revokes refresh and returns to login',async()=>{
  const ui=setup();ui.tokens={access_token:ui.token(160),refresh_token:'session-refresh'};
  ui.session.setAuthenticated(ui.person);ui.nodes.get('#password').type='text';
  ui.advance(59999);assert.equal(ui.state.user.id,1);
  ui.advance(1);
  assert.equal(ui.tokens,null);assert.equal(ui.state.user,null);
  assert.equal(ui.signedOut.expired,true);
  assert.equal(ui.nodes.get('#login-screen').style.display,'');
  assert.equal(ui.nodes.get('#password').type,'password');
  assert.equal(ui.nodes.get('#email').focused,true);
  assert.deepEqual(JSON.parse(ui.calls.find(c=>c.path==='/auth/logout').options.body),{refresh_token:'session-refresh'});
  assert.ok(!ui.calls.some(c=>c.path==='/auth/refresh'));
});

test('returning from suspended tab immediately expires the session without waiting for a timer',()=>{
  const ui=setup();ui.tokens={access_token:ui.token(160),refresh_token:'refresh'};ui.session.setAuthenticated(ui.person);
  ui.elapse(120000);ui.events.visibilitychange();
  assert.equal(ui.state.user,null);assert.equal(ui.tokens,null);
});

test('login response cannot restore a session after sign out',async()=>{
  const pending=deferred();const ui=setup(path=>path==='/auth/login'?pending.promise:ui.person);
  const submission=ui.nodes.get('#login-form').events.submit({preventDefault(){}});
  ui.session.signOut();pending.resolve({access_token:ui.token(160),refresh_token:'late'});
  await submission;
  assert.equal(ui.tokens,null);assert.equal(ui.state.user,null);
  assert.equal(ui.nodes.get('#login-submit').disabled,false);
});

test('failed profile lookup after credentials does not leave tokens installed',async()=>{
  const ui=setup(async path=>{if(path==='/auth/login')return {access_token:ui.token(160),refresh_token:'token'};throw new Error('offline');});
  await ui.nodes.get('#login-form').events.submit({preventDefault(){}});
  assert.equal(ui.tokens,null);assert.equal(ui.state.user,null);
});


test('returning to guest chat cancels an in-flight login',async()=>{
  const pending=deferred();const ui=setup(path=>path==='/auth/login'?pending.promise:ui.person);
  const submission=ui.nodes.get('#login-form').events.submit({preventDefault(){}});
  ui.nodes.get('#guest-back').events.click();
  pending.resolve({access_token:ui.token(160),refresh_token:'late'});
  await submission;
  assert.equal(ui.tokens,null);assert.equal(ui.state.user,null);
  assert.equal(ui.nodes.get('#login-submit').disabled,false);
});
