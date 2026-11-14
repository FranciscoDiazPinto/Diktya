import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createNavigation} from '../modules/navigation.mjs';

class Element {
  constructor(){this.children=[];this.events={};this.attributes={};this.textContent='';this.classes=new Set();this.classList={toggle:(c,value)=>value?this.classes.add(c):this.classes.delete(c),remove:c=>this.classes.delete(c)};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  addEventListener(name,fn){this.events[name]=fn;}
  setAttribute(key,value){this.attributes[key]=value;}
  getAttribute(key){return this.attributes[key]??null;}
  removeAttribute(key){delete this.attributes[key];}
  focus(){this.focused=true;}
}
function setup(hash='#overview') {
  const html=readFileSync(new URL('../index.html',import.meta.url),'utf8');
  const nodes=new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>['#'+m[1],new Element()]));
  const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);assert.equal(new Set(ids).size,ids.length);
  const anchors=[];
  for(const match of html.matchAll(/<a\b[^>]*>/g)) {
    const id=match[0].match(/\bid="([^"]+)"/)?.[1],href=match[0].match(/href="([^"]+)"/)?.[1];
    if(!href?.startsWith('#'))continue;
    const node=id?nodes.get('#'+id):new Element();node.attributes.href=href;anchors.push(node);
  }
  nodes.set('.sidebar',new Element());nodes.set('.mobile-menu',new Element());
  const events={},history=[];const location={hash};
  const document={querySelector(selector){assert(nodes.has(selector),selector);return nodes.get(selector);},querySelectorAll(){return anchors;},createElement(){return new Element();}};
  const changes=[];
  const navigation=createNavigation({document,window:{location,history:{pushState(a,b,value){location.hash=value;history.push(value);},replaceState(a,b,value){location.hash=value;}},addEventListener:(n,f)=>{events[n]=f;},scrollTo(){}},onViewChanged:(a,b)=>changes.push([a,b])});
  navigation.reset();
  return {navigation,nodes,location,history,events,changes,anchors,$:id=>nodes.get('#'+id),visible:()=>[...nodes].filter(([id,node])=>id.startsWith('#view-')&&!['#view-title','#view-description'].includes(id)&&node.hidden===false).map(([id])=>id)};
}
const admin={permissions:['monitoring:read','chat:use','networks:read:details','networks:read:own','changes:request','vlan:reserve','tickets:read','networks:manage']};

test('the supervisor can reach read-only tickets through navigation and a direct URL',()=>{
  const supervisor={permissions:['monitoring:read','chat:use','changes:read']};
  const ui=setup('#tickets-panel');ui.navigation.configureUser(supervisor);
  assert.equal(ui.$('tickets-nav').hidden,false);
  assert.equal(ui.navigation.currentView,'tickets-panel');
  ui.navigation.navigate('overview');assert.equal(ui.navigation.navigate('tickets-panel'),true);
  assert.equal(ui.navigation.navigate('provisioning'),false);
  assert.equal(ui.navigation.navigate('users'),false);
});

test('only the chosen view is visible; sidebar changes route, heading and browser history',()=>{
  const ui=setup();ui.navigation.configureUser(admin);
  assert.deepEqual(ui.visible(),['#view-overview']);
  ui.$('ap-nav').events.click({preventDefault(){}});
  assert.deepEqual(ui.visible(),['#view-access-points-panel']);assert.equal(ui.$('current-view-label').textContent,'Puntos de acceso');
  assert.equal(ui.location.hash,'#access-points-panel');assert.equal(ui.$('ap-nav').getAttribute('aria-current'),'page');
  assert.equal(ui.$('global-monitoring-actions').hidden,true);
  ui.navigation.navigate('interfaces');
  assert.deepEqual(ui.visible(),['#view-interfaces']);assert.equal(ui.$('global-monitoring-actions').hidden,false);
  assert.equal(ui.$('ap-nav').getAttribute('aria-current'),null);
});

test('technical role cannot reveal global pages by URL or programmatic navigation',()=>{
  const ui=setup('#firewall');ui.navigation.configureUser({permissions:['chat:use','networks:read:own','networks:read:details','changes:request']});
  assert.deepEqual(ui.visible(),['#view-overview']);assert.equal(ui.location.hash,'#overview');
  assert.equal(ui.$('firewall-nav').hidden,true);assert.equal(ui.navigation.navigate('firewall'),false);
  assert.equal(ui.navigation.navigate('access-points-panel'),true);
  assert.deepEqual(ui.visible(),['#view-access-points-panel']);
  assert.equal(ui.$('reservations-summary').hidden,true);
});

