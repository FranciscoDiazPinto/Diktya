// Vistas locales por hash: permisos y estado de cada funcionalidad siguen en sus controladores.
const VIEWS = [
  {key:'overview',nav:'overview-nav',title:'Resumen y chat',description:'Monitorea tu infraestructura y conversa con Netbot desde el mismo lugar.',allow:()=>true},
  ...[ ['devices','Dispositivos','Inventario de equipos y su estado.'], ['alerts','Alertas','Incidentes activos de infraestructura.'], ['wireless','SSID y VLAN','Redes detectadas por las integraciones.'], ['coverage','Planos','Ubicación de AP en planos del recinto.'] ].map(([key,title,description])=>({key,nav:key+'-nav',title,description,allow:p=>p.has('monitoring:read')})),
  {key:'access-points-panel',nav:'ap-nav',title:'Puntos de acceso',description:'Estado y telemetría de los AP que puedes consultar.',allow:p=>p.has('monitoring:read')||p.has('networks:read:details')},
  {key:'interfaces',nav:'interfaces-nav',title:'Interfaces',description:'Enlaces y tráfico de las interfaces del firewall.',allow:p=>p.has('monitoring:read')},
  {key:'clients',nav:'clients-nav',title:'Clientes',description:'Consulta y filtra las concesiones DHCP.',allow:p=>p.has('monitoring:read')},
  {key:'firewall',nav:'firewall-nav',title:'Firewall',description:'Estadísticas y eventos del firewall.',allow:p=>p.has('monitoring:read')},
  {key:'support-panel',nav:'support-nav',title:'Mi red',description:'Comprueba una red autorizada, recupera su acceso o solicita soporte.',allow:p=>p.has('networks:read:own')||p.has('wifi:access:read:own')||p.has('networks:manage')},
  {key:'tickets-panel',nav:'tickets-nav',title:'Tickets',description:'Consulta el seguimiento y gestiona las solicitudes autorizadas.',allow:p=>['tickets:read:own','tickets:read:assigned','tickets:read','tickets:manage'].some(x=>p.has(x))},
  {key:'provisioning',nav:'provisioning-nav',title:'Aprovisionamiento',description:'Revisa planes SSID, cargas CSV y reservas antes de confirmar.',allow:p=>p.has('changes:request')||p.has('vlan:reserve')},
  {key:'audit',nav:'audit-nav',title:'Auditoría',description:'Trazabilidad de acciones y estados registrados.',allow:p=>p.has('audit:read')},
];
const MONITORING_VIEWS=new Set(['overview','interfaces','clients','firewall']);

export function createNavigation({document,window,onViewChanged=()=>{}}) {
  const $=id=>document.querySelector('#'+id);
  let permissions=new Set(),user=null,active=null;
  const allowed=view=>user && view.allow(permissions);
  const resolve=hash=>VIEWS.find(view=>'#'+view.key===(hash==='#chat'?'#overview':hash));
  const overview=VIEWS[0];
  function updateLocation(view,replace) {
    const hash='#'+view.key;
    if(window.location?.hash===hash)return;
    if(replace)window.history?.replaceState?.(null,'',hash);
    else window.history?.pushState?.(null,'',hash);
  }
  function apply(view,{focus=false}={}) {
    if(!user)return false;
    if(!view || !allowed(view)){view=overview;updateLocation(view,true);}
    if(window.location?.hash==='#chat')updateLocation(overview,true);
    const previous=active;active=view.key;
    for(const item of VIEWS) {
      $('view-'+item.key).hidden=item.key!==view.key;
      const link=$(item.nav);link.classList.toggle('active',item.key===view.key);
      if(item.key===view.key)link.setAttribute('aria-current','page');else link.removeAttribute?.('aria-current');
    }
    const global=permissions.has('monitoring:read'),monitoring=global && MONITORING_VIEWS.has(view.key);
    $('global-monitoring-actions').hidden=!monitoring;$('global-monitoring-notices').hidden=!monitoring;
    $('overview-monitoring').hidden=!global;
    $('dashboard-chat-layout').classList.toggle('personal',!global);
    $('chat').hidden=!permissions.has('chat:use');
    $('overview-period-tools').hidden=!(global && view.key==='overview');
    $('greeting').hidden=view.key!=='overview';$('view-title').hidden=view.key==='overview';
    $('view-title').textContent=view.title;$('current-view-label').textContent=view.title;
    $('view-description').textContent=view.key==='overview' && !global
      ? 'Accede a tus redes, conversaciones y solicitudes de soporte.' : view.description;
    document.querySelector('.sidebar').classList.remove('open');
    if(previous!==active)onViewChanged(previous,active);
    if(focus){$('view-title').focus?.({preventScroll:true});window.scrollTo?.({top:0,behavior:'instant'});}
    return true;
  }
  function navigate(key,{replace=false,focus=true}={}) {
    if(key==='chat') {if(!permissions.has('chat:use'))return false;key='overview';}
    const view=VIEWS.find(item=>item.key===key);
    if(!allowed(view || {allow:()=>false}))return false;
    updateLocation(view,replace);return apply(view,{focus});
  }
  function reset() {
    if(active!==null)onViewChanged(active,null);
    active=null;user=null;permissions=new Set();
    for(const view of VIEWS){$('view-'+view.key).hidden=true;$(view.nav).hidden=true;$(view.nav).classList.remove('active');$(view.nav).removeAttribute?.('aria-current');}
    $('personal-overview').replaceChildren();$('current-view-label').textContent='Resumen';
  }
  function configureUser(value) {
    user=value;permissions=new Set(user.permissions || []);
    for(const view of VIEWS)$(view.nav).hidden=!allowed(view);
    $('personal-overview').hidden=permissions.has('monitoring:read');
    $('reservations-summary').hidden=!permissions.has('vlan:reserve');
    const shortcuts=[];
    for(const view of VIEWS.filter(view=>view.key!=='overview' && allowed(view))) {
      const link=document.createElement('a');link.className='overview-shortcut';link.href='#'+view.key;
      const title=document.createElement('strong');title.textContent=view.title;
      const detail=document.createElement('span');detail.textContent=view.description;
      link.append(title,detail);link.addEventListener('click',event=>{event.preventDefault();navigate(view.key);});shortcuts.push(link);
    }
    $('personal-overview').replaceChildren(...shortcuts);
    apply(resolve(window.location?.hash || '#overview'));
  }
  // Los enlaces internos existentes (incluido «Ver todo») participan de la navegación.
  const anchors=new Set([...VIEWS.map(view=>$(view.nav)),...document.querySelectorAll('a[href^="#"]')]);
  for(const link of anchors)link.addEventListener('click',event=>{
    const view=resolve(link.getAttribute?.('href') || link.href);
    if(!view || !user)return;
    event.preventDefault();navigate(view.key);
  });
  const restore=()=>{if(user)apply(resolve(window.location?.hash || '#overview'));};
  window.addEventListener?.('hashchange',restore);window.addEventListener?.('popstate',restore);
  document.querySelector('.mobile-menu').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('open'));
  return {reset,configureUser,navigate,get currentView(){return active;}};
}
