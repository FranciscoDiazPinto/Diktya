// Cambio de VLAN y reinicio de equipos: propuesta, confirmación explícita y seguimiento.
// Confirmar registra la aprobación; la ejecución, verificación y recuperación son del worker.
const STATUS = {
  preview: 'Pendiente de tu confirmación', expired: 'Vencida · prepara otra propuesta', confirmed: 'Aprobada · esperando al ejecutor',
  rejected: 'Rechazada antes de ejecutar · prepara otra propuesta',
  executing: 'En ejecución', completed: 'Verificada', failed: 'Fallida · revisa el resultado',
  unverified: 'Equipo en línea · reinicio no acreditado',
  rolled_back: 'No verificada · se restauró el estado anterior', rollback_failed: 'No se pudo restaurar · requiere conciliación',
  uncertain: 'Resultado incierto · requiere conciliación', cancelled: 'Cancelada',
};
const RESULT = {
  verified_configuration: 'Configuración releída y verificada en el controlador. No equivale a una prueba de conexión.',
  returned_online: 'El equipo volvió en línea después del reinicio.',
  online_restart_unconfirmed: 'El equipo está en línea, pero no se pudo acreditar que se reinició.',
  reconciled_online_restart_unconfirmed: 'Conciliación: equipo en línea. No se pudo acreditar el reinicio; se liberó el bloqueo sin repetir la orden.',
  reconciled_restart_verified: 'Conciliación: reinicio acreditado por un uptime menor y equipo en línea.',
  did_not_return: 'El equipo no volvió en línea dentro del tiempo máximo. Se abrió un ticket.',
  not_sent: 'La orden no se envió: el equipo no fue reiniciado.',
  restart_unconfirmed: 'No se pudo confirmar si el equipo recibió la orden.',
};