test('customer overview offers only permitted sections and never provisioning or technical AP',()=>{
  const ui=setup();ui.navigation.configureUser({permissions:['chat:use','networks:read:own','tickets:read:own']});
  assert.equal(ui.$('personal-overview').hidden,false);
  assert.equal(ui.$('ap-nav').hidden,true);assert.equal(ui.$('provisioning-nav').hidden,true);
  assert.equal(ui.$('personal-overview').children.length,3); // Mi red, Tickets y Mi cuenta
  ui.$('personal-overview').children[0].events.click({preventDefault(){}});
  assert.equal(ui.navigation.currentView,'support-panel');
});

test('refresh/deep link and browser back preserve the view without reloading modules',()=>{
  const ui=setup('#clients');ui.navigation.configureUser(admin);
  assert.equal(ui.navigation.currentView,'clients');
  ui.navigation.navigate('chat');ui.location.hash='#clients';ui.events.popstate();
  assert.equal(ui.navigation.currentView,'clients');assert.deepEqual(ui.visible(),['#view-clients']);
  ui.location.hash='#unknown';ui.events.hashchange();assert.equal(ui.navigation.currentView,'overview');
});

test('leaving access view and sign out notify cleanup and hide every view',()=>{
  const ui=setup();ui.navigation.configureUser(admin);ui.navigation.navigate('support-panel');ui.navigation.navigate('chat');
  assert.ok(ui.changes.some(([a,b])=>a==='support-panel'&&b==='overview'));
  ui.navigation.reset();assert.deepEqual(ui.visible(),[]);assert.equal(ui.$('personal-overview').children.length,0);
  assert.equal(ui.navigation.navigate('chat'),false);
});

test('existing in-page firewall link opens the firewall view rather than scrolling a hidden panel',()=>{
  const ui=setup();ui.navigation.configureUser(admin);
  const link=ui.anchors.find(link=>link.getAttribute('href')==='#firewall'&&link!==ui.$('firewall-nav'));
  link.events.click({preventDefault(){}});
  assert.equal(ui.navigation.currentView,'firewall');assert.deepEqual(ui.visible(),['#view-firewall']);
});


test('chat belongs to the dashboard and old chat links open the combined overview',()=>{
  const ui=setup('#chat');ui.navigation.configureUser(admin);
  assert.deepEqual(ui.visible(),['#view-overview']);assert.equal(ui.$('chat').hidden,false);
  assert.equal(ui.location.hash,'#overview');
  ui.navigation.configureUser({permissions:['monitoring:read']});
  assert.equal(ui.$('chat').hidden,true);
});


test('integrated inventory modules each open a separate view and reject unprivileged deep links',()=>{
  for(const key of ['devices','alerts','wireless','coverage']) {
    const ui=setup('#'+key);ui.navigation.configureUser(admin);
    assert.deepEqual(ui.visible(),['#view-'+key]);
    ui.navigation.configureUser({permissions:['chat:use','tickets:read:own']});
    assert.deepEqual(ui.visible(),['#view-overview']);
    assert.equal(ui.$(key+'-nav').hidden,true);
    assert.equal(ui.navigation.navigate(key),false);
  }
});

 test('audit deep links require audit permission',()=>{
  const denied=setup('#audit');denied.navigation.configureUser({permissions:['chat:use','monitoring:read','tickets:read:own']});assert.equal(denied.navigation.currentView,'overview');assert.equal(denied.$('audit-nav').hidden,true);assert.equal(denied.navigation.navigate('audit'),false);
  const allowed=setup('#audit');allowed.navigation.configureUser({permissions:['audit:read']});assert.equal(allowed.navigation.currentView,'audit');assert.equal(allowed.$('audit-nav').hidden,false);
});


test('technician opens only the own-audit view; users and system pages stay administrative',()=>{
  const ui=setup('#audit');ui.navigation.configureUser({permissions:['chat:use','changes:request']});
  assert.equal(ui.navigation.currentView,'audit');
  assert.equal(ui.navigation.navigate('users'),false);assert.equal(ui.$('users-nav').hidden,true);
  assert.equal(ui.navigation.navigate('system'),false);assert.equal(ui.$('system-nav').hidden,true);
  assert.equal(ui.navigation.navigate('account'),true);assert.deepEqual(ui.visible(),['#view-account']);
  const admin=setup('#users');admin.navigation.configureUser({permissions:['users:manage','monitoring:read']});
  assert.equal(admin.navigation.currentView,'users');assert.equal(admin.navigation.navigate('system'),true);
});
