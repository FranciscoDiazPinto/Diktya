// Inventario operativo UniFi. El técnico consulta exclusivamente una red asignada.
export function createAccessPoints({document, window, Option, state, api, textNode, formatDuration}) {
  const $=s=>document.querySelector(s);
  let generation=0, requestId=0, timer=null, mode=null, offset=0, total=0, busy=false;
  let lastResponse=null, lastReceived=0;
  const network=$('#ap-network'), body=$('#ap-body'), pageSize=25;
  const capture=()=>({generation,session:state.session});
  const current=c=>c.generation===generation && c.session===state.session;
  const date=value=>value ? new Date(value).toLocaleString('es-CL') : 'No disponible';
  function reset() {
    generation+=1;requestId+=1;busy=false;mode=null;offset=0;total=0;lastResponse=null;lastReceived=0;
    if(timer!==null)window.clearInterval(timer);timer=null;
    $('#access-points-panel').hidden=true;$('#ap-nav').hidden=true;
    $('#ap-status').textContent='';$('#ap-interface-summary').textContent='';$('#ap-pagination').hidden=true;
    network.replaceChildren(new Option('Selecciona una red',''));body.replaceChildren();
    $('#ap-refresh').disabled=false;
  }
  function rowMessage(text) {
    const row=document.createElement('tr'),cell=textNode('td',text);cell.colSpan=5;row.append(cell);body.replaceChildren(row);
  }
  function render(response, items, {disconnected=false}={}) {
    const old=response.stale || disconnected;
    const issues=(response.issues || []).map(i=>i.message).join(' ');
    $('#ap-status').textContent=`${response.source==='mock'?'SIMULACIÓN · ':''}${old?'DATOS ANTERIORES':'Lectura'}: ${date(response.collected_at)} · ${disconnected?'Sin conexión con Netbot; reintentando. ':''}${issues}`;
    body.replaceChildren();
    if(items===null) {rowMessage('Estado de AP no disponible. Esto no confirma una caída física.');return;}
    if(!items.length) {rowMessage(old?'El inventario anterior no contenía AP; el estado actual es desconocido.':'No hay AP en este inventario o vinculación.');return;}
    const labels={online:'En línea',offline:'Fuera de línea',transitioning:'En transición',unknown:'Desconocido'};
    for(const ap of items) {
      const row=document.createElement('tr'),name=document.createElement('td');
      name.append(textNode('strong',ap.name),textNode('div',ap.model || 'Modelo no informado'));
      const status=textNode('td',`${old?'Anterior: ':''}${labels[ap.state] || 'Desconocido'} (${ap.controller_state || 'No informado'})`);
      row.append(name,status,textNode('td',date(ap.last_heartbeat_at)),
        textNode('td',ap.uptime_seconds==null?'No disponible':formatDuration(ap.uptime_seconds)),
        textNode('td',ap.telemetry_available ? `${ap.cpu_percent==null?'CPU N/D':'CPU '+ap.cpu_percent+'%'} · ${ap.memory_percent==null?'RAM N/D':'RAM '+ap.memory_percent+'%'}`:'No disponible'));
      body.append(row);
    }
  }
  function pagination() {
    $('#ap-pagination').hidden=mode!=='global';
    $('#ap-page').textContent=total?`${offset+1}–${Math.min(offset+pageSize,total)} de ${total}`:'Sin registros';
    $('#ap-previous').disabled=offset===0;$('#ap-next').disabled=offset+pageSize>=total;
  }
  async function poll() {
    if(!mode || busy || (mode==='scoped' && !network.value))return;
    const context=capture(),id=++requestId;busy=true;$('#ap-refresh').disabled=true;
    try {
      let response,items;
      if(mode==='global') {
        response=await api.monitoringRequest(`/access-points?limit=${pageSize}&offset=${offset}`);
        if(!current(context) || id!==requestId)return;
        total=response.data?.total_count || 0;items=response.data?.items ?? null;
        if(total && offset>=total){offset=0;busy=false;await poll();return;}
      } else {
        const result=await api.authedRequest(`/api/v1/networks/${Number(network.value)}/telemetry`);
        if(!current(context) || id!==requestId)return;
        response=result.access_points;items=response.data;
        const linked=result.interfaces,iface=linked.data?.[0];
        $('#ap-interface-summary').textContent=iface
          ? `Interfaz de esta red: ${iface.description || iface.interface_id} · ${iface.status}${linked.stale?' · DATOS ANTERIORES':''} · lectura ${date(linked.collected_at)}`
          : 'La interfaz de esta red no está verificada.';
      }
      lastResponse={response,items};lastReceived=Date.now();render(response,items);pagination();
    } catch(error) {
      if(!current(context) || id!==requestId)return;
      if(error.status===401 || error.status===403 || error.status===404) {
        lastResponse=null;rowMessage('El acceso cambió. Vuelve a seleccionar una red autorizada.');
        $('#ap-interface-summary').textContent='';$('#ap-status').textContent=error.message;
      } else if(lastResponse && Date.now()-lastReceived<=300000) {
        render(lastResponse.response,lastResponse.items,{disconnected:true});
        $('#ap-interface-summary').textContent='Sin conexión: la interfaz mostrada anteriormente no está verificada ahora.';
      } else {lastResponse=null;rowMessage('No se pudo consultar el monitoreo. Se reintentará.');$('#ap-status').textContent=error.message;}
    } finally {if(current(context) && id===requestId){busy=false;$('#ap-refresh').disabled=false;}}
  }
  async function configureUser(user) {
    const global=user.permissions?.includes('monitoring:read');
    if(!global && !user.permissions?.includes('networks:read:details'))return;
    mode=global?'global':'scoped';$('#access-points-panel').hidden=false;$('#ap-nav').hidden=false;
    $('#ap-network-label').hidden=global;$('#ap-pagination').hidden=!global;
    const context=capture();
    if(global)await poll();
    else {
      rowMessage('Selecciona una red autorizada para consultar sus AP e interfaz.');
      try {
        const networks=await api.authedRequest('/api/v1/networks');if(!current(context))return;
        network.replaceChildren(new Option('Selecciona una red',''),...networks.map(n=>new Option(`${n.name} · ${n.ssid}`,n.id)));
        if(!networks.length)$('#ap-status').textContent='No tienes redes asignadas para monitoreo técnico.';
      } catch(error){if(current(context))$('#ap-status').textContent=error.message;}
    }
    if(current(context))timer=window.setInterval(poll,10000);
  }
  network.addEventListener('change',()=>{
    generation+=1;requestId+=1;busy=false;lastResponse=null;lastReceived=0;
    $('#ap-interface-summary').textContent='';$('#ap-status').textContent='';body.replaceChildren();
    $('#ap-refresh').disabled=false;poll();
  });
  $('#ap-refresh').addEventListener('click',poll);
  $('#ap-previous').addEventListener('click',()=>{if(!busy && offset>0){offset=Math.max(0,offset-pageSize);poll();}});
  $('#ap-next').addEventListener('click',()=>{if(!busy && offset+pageSize<total){offset+=pageSize;poll();}});
  return {reset,configureUser,poll};
}
