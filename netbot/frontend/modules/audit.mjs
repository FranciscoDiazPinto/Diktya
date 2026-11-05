// Estado privado y resultados vinculados a la sesión y a los filtros aplicados.
const PAGE_SIZE = 50;
export function createAudit({document, window, state, api}) {
  const $ = id => document.querySelector('#audit-' + id);
  const fields = ['actor', 'source', 'action', 'outcome', 'since', 'until'];
  let allowed = false, generation = 0, offset = 0, total = 0, applied = '', exporting = false;
  const current = (session, version) => allowed && state.session === session && generation === version;
  function paging() {
    $('prev').disabled = !allowed || offset === 0;
    $('next').disabled = !allowed || offset + PAGE_SIZE >= total;
    $('export').disabled = !allowed || exporting;
  }
  function reset() {
    generation++; allowed = false; offset = total = 0; applied = ''; exporting = false;
    fields.forEach(id => { $(id).value = ''; });
    $('body').replaceChildren(); $('page').textContent = ''; $('status').textContent = ''; paging();
  }
  function filters() {
    const params = new URLSearchParams();
    for (const id of fields) {
      const value = $(id).value.trim();
      if (!value) continue;
      params.set(id === 'actor' ? 'actor_id' : id, ['since','until'].includes(id) ? new Date(value).toISOString() : value);
    }
    if (params.has('since') && params.has('until') && params.get('since') > params.get('until')) throw new Error('La fecha inicial no puede superar la final.');
    return params.toString();
  }
  function cell(value) {
    const node = document.createElement('td'); node.textContent = value == null ? '—' : String(value); return node;
  }
  async function refresh() {
    if (!allowed) return;
    const session = state.session, version = ++generation;
    exporting = false; paging();
    $('body').replaceChildren(); $('page').textContent = ''; $('status').textContent = 'Consultando auditoría…';
    $('prev').disabled = $('next').disabled = true;
    try {
      const page = await api.authedRequest(`/api/v1/audit?${applied}&limit=${PAGE_SIZE}&offset=${offset}`);
      if (!current(session, version)) return;
      total = page.total;
      const rows = page.items.map(entry => {
        const row = document.createElement('tr');
        row.append(...[new Date(entry.occurred_at).toLocaleString('es-CL'), entry.source,
          entry.actor_id ?? 'Sistema / no identificado', entry.action, entry.outcome,
          `${entry.resource_type} · ${entry.resource_id ?? '—'}`, entry.snapshot ? 'Estado actual' : 'Evento'].map(cell));
        return row;
      });
      $('body').replaceChildren(...rows);
      $('page').textContent = total ? `${offset + 1}–${offset + rows.length} de ${total}` : '0 registros';
      $('status').textContent = rows.length ? '' : 'No hay registros para estos filtros.';
      paging();
    } catch (error) {
      if (current(session, version)) { total = 0; $('status').textContent = error.message; paging(); }
    }
  }
  async function apply(event) {
    event?.preventDefault();
    if (!allowed) return;
    try { applied = filters(); offset = 0; exporting = false; return refresh(); }
    catch (error) { $('status').textContent = error.message; }
  }
  async function exportCsv() {
    if (!allowed || exporting) return;
    const session = state.session, version = generation;
    exporting = true; paging(); $('status').textContent = 'Preparando exportación…';
    try {
      const blob = await api.authedRequest(`/api/v1/audit/export?${applied}`, {raw: true});
      if (!current(session, version)) return;
      const url = window.URL.createObjectURL(blob), link = document.createElement('a');
      try {
        link.href = url; link.download = 'netbot-auditoria.csv'; document.body.append(link); link.click();
      } finally { link.remove(); window.URL.revokeObjectURL(url); }
      $('status').textContent = 'CSV exportado con los filtros aplicados.';
    } catch (error) { if (current(session, version)) $('status').textContent = error.message; }
    finally { if (current(session, version)) { exporting = false; paging(); } }
  }
  $('filters').addEventListener('submit', apply);
  $('clear').addEventListener('click', () => { fields.forEach(id => { $(id).value = ''; }); return apply(); });
  $('prev').addEventListener('click', () => { if (allowed && offset > 0) { offset -= PAGE_SIZE; return refresh(); } });
  $('next').addEventListener('click', () => { if (allowed && offset + PAGE_SIZE < total) { offset += PAGE_SIZE; return refresh(); } });
  $('export').addEventListener('click', exportCsv);
  return {reset, refresh, configureUser(user) { reset(); allowed = Boolean(user.permissions?.includes('audit:read')); paging(); if (allowed) return refresh(); }};
}
