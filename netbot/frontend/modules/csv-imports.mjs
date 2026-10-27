// El CSV viaja como archivo a la API; nunca se incorpora a mensajes del LLM.
export function createCsvImports({ document, Option, state, api, textNode, onConfirmed }) {
  const $ = (selector) => document.querySelector(selector);
  const panel = $('#csv-panel'), form = $('#csv-form'), fileInput = $('#csv-file');
  const history = $('#csv-history'), status = $('#csv-status'), preview = $('#csv-preview');
  const rowsHost = $('#csv-rows'), selectAll = $('#csv-select-all');
  const confirm = $('#csv-confirm'), cancel = $('#csv-cancel'), upload = $('#csv-upload');
  let generation = 0, batch = null, selected = new Set(), rowControls = [];
  let busy = false, blocked = false;
  let limits = { max_bytes: 1048576, max_rows: 500, ttl_seconds: 900 };
  const capture = () => ({ session: state.session, generation });
  const current = (context) => context.session === state.session && context.generation === generation;

  function updateControls() {
    upload.disabled = fileInput.disabled = history.disabled = busy;
    const selectable = batch?.status === 'preview' && !blocked;
    confirm.disabled = busy || !selectable || selected.size === 0;
    cancel.disabled = busy || batch?.status !== 'preview';
    for (const { input, valid } of rowControls) input.disabled = busy || !selectable || !valid;
    selectAll.disabled = busy || !selectable || !rowControls.some((r) => r.valid);
    selectAll.checked = !!selected.size && rowControls.filter((r) => r.valid).every((r) => selected.has(r.number));
    $('#csv-selection').textContent = `${selected.size} fila(s) seleccionada(s). Solo se guardarán las seleccionadas al confirmar.`;
  }

  function reset() {
    generation += 1;
    batch = null; selected = new Set(); rowControls = []; busy = blocked = false;
    fileInput.value = ''; history.replaceChildren(new Option('Selecciona una carga', ''));
    preview.hidden = true; rowsHost.replaceChildren(); $('#csv-results').replaceChildren();
    status.textContent = ''; updateControls();
  }

  function remember(data) {
    let option = [...history.children].find((node) => node.value === data.id);
    if (!option) { option = new Option('', data.id); history.append(option); }
    option.textContent = `${data.filename} · ${data.status}`;
    history.value = data.id;
  }

  function render(data) {
    batch = data; blocked = false;
    const confirmedRows = new Set(data.results.map((r) => r.row_number));
    selected = new Set(data.rows.filter((r) => data.status === 'confirmed' ? confirmedRows.has(r.row_number) : data.status === 'preview' && r.data && !r.errors.length).map((r) => r.row_number));
    rowControls = []; rowsHost.replaceChildren(); preview.hidden = false; remember(data);
    $('#csv-summary').textContent = `${data.filename}: ${data.valid_count} válidas, ${data.invalid_count} con errores. ${data.simulated ? 'Inventario SIMULADO' : 'Inventario ' + data.source}. Estado: ${data.status}. Vence: ${new Date(data.expires_at).toLocaleString('es-CL')}.`;
    const context = capture();
    for (const row of data.rows) {
      const tr = document.createElement('tr');
      const cell = document.createElement('td'), input = document.createElement('input');
      input.type = 'checkbox'; input.checked = selected.has(row.row_number);
      input.setAttribute('aria-label', `Seleccionar fila ${row.row_number}`);
      const valid = !!row.data && !row.errors.length;
      input.addEventListener('change', () => {
        if (!current(context) || !valid || batch.status !== 'preview' || blocked) return;
        if (input.checked) selected.add(row.row_number); else selected.delete(row.row_number);
        updateControls();
      });
      rowControls.push({ input, valid, number: row.row_number }); cell.append(input); tr.append(cell);
      for (const value of [row.row_number, row.data?.parent_interface ?? '—', row.data?.tag ?? '—', row.data?.ssid ?? '—', row.data?.event_name ?? '—', row.data?.purpose ?? '—', row.errors.length ? row.errors.join(' ') : 'Válida']) tr.append(textNode('td', String(value)));
      rowsHost.append(tr);
    }
    $('#csv-results').replaceChildren();
    if (data.status === 'confirmed') {
      $('#csv-results').append(textNode('p', `${data.results.length} reserva(s) confirmada(s). No se modificó la infraestructura.`));
      for (const result of data.results) $('#csv-results').append(textNode('p', `Fila ${result.row_number}: reserva #${result.reservation.id}, VLAN ${result.reservation.tag} · ${result.reservation.status}.`));
    }
    updateControls();
  }

  async function load(id) {
    generation += 1;
    const context = capture(); busy = true; updateControls();
    try {
      const data = await api.authedRequest(`/api/v1/changes/csv-imports/${id}`);
      if (current(context)) { render(data); status.textContent = 'Carga recuperada.'; }
    } catch (error) {
      if (current(context)) { batch = null; selected.clear(); preview.hidden = true; status.textContent = error.message; }
    } finally {
      if (current(context)) { busy = false; updateControls(); }
    }
  }

  async function configureUser(user) {
    panel.hidden = !user.permissions?.includes('vlan:reserve');
    if (panel.hidden) return;
    const context = capture(); busy = true; updateControls();
    try {
      const [options, imports] = await Promise.all([api.authedRequest('/api/v1/changes/csv-imports/options'), api.authedRequest('/api/v1/changes/csv-imports')]);
      if (!current(context)) return;
      limits = options;
      $('#csv-limits').textContent = `UTF-8, coma o punto y coma. Máximo ${Math.floor(limits.max_bytes / 1024)} KiB y ${limits.max_rows} filas. Sin contraseñas.`;
      history.replaceChildren(new Option('Selecciona una carga', ''), ...imports.map((item) => new Option(`${item.filename} · ${item.status}`, item.id)));
      if (imports.length) await load(imports[0].id);
    } catch (error) { if (current(context)) status.textContent = error.message; }
    finally { if (current(context)) { busy = false; updateControls(); } }
  }

  fileInput.addEventListener('change', () => {
    generation += 1; batch = null; selected.clear(); blocked = false; preview.hidden = true;
    history.value = ''; status.textContent = 'Pulsa Validar CSV para revisar el archivo.'; updateControls();
  });
  history.addEventListener('change', () => {
    fileInput.value = '';
    if (history.value) load(history.value);
    else { generation += 1; batch = null; selected.clear(); preview.hidden = true; updateControls(); }
  });
  selectAll.addEventListener('change', () => {
    if (busy || blocked || batch?.status !== 'preview') return;
    selected = new Set(selectAll.checked ? rowControls.filter((r) => r.valid).map((r) => r.number) : []);
    for (const row of rowControls) row.input.checked = selected.has(row.number);
    updateControls();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (busy) return;
    const file = fileInput.files?.[0];
    if (!file || !file.name.toLowerCase().endsWith('.csv') || !file.size) { status.textContent = 'Selecciona un archivo CSV no vacío.'; return; }
    if (file.size > limits.max_bytes) { status.textContent = 'El archivo supera el tamaño máximo permitido.'; return; }
    generation += 1; const context = capture(); busy = true; blocked = false;
    batch = null; selected.clear(); preview.hidden = true; updateControls(); status.textContent = 'Validando archivo e inventario…';
    try {
      const content = new Uint8Array(await file.arrayBuffer());
      if (!current(context)) return;
      const data = await api.authedRequest(`/api/v1/changes/csv-imports?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST', headers: { 'Content-Type': 'text/csv; charset=utf-8' }, body: content,
      });
      if (!current(context)) return;
      render(data); status.textContent = 'Validación terminada. Revisa las filas antes de confirmar; aún no hay reservas nuevas.';
    } catch (error) { if (current(context)) status.textContent = error.message; }
    finally { if (current(context)) { busy = false; updateControls(); } }
  });

  async function transition(action) {
    if (busy || !batch || (action === 'confirm' && (blocked || !selected.size))) return;
    const context = capture(), id = batch.id;
    busy = true; updateControls();
    status.textContent = action === 'confirm' ? 'Confirmando reservas seleccionadas…' : 'Cancelando carga…';
    try {
      const data = await api.authedRequest(`/api/v1/changes/csv-imports/${id}/${action}`, {
        method: 'POST', ...(action === 'confirm' ? { body: JSON.stringify({ row_numbers: [...selected].sort((a, b) => a - b) }) } : {}),
      });
      if (!current(context)) return;
      render(data); status.textContent = action === 'confirm' ? 'Reservas guardadas. No se crearon SSIDs ni se aplicaron cambios de red.' : 'Carga cancelada; no se crearon reservas.';
      if (action === 'confirm') onConfirmed();
    } catch (error) {
      if (!current(context)) return;
      status.textContent = error.message;
      if ([403, 404].includes(error.status)) { batch = null; selected.clear(); preview.hidden = true; }
      if (error.status === 409) blocked = true;
    } finally { if (current(context)) { busy = false; updateControls(); } }
  }
  confirm.addEventListener('click', () => transition('confirm'));
  cancel.addEventListener('click', () => transition('cancel'));
  return { reset, configureUser };
}
