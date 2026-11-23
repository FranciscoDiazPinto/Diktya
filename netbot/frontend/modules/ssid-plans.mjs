// Propuestas y confirmación por API; ninguna escritura de red desde el LLM.
export function createSsidPlans({document, Option, state, api, textNode, captureChat, isChatCurrent, chatMessages, onOpenPlans = () => {}, onScopeCreated = () => {}}) {
  const $ = s => document.querySelector(s), panel = $('#ssid-panel'), scope = $('#ssid-scope');
  let generation = 0, options = null, aps = [], busy = false;
  const capture = () => ({session:state.session,generation});
  const current = c => c.session === state.session && c.generation === generation;
  const request = (path, extra = {}) => api.authedRequest(`/api/v1/changes${path}`,extra);
  const closure = $('#fair-closure');
  const previewButton = $('#fair-closure-preview');
  const confirmButton = $('#fair-closure-confirm');
  const summary = $('#fair-closure-summary');
  const successorForm = $('#fair-successor');
  const successorUsers = $('#fair-successor-users');
  let closurePreview = null;
  let closed = false;

  function clearClosure() {
    closurePreview = null;
    summary.replaceChildren();
    confirmButton.hidden = true;
    successorForm.hidden = true;
    $('#fair-successor-assignees').hidden = true;
    successorUsers.replaceChildren();
    $('#fair-successor-name').value = '';
    $('#fair-successor-event').value = '';
  }

  function showClosure(result) {
    clearClosure();
    closurePreview = result;
    closed = !result.accepts_changes;
    summary.append(textNode('p', `${result.event_name} · ${closed ? 'Cambios bloqueados' : 'Acepta cambios'}`));
    const kinds = {ssid: 'Alta de SSID', vlan: 'Cambio de VLAN', vlan_batch: 'Lote de cambios de VLAN', restart: 'Reinicio'};
    const groups = [
      ['Planes que se cancelarán', result.pending.map(plan => `${kinds[plan.kind]} · ${plan.id} · ${plan.status}`)],
      ['Trabajos activos o por conciliar', result.blockers.map(plan => `${kinds[plan.kind]} · ${plan.id} · ${plan.status}`)],
      ['Resultados para revisión', result.review.map(plan => `${kinds[plan.kind]} · ${plan.id} · ${plan.status}`)],
      ['Reservas vinculadas', result.linked_reservations.map(row =>
        `Reserva ${row.id} · ${row.releasable ? 'Se liberará al confirmar' : 'Se conserva'}`)],
    ];
    for (const [label, items] of groups) {
      summary.append(textNode('h4', label));
      if (!items.length) {
        summary.append(textNode('p', 'Ninguno.'));
        continue;
      }
      const list = document.createElement('ul');
      list.append(...items.map(item => textNode('li', item)));
      summary.append(list);
    }
    confirmButton.hidden = closed && !result.linked_reservations.some(row => row.releasable);
    confirmButton.textContent = closed ? 'Confirmar liberación de reservas' : 'Confirmar cierre del ámbito';
    successorForm.hidden = !closed || !confirmButton.hidden || result.pending.length > 0 || result.blockers.length > 0;
    if (!successorForm.hidden) {
      successorForm.action = `/api/v1/changes/wifi-scopes/${Number(scope.value)}/successor`;
    }
  }

  async function loadSuccessorUsers(context, result) {
    if (successorForm.hidden || !state.user?.permissions?.includes('users:read')) return;
    try {
      const users = await api.authedRequest('/admin/users', {});
      if (!current(context) || closurePreview !== result || !Array.isArray(users)) return;
      for (const user of users) {
        if (!user.is_active || !user.permissions?.includes('changes:request')) continue;
        const option = document.createElement('input');
        option.type = 'checkbox';
        option.name = 'user_ids';
        option.value = String(user.id);
        const label = document.createElement('label');
        label.append(option, textNode('span', user.full_name ? `${user.full_name} · ${user.email}` : user.email));
        successorUsers.append(label);
      }
      $('#fair-successor-assignees').hidden = !successorUsers.children.length;
    } catch {
      if (current(context) && closurePreview === result) {
        $('#ssid-status').textContent = 'No se pudo cargar el personal autorizado. Puedes volver a revisar el cierre.';
      }
    }
  }

  successorForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || successorForm.hidden || !closurePreview || !scope.value) return;
    const name = $('#fair-successor-name');
    const eventName = $('#fair-successor-event');
    const invalid = [name, eventName].find(field => !field.value.trim());
    if (invalid) {
      $('#ssid-status').textContent = 'Completa el nombre del ámbito y del evento.';
      invalid.focus();
      return;
    }
    const context = capture();
    const data = {
      name: name.value.trim(), event_name: eventName.value.trim(), revision: closurePreview.revision,
      user_ids: [...successorUsers.querySelectorAll('input:checked')].map(input => Number(input.value)),
    };
    controls(true);
    try {
      const result = await request(`/wifi-scopes/${Number(scope.value)}/successor`, {
        method: 'POST', body: JSON.stringify(data),
      });
      if (!current(context)) return;
      scope.append(new Option(result.name, result.id));
      onScopeCreated(result);
      clearClosure();
      $('#ssid-status').textContent = `Ámbito «${result.name}» creado. Selecciónalo para preparar cambios.`;
      controls(false);
      scope.focus();
    } catch (error) {
      if (current(context)) $('#ssid-status').textContent = error.message;
    } finally {
      if (current(context)) controls(false);
    }
  });

  async function reviewClosure(confirm) {
    if (busy || !scope.value || closure.hidden || (confirm && !closurePreview)) return;
    const context = capture();
    const endpoint = `/wifi-scopes/${Number(scope.value)}/closure-`;
    const approval = confirm ? {method: 'POST', body: JSON.stringify({revision: closurePreview.revision})} : {};
    clearClosure();
    controls(true);
    try {
      const result = await request(endpoint + (confirm ? 'confirm' : 'preview'), approval);
      if (!current(context)) return;
      showClosure(result);
      $('#ssid-status').textContent = confirm
        ? result.blockers.length
          ? 'Cambios bloqueados. Quedan trabajos activos o pendientes de conciliación.'
          : 'Cambios bloqueados para esta feria.'
        : 'Vista previa disponible. Revisa los planes y las reservas antes de confirmar.';
      if (confirm) await refresh();
      if (current(context)) await loadSuccessorUsers(context, result);
    } catch (error) {
      if (current(context)) $('#ssid-status').textContent = error.message;
    } finally {
      if (current(context)) {
        controls(false);
        if (confirm) previewButton.focus();
      }
    }
  }

  previewButton.addEventListener('click', () => reviewClosure(false));
  confirmButton.addEventListener('click', () => reviewClosure(true));

  function controls(value) {
    busy = value; scope.disabled = value;
    $('#ssid-prepare').disabled = value || !options || closed;
    $('#ssid-upload').disabled = value || !options || closed;
    previewButton.disabled = value || !scope.value;
    confirmButton.disabled = value;
    $('#fair-successor-submit').disabled = value;
  }
  function reset() {
    generation += 1; options = null; aps = []; panel.hidden = true;
    closed = false; closure.hidden = true; clearClosure();
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
    if (['partial', 'failed'].includes(plan.status) && plan.execution_results?.length) {
      const retry = textNode('button', 'Retomar filas pendientes');
      retry.type = 'button';
      retry.addEventListener('click', async () => {
        if (!current(context) || retry.disabled) return;
        retry.disabled = true;
        try {
          const resumed = await request(`/ssid-plans/${plan.id}/retry`, {method: 'POST'});
          if (!current(context)) return;
          const previewCard = showPlan(resumed);
          $('#ssid-status').textContent = 'Propuesta preparada con las filas pendientes. Revisa y confirma para continuar.';
          previewCard.tabIndex = -1;
          previewCard.focus();
        } catch (error) {
          if (!current(context)) return;
          $('#ssid-status').textContent = error.message;
          retry.disabled = false;
          retry.focus();
        }
      });
      card.append(retry);
    }
    $('#ssid-plan-list').append(card);
    return card;
  }
  async function refresh() {
    const context = capture();
    try { const plans = await request('/ssid-plans'); if (!current(context)) return; $('#ssid-plan-list').replaceChildren(); for(const p of plans) showPlan(p); }
    catch(error) { if(current(context)) $('#ssid-status').textContent = error.message; }
  }
  async function configureUser(user) {
    if(!user.permissions?.includes('changes:request')) return;
    panel.hidden = false;
    closure.hidden = !user.permissions.includes('networks:manage');
    const context = capture();
    try {
      const scopes = await request('/wifi-scopes'); if(!current(context)) return;
      scope.replaceChildren(new Option('Selecciona un ámbito',''),...scopes.map(s => new Option(s.name,s.id)));
      $('#ssid-status').textContent = scopes.length ? 'Selecciona un ámbito para consultar AP y VLAN autorizados.' : 'No tienes ámbitos de aprovisionamiento asignados. Un administrador debe configurarlos.';
      await refresh();
    } catch(error) { if(current(context)) $('#ssid-status').textContent = error.message; }
  }
  scope.addEventListener('change',async () => {
    closed = false; clearClosure();
    generation += 1; options = null; aps = []; $('#ssid-aps').replaceChildren(); $('#ssid-source').textContent=''; controls(false);
    $('#ssid-network').replaceChildren(new Option('Selecciona una red','')); $('#ssid-profile').replaceChildren(new Option('Selecciona un perfil',''));
    if(!scope.value) return; const context = capture(); controls(true);
    try {
      const result = await request(`/wifi-scopes/${Number(scope.value)}/options`); if(!current(context)) return; options = result;
      closed = result.accepts_changes === false;
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
  function workbookBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
      reader.onerror = () => reject(new Error('No se pudo leer el Excel.'));
      reader.readAsDataURL(file);
    });
  }
  async function prepare(upload) {
    if(busy || closed) return; const context=capture();
    try {
      const payload = common();
      let path = '/ssid-plans';
      if (upload) {
        const file = $('#ssid-csv').files?.[0];
        const extension = file?.name.split('.').at(-1).toLowerCase();
        if (!file || !['csv', 'xlsx'].includes(extension) || !file.size || file.size > 1048576)
          throw new Error('Selecciona un archivo CSV o XLSX de hasta 1 MiB.');
        controls(true);
        path += '/' + extension;
        if (extension === 'xlsx') payload.xlsx_base64 = await workbookBase64(file);
        else payload.csv_text = await file.text();
        if (!current(context)) return;
      } else {
        Object.assign(payload,{ssid:$('#ssid-name').value.trim(),network_id:$('#ssid-network').value,purpose:$('#ssid-purpose').value.trim()});
        if(!payload.ssid || !payload.network_id || !payload.purpose) throw new Error('Completa SSID, red/VLAN y motivo.');
      }
      controls(true);
      const plan=await request(path,{method:'POST',body:JSON.stringify(payload)});
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
      try {const plan=await request('/ssid-plans',{method:'POST',body:JSON.stringify(proposal)});if(!isChatCurrent(context)) return;showPlan(plan);onOpenPlans();}
      catch(error) {if(isChatCurrent(context)) {card.append(textNode('p',error.message));button.disabled=false;}}
    });card.append(button);chatMessages.append(card);
  }
  return {reset,configureUser,renderProposal,refresh};
}
