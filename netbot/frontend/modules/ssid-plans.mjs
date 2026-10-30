// Propuestas y confirmación por API; ninguna escritura de red desde el LLM.
export function createSsidPlans({document, Option, state, api, textNode, captureChat, isChatCurrent, chatMessages}) {
  const $ = s => document.querySelector(s), panel = $('#ssid-panel'), scope = $('#ssid-scope');
  let generation = 0, options = null, aps = [], busy = false;
  const capture = () => ({session:state.session,generation});
  const current = c => c.session === state.session && c.generation === generation;
  const request = (path, extra = {}) => api.authedRequest(`/api/v1/changes${path}`,extra);
  function controls(value) {
    busy = value; scope.disabled = value;
    $('#ssid-prepare').disabled = value || !options; $('#ssid-upload').disabled = value || !options;
  }
  function reset() {
    generation += 1; options = null; aps = []; panel.hidden = true;
    scope.replaceChildren(new Option('Selecciona un ámbito',''));
    $('#ssid-network').replaceChildren(new Option('Selecciona una red','')); $('#ssid-profile').replaceChildren(new Option('Selecciona un perfil',''));
    $('#ssid-aps').replaceChildren(); $('#ssid-plan-list').replaceChildren();
    for (const id of ['ssid-name','ssid-purpose','ssid-csv']) $(`#${id}`).value = '';
    $('#ssid-source').textContent = ''; $('#ssid-status').textContent = ''; controls(false);
  }
  function showPlan(plan) {
    const context = capture(), card = document.createElement('article'); card.className = 'reservation-card';
    card.append(textNode('strong', `${plan.simulated ? 'SIMULACIÓN · ' : ''}Plan ${plan.id} · ${plan.status}`));
    card.append(textNode('p', `Vence: ${new Date(plan.expires_at).toLocaleString('es-CL')}. La aprobación y la ejecución son etapas separadas.`));
    const selected = new Set();
    const confirm = textNode('button','Confirmar las filas seleccionadas'); confirm.type = 'button'; confirm.disabled = true;
    const valid = plan.status === 'preview' && new Date(plan.expires_at).getTime() > Date.now();
    for (const row of plan.rows) {
      const line = document.createElement('label'), check = document.createElement('input'); check.type = 'checkbox';
      check.disabled = !valid || !!row.errors.length || !row.proposal;
      const p = row.proposal;
      line.append(check, textNode('span', ` Fila ${row.row_number}: ${p ? `${p.ssid} → ${p.network_id} · AP: ${p.ap_ids.join(', ')} · perfil ${p.security_profile}` : 'Sin propuesta'}${row.errors.length ? ' · '+row.errors.join(' ') : ''}`));
      check.addEventListener('change', () => {
        if (!current(context) || check.disabled) return;
        if (check.checked) selected.add(row.row_number); else selected.delete(row.row_number);
        confirm.disabled = selected.size === 0;
      }); card.append(line);
    }
    if (valid) {
      const feedback = textNode('p','');
      confirm.addEventListener('click', async () => {
        if (!current(context) || !selected.size || confirm.disabled) return;
        confirm.disabled = true;
        try {
          const result = await request(`/ssid-plans/${plan.id}/confirm`,{method:'POST',body:JSON.stringify({revision:plan.revision,row_numbers:[...selected].sort((a,b)=>a-b)})});
          if (!current(context)) return;
          feedback.textContent = `${result.selection.length} fila(s) aprobadas. Pendientes del ejecutor; usa Recuperar planes para consultar el resultado.`;
          for (const input of inputs) input.disabled = true;
        } catch (error) { if (current(context)) { feedback.textContent = error.message; confirm.disabled = false; } }
      });
      const inputs = [...card.children].flatMap(n => n.children ? [...n.children].filter(c => c.type === 'checkbox') : []);
      const cancel = textNode('button','Cancelar propuesta'); cancel.type = 'button';
      cancel.addEventListener('click',async () => {
        if (!current(context) || cancel.disabled) return; cancel.disabled = confirm.disabled = true;
        try { await request(`/ssid-plans/${plan.id}/cancel`,{method:'POST'}); if (current(context)) { feedback.textContent = 'Propuesta cancelada.'; for (const input of inputs) input.disabled = true; } }
        catch(error) { if(current(context)) {feedback.textContent=error.message;cancel.disabled=false;confirm.disabled=!selected.size;} }
      });
      card.append(confirm,cancel,feedback);
    } else if (plan.status === 'confirmed') card.append(textNode('p','Aprobación registrada. Pendiente del ejecutor de cambios; consulta su resultado antes de afirmar que se desplegó.'));
    for (const result of plan.execution_results || []) card.append(textNode('p', `${result.ssid}: ${result.status}${result.external_id ? ' · ID '+result.external_id : ''}`));
    if (plan.status === 'completed') card.append(textNode('p','Configuración releída y verificada en el controlador. No equivale a una prueba de conexión Wi-Fi o Internet.'));
    if (['executing','uncertain'].includes(plan.status)) card.append(textNode('p','El trabajo no se reintenta automáticamente. Un estado incierto requiere conciliación del equipo técnico.'));
    $('#ssid-plan-list').append(card);
  }
  async function refresh() {
    const context = capture();
    try { const plans = await request('/ssid-plans'); if (!current(context)) return; $('#ssid-plan-list').replaceChildren(); for(const p of plans) showPlan(p); }
    catch(error) { if(current(context)) $('#ssid-status').textContent = error.message; }
  }
  async function configureUser(user) {
    if(!user.permissions?.includes('changes:request')) return;
    panel.hidden = false; const context = capture();
    try {
      const scopes = await request('/wifi-scopes'); if(!current(context)) return;
      scope.replaceChildren(new Option('Selecciona un ámbito',''),...scopes.map(s => new Option(s.name,s.id)));
      $('#ssid-status').textContent = scopes.length ? 'Selecciona un ámbito para consultar AP y VLAN autorizados.' : 'No tienes ámbitos de aprovisionamiento asignados. Un administrador debe configurarlos.';
      await refresh();
    } catch(error) { if(current(context)) $('#ssid-status').textContent = error.message; }
  }
  scope.addEventListener('change',async () => {
    generation += 1; options = null; aps = []; $('#ssid-aps').replaceChildren(); $('#ssid-source').textContent=''; controls(false);
    $('#ssid-network').replaceChildren(new Option('Selecciona una red','')); $('#ssid-profile').replaceChildren(new Option('Selecciona un perfil',''));
    if(!scope.value) return; const context = capture(); controls(true);
    try {
      const result = await request(`/wifi-scopes/${Number(scope.value)}/options`); if(!current(context)) return; options = result;
      $('#ssid-source').textContent = result.simulated ? 'SIMULACIÓN: inventario de demostración; no es infraestructura real.' : 'Inventario consultado en UniFi y OPNsense.';
      $('#ssid-network').replaceChildren(new Option('Selecciona una red',''),...result.networks.map(n=>new Option(`${n.parent_interface} · VLAN ${n.tag}`,n.id)));
      $('#ssid-profile').replaceChildren(new Option('Selecciona un perfil',''),...result.security_profiles.map(p=>new Option(p,p)));
      for(const ap of result.aps) { const label=document.createElement('label'), check=document.createElement('input');check.type='checkbox';label.append(check,textNode('span',ap.name));$('#ssid-aps').append(label);aps.push({id:ap.id,check}); }
    } catch(error) { if(current(context)) $('#ssid-status').textContent = error.message; }
    finally { if(current(context)) {controls(false);await refresh();} }
  });
  function common() {
    const ap_ids = aps.filter(a=>a.check.checked).map(a=>a.id);
    if(!options || !ap_ids.length || !$('#ssid-profile').value) throw new Error('Selecciona un ámbito, al menos un AP y un perfil de seguridad.');
    return {scope_id:Number(scope.value),ap_ids,security_profile:$('#ssid-profile').value};
  }
  async function prepare(csv) {
    if(busy) return; const context=capture();
    try {
      const payload = common();
      if(csv) {
        const file=$('#ssid-csv').files?.[0]; if(!file || file.size>1048576) throw new Error('Selecciona un CSV de hasta 1 MiB.');
        payload.csv_text=await file.text(); if(!current(context)) return;
      } else {
        Object.assign(payload,{ssid:$('#ssid-name').value.trim(),network_id:$('#ssid-network').value,purpose:$('#ssid-purpose').value.trim()});
        if(!payload.ssid || !payload.network_id || !payload.purpose) throw new Error('Completa SSID, red/VLAN y motivo.');
      }
      controls(true);
      const plan=await request(csv?'/ssid-plans/csv':'/ssid-plans',{method:'POST',body:JSON.stringify(payload)});
      if(current(context)) {showPlan(plan);$('#ssid-status').textContent='Propuesta preparada. Revisa y selecciona las filas para confirmar.';}
    } catch(error) {if(current(context)) $('#ssid-status').textContent=error.status===422?'Revisa los campos y el tamaño UTF-8 del SSID.':error.message;}
    finally {if(current(context)) controls(false);}
  }
  $('#ssid-form').addEventListener('submit',event=>{event.preventDefault();return prepare(false);});
  $('#ssid-upload').addEventListener('click',()=>prepare(true)); $('#ssid-refresh').addEventListener('click',refresh);
  function renderProposal(proposal) {
    const context=captureChat(), card=document.createElement('article');card.className='reservation-card';
    card.append(textNode('p',`Propuesta SSID: ${proposal.ssid}. AP: ${proposal.ap_ids.join(', ')}. VLAN/red: ${proposal.network_id}. Perfil: ${proposal.security_profile}.`));
    const button=textNode('button','Preparar revisión en el panel');button.type='button';
    button.addEventListener('click',async()=>{
      if(!isChatCurrent(context)||button.disabled) return;button.disabled=true;
      try {const plan=await request('/ssid-plans',{method:'POST',body:JSON.stringify(proposal)});if(!isChatCurrent(context)) return;showPlan(plan);panel.scrollIntoView?.({behavior:'smooth',block:'start'});}
      catch(error) {if(isChatCurrent(context)) {card.append(textNode('p',error.message));button.disabled=false;}}
    });card.append(button);chatMessages.append(card);
  }
  return {reset,configureUser,renderProposal,refresh};
}