export function createChangePlans({document, Option, state, api, textNode, captureChat, isChatCurrent, chatMessages, onOpenPlans = () => {}}) {
  const $ = id => document.querySelector('#' + id);
  const panel = $('changes-panel'), scope = $('changes-scope'), list = $('changes-plan-list'), status = $('changes-status');
  let generation = 0, admin = false, loaded = false;
  const capture = () => ({session: state.session, generation});
  const current = c => c.session === state.session && c.generation === generation;
  const request = (path, extra = {}) => api.authedRequest(`/api/v1/changes${path}`, extra);
  const post = (path, body) => request(path, {method: 'POST', ...(body ? {body: JSON.stringify(body)} : {})});
  const placeholder = (select, label) => select.replaceChildren(new Option(label, ''));

  const batchBase = '/ssid-vlan-batches';
  const batchAdd = $('vlan-batch-add'), batchPreview = $('vlan-batch-preview');
  const batchDraft = $('vlan-batch-draft'), batchHistory = $('vlan-batch-history'), batchDetail = $('vlan-batch-detail');
  let draftRows = [], batchBusy = false, canApprove = false, selectedBatch = null;

  function reviewDraft() {
    batchDraft.replaceChildren();
    for (const row of draftRows) {
      const item = textNode('li', `${row.label} · ${row.purpose}`);
      const remove = textNode('button', `Quitar ${row.label}`);
      remove.type = 'button';
      remove.addEventListener('click', () => {
        if (batchBusy) return;
        draftRows = draftRows.filter(current => current !== row);
        reviewDraft();
        batchAdd.focus();
      });
      item.append(remove);
      batchDraft.append(item);
    }
    batchPreview.disabled = !loaded || batchBusy || !draftRows.length;
  }

  function showBatch(batch) {
    selectedBatch = batch.id;
    batchDetail.replaceChildren();
    const title = textNode('h4', `Lote ${batch.id} · ${STATUS[batch.status] || batch.status}`);
    title.tabIndex = -1;
    batchDetail.append(title);
    const selected = new Set();
    const results = new Map(batch.results.map(result => [result.row_number, result]));
    const reviewable = batch.status === 'preview' && new Date(batch.expires_at).getTime() > Date.now();
    const confirm = textNode('button', 'Confirmar filas del lote');
    confirm.type = 'button';
    confirm.disabled = true;
    const rows = document.createElement('ol');
    for (const row of batch.rows) {
      const item = document.createElement('li');
      const result = results.get(row.row_number);
      const text = row.errors.length ? row.errors.join(' ') :
        `${row.ssid} → VLAN ${row.target_vlan}. ${row.impact}`;
      const label = `Fila ${row.row_number}: ${text}`;
      if (reviewable && canApprove && !row.errors.length) {
        const check = document.createElement('input');
        check.type = 'checkbox';
        const wrapper = document.createElement('label');
        wrapper.append(check, textNode('span', label));
        check.addEventListener('change', () => {
          if (check.checked) selected.add(row.row_number);
          else selected.delete(row.row_number);
          confirm.disabled = !selected.size;
        });
        item.append(wrapper);
      } else {
        item.append(textNode('p', result ? `${label} · ${STATUS[result.status] || result.status}` : label));
      }
      rows.append(item);
    }
    batchDetail.append(rows);
    if (reviewable && canApprove) {
      confirm.addEventListener('click', () => batchAction(
        () => post(`${batchBase}/${batch.id}/confirm`, {revision: batch.revision, row_numbers: [...selected]}),
        'Aprobación registrada. Actualiza el estado para consultar la ejecución.',
      ));
      batchDetail.append(confirm);
    }
    if (batch.can_retry) {
      const retry = textNode('button', 'Retomar cambios pendientes');
      retry.type = 'button';
      retry.addEventListener('click', () => batchAction(() => post(`${batchBase}/${batch.id}/retry`),
        'Lote preparado desde la primera fila pendiente. Revisa y confirma para continuar.'));
      batchDetail.append(retry);
    }
    return title;
  }

  async function loadBatchHistory(context) {
    if (!scope.value) return;
    const batches = await request(`${batchBase}?scope_id=${Number(scope.value)}`);
    if (!current(context)) return;
    batchHistory.replaceChildren(new Option('Selecciona un lote', ''), ...batches.map(batch =>
      new Option(`${batch.id} · ${STATUS[batch.status] || batch.status} · ${batch.row_count} fila(s)`, batch.id)));
    batchHistory.value = batches.some(batch => batch.id === selectedBatch) ? selectedBatch : '';
    batchHistory.disabled = !batches.length;
  }

  async function batchAction(run, message, {clearDraft = false} = {}) {
    if (batchBusy || !scope.value) return;
    const context = capture();
    batchBusy = true;
    try {
      const batch = await run();
      if (!current(context)) return;
      if (clearDraft) draftRows = [];
      const title = showBatch(batch);
      status.textContent = message;
      title.focus();
      await loadBatchHistory(context);
    } catch (error) {
      if (current(context)) status.textContent = error.message;
    } finally {
      if (current(context)) { batchBusy = false; reviewDraft(); }
    }
  }

  batchAdd.addEventListener('click', () => {
    if (!loaded || batchBusy) return;
    const ssid = $('vlan-change-ssid'), network = $('vlan-change-network');
    const purpose = $('vlan-change-purpose').value.trim();
    if (!ssid.value || !network.value || !purpose) {
      status.textContent = 'Selecciona SSID, red destino y escribe el motivo.';
      return;
    }
    if (draftRows.length >= 50 || draftRows.some(row => row.broadcast_id === ssid.value)) {
      status.textContent = 'El lote admite hasta 50 SSID distintos.';
      return;
    }
    const label = `${ssid.selectedOptions[0].text} → ${network.selectedOptions[0].text}`;
    draftRows.push({broadcast_id: ssid.value, network_id: network.value, purpose, label});
    reviewDraft();
    status.textContent = 'Cambio agregado al lote.';
  });
  batchPreview.addEventListener('click', () => batchAction(() => post(`${batchBase}/preview`, {
    scope_id: Number(scope.value),
    rows: draftRows.map(({label, ...row}) => row),
  }), 'Lote preparado. Revisa las filas antes de confirmar.', {clearDraft: true}));
  batchHistory.addEventListener('change', () => {
    if (batchHistory.value) {
      return batchAction(() => request(`${batchBase}/${batchHistory.value}`), 'Lote recuperado.');
    }
    selectedBatch = null;
    batchDetail.replaceChildren();
  });

  function clearOptions() {
    loaded = false; draftRows = []; batchBusy = false; selectedBatch = null;
    batchAdd.disabled = true; batchHistory.disabled = true;
    placeholder(batchHistory, 'Selecciona un lote'); batchDetail.replaceChildren(); reviewDraft();
    placeholder($('vlan-change-ssid'), 'Selecciona un SSID'); placeholder($('vlan-change-network'), 'Selecciona la red destino');
    placeholder($('restart-device'), 'Selecciona un AP');
    $('vlan-change-prepare').disabled = $('restart-prepare').disabled = true; $('changes-source').textContent = '';
  }
  function reset() {
    generation += 1; admin = false; panel.hidden = true; clearOptions();
    placeholder(scope, 'Selecciona un ámbito'); list.replaceChildren(); status.textContent = '';
    for (const id of ['vlan-change-purpose', 'restart-purpose', 'restart-device-id']) $(id).value = '';
    $('restart-device-id-field').hidden = true;
  }

  function card(kind, plan) {
    const context = capture(), node = document.createElement('article'); node.className = 'reservation-card';
    const vlan = kind === 'vlan', base = vlan ? '/ssid-vlan-change-plans' : '/device-restart-plans';
    node.append(textNode('strong', vlan
      ? `Cambio de VLAN · «${plan.ssid}» · ${STATUS[plan.status] || plan.status}`
      : `Reinicio · ${plan.device_name} · ${STATUS[plan.status] || plan.status}`));
    node.append(textNode('p', vlan
      ? `Red actual: ${plan.current_network_id}${plan.current_vlan ? ` (VLAN ${plan.current_vlan})` : ''} → red destino: ${plan.target_network_id}${plan.target_vlan ? ` (VLAN ${plan.target_vlan})` : ''}.`
      : `Equipo ${plan.device_id}${plan.access_point ? '' : ' · equipo crítico o no clasificado'}.`));
    if (plan.impact) node.append(textNode('p', `Impacto estimado: ${plan.impact}`));
    node.append(textNode('p', `Motivo: ${plan.purpose}`));
    const feedback = textNode('p', ''); feedback.setAttribute?.('role', 'status');
    const actions = [];
    const action = (label, run) => {
      const button = textNode('button', label); button.type = 'button';
      button.addEventListener('click', async () => {
        if (!current(context) || button.disabled) return;
        for (const item of actions) item.disabled = true;
        try { const result = await run(); if (current(context)) { feedback.textContent = result; await refresh(); } }
        catch (error) { if (current(context)) { feedback.textContent = error.message; for (const item of actions) item.disabled = false; } }
      });
      actions.push(button); return button;
    };
    if (plan.status === 'preview') {
      node.append(textNode('p', `Vence: ${new Date(plan.expires_at).toLocaleString('es-CL')}. Sin tu confirmación no se ejecuta nada.`));
      node.append(action(vlan ? 'Confirmar cambio de VLAN' : 'Confirmar reinicio', async () => {
        await post(`${base}/${plan.id}/confirm`, {revision: plan.revision});
        return 'Aprobación registrada. El ejecutor aplicará y verificará el cambio; actualiza para ver el resultado.';
      }));
    }
    if (['preview', 'confirmed'].includes(plan.status))
      node.append(action('Cancelar', async () => { await post(`${base}/${plan.id}/cancel`); return 'Cancelado. No se modificó la red.'; }));
    for (const result of plan.execution_results || []) node.append(textNode('p', RESULT[result.status] || `Resultado: ${result.status}`));
    if (plan.needs_reconciliation) {
      node.append(textNode('p', 'El recurso queda bloqueado y no se reintenta automáticamente. Un administrador debe conciliarlo con el controlador.'));
      if (admin) node.append(action('Conciliar leyendo el controlador', async () => {
        const result = await post(`/reconcile/${kind}/${plan.id}`);
        return `Conciliado: ${STATUS[result.status] || result.status}.`;
      }));
    }
    node.append(feedback); return node;
  }

  async function refresh() {
    const context = capture();
    try {
      const [vlans, restarts] = await Promise.all([request('/ssid-vlan-change-plans'), request('/device-restart-plans')]);
      if (!current(context)) return;
      list.replaceChildren(...vlans.map(p => card('vlan', p)), ...restarts.map(p => card('restart', p)));
      if (!vlans.length && !restarts.length) list.append(textNode('p', 'Todavía no has preparado cambios de VLAN ni reinicios.', 'empty-state'));
    } catch (error) { if (current(context)) status.textContent = error.message; }
  }

  async function configureUser(user) {
    const permissions = user.permissions || [];
    if (!permissions.includes('changes:request')) return;
    admin = permissions.includes('networks:manage');
    canApprove = permissions.includes('changes:approve');
    panel.hidden = false; $('restart-device-id-field').hidden = !admin;
    const context = capture();
    try {
      const scopes = await request('/wifi-scopes'); if (!current(context)) return;
      scope.replaceChildren(new Option('Selecciona un ámbito', ''), ...scopes.map(s => new Option(s.name, s.id)));
      status.textContent = scopes.length ? '' : 'No tienes ámbitos de aprovisionamiento asignados.';
      await refresh();
    } catch (error) { if (current(context)) status.textContent = error.message; }
  }

  async function loadScope() {
    generation += 1; clearOptions();
    if (!scope.value) return;
    const context = capture(), id = Number(scope.value);
    status.textContent = 'Consultando inventario autorizado…';
    try {
      const options = await request(`/wifi-scopes/${id}/options`); if (!current(context)) return;
      $('changes-source').textContent = options.simulated
        ? 'SIMULACIÓN: inventario de demostración. Los cambios reales requieren el inventario del controlador.'
        : 'Inventario consultado en UniFi y OPNsense.';
      $('vlan-change-network').replaceChildren(new Option('Selecciona la red destino', ''),
        ...options.networks.map(n => new Option(`${n.parent_interface} · VLAN ${n.tag}`, n.id)));
      $('restart-device').replaceChildren(new Option('Selecciona un AP', ''), ...options.aps.map(a => new Option(a.name, a.id)));
      const ssids = await request(`/wifi-scopes/${id}/ssids`); if (!current(context)) return;
      $('vlan-change-ssid').replaceChildren(new Option('Selecciona un SSID', ''), ...ssids.map(s => new Option(s.ssid, s.id)));
      loaded = options.accepts_changes !== false;
      batchAdd.disabled = $('vlan-change-prepare').disabled = $('restart-prepare').disabled = !loaded;
      status.textContent = loaded ? '' : 'Este ámbito ya no acepta cambios.';
    } catch (error) { if (current(context)) status.textContent = error.message; }
    finally {
      if (current(context)) {
        await refresh();
        if (current(context)) {
          try { await loadBatchHistory(context); }
          catch (error) { if (current(context)) status.textContent = error.message; }
        }
      }
    }
  }
  scope.addEventListener('change', loadScope);

  async function prepare(path, payload, button) {
    const context = capture(); button.disabled = true; status.textContent = 'Preparando propuesta…';
    try {
      await post(path, payload); if (!current(context)) return;
      status.textContent = 'Propuesta preparada. Revisa el impacto y confírmala para que se ejecute.';
      await refresh();
    } catch (error) { if (current(context)) status.textContent = error.status === 422 ? 'Revisa los campos de la propuesta.' : error.message; }
    finally { if (current(context)) button.disabled = !loaded; }
  }
  $('vlan-change-form').addEventListener('submit', event => {
    event.preventDefault?.();
    const payload = {scope_id: Number(scope.value), broadcast_id: $('vlan-change-ssid').value,
      network_id: $('vlan-change-network').value, purpose: $('vlan-change-purpose').value.trim()};
    if (!loaded || !payload.broadcast_id || !payload.network_id || !payload.purpose) { status.textContent = 'Selecciona SSID, red destino y escribe el motivo.'; return; }
    return prepare('/ssid-vlan-change-plans', payload, $('vlan-change-prepare'));
  });
  $('restart-form').addEventListener('submit', event => {
    event.preventDefault?.();
    const manual = admin ? $('restart-device-id').value.trim() : '';
    const payload = {scope_id: Number(scope.value), device_id: manual || $('restart-device').value, purpose: $('restart-purpose').value.trim()};
    if (!loaded || !payload.device_id || !payload.purpose) { status.textContent = 'Selecciona el equipo y escribe el motivo.'; return; }
    return prepare('/device-restart-plans', payload, $('restart-prepare'));
  });
  $('changes-refresh').addEventListener('click', async () => {
    await refresh();
    if (selectedBatch) await batchAction(() => request(`${batchBase}/${selectedBatch}`), 'Estado del lote actualizado.');
    else {
      const context = capture();
      try { await loadBatchHistory(context); }
      catch (error) { if (current(context)) status.textContent = error.message; }
    }
  });

  // El chat solo propone: el plan se crea aquí, tras una acción explícita del usuario.
  function proposalCard(text, path, proposal) {
    const context = captureChat(), node = document.createElement('article'); node.className = 'reservation-card';
    node.append(textNode('p', text));
    const button = textNode('button', 'Preparar revisión en el panel'); button.type = 'button';
    button.addEventListener('click', async () => {
      if (!isChatCurrent(context) || button.disabled) return; button.disabled = true;
      try { await post(path, proposal); if (!isChatCurrent(context)) return; await refresh(); onOpenPlans(); }
      catch (error) { if (isChatCurrent(context)) { node.append(textNode('p', error.message)); button.disabled = false; } }
    });
    node.append(button); chatMessages.append(node);
  }
  const renderVlanProposal = p => proposalCard(`Propuesta de cambio de VLAN: SSID ${p.broadcast_id} → red ${p.network_id}. Motivo: ${p.purpose}`, '/ssid-vlan-change-plans', p);
  const renderRestartProposal = p => proposalCard(`Propuesta de reinicio del equipo ${p.device_id}. Motivo: ${p.purpose}`, '/device-restart-plans', p);

  return {reset, configureUser, refresh, renderVlanProposal, renderRestartProposal};
}
