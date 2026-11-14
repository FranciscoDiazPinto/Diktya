// Estado de los agentes en segundo plano y del proveedor de IA (HU017/HU019). Solo lectura.
const AGENTS = {monitoring: 'Monitoreo de red', tickets: 'Tickets y notificaciones', changes: 'Ejecución de cambios',
  housekeeping: 'Limpieza periódica'};
const STATES = {ok: 'Operativo', failed: 'Con errores', stalled: 'Sin informar', stopped: 'Detenido', starting: 'Iniciando'};
const REFRESH_MS = 30000;

export function createSystemStatus({document, window, state, api, textNode}) {
  const $ = id => document.querySelector('#' + id);
  let allowed = false, generation = 0, timer = null;
  const current = (session, version) => allowed && session === state.session && version === generation;
  const time = value => value ? new Date(value).toLocaleString('es-CL') : '—';
  function reset() {
    generation += 1; allowed = false;
    if (timer !== null) { window.clearInterval(timer); timer = null; }
    $('agents-body').replaceChildren(); $('llm-health').textContent = ''; $('system-status').textContent = '';
  }
  async function refresh() {
    if (!allowed) return;
    const session = state.session, version = generation;
    try {
      const agents = await api.authedRequest('/api/v1/agents/status');
      if (!current(session, version)) return;
      const rows = agents.map(agent => {
        const row = document.createElement('tr');
        row.append(textNode('td', AGENTS[agent.agent_id] || agent.agent_id), textNode('td', STATES[agent.status] || agent.status),
          textNode('td', time(agent.last_success_at)),
          textNode('td', agent.consecutive_failures ? `${agent.consecutive_failures} · ${agent.last_error || 'error'} · ${time(agent.last_error_at)}` : 'Sin errores'));
        return row;
      });
      $('agents-body').replaceChildren(...rows);
      const changes = agents.find(agent => agent.agent_id === 'changes');
      $('system-status').textContent = !changes || ['stopped', 'stalled'].includes(changes.status)
        ? 'El ejecutor de cambios no está activo: las aprobaciones quedan en espera hasta que se inicie.' : '';
    } catch (error) { if (current(session, version)) $('system-status').textContent = error.message; }
    try {
      const health = await api.authedRequest('/api/v1/chat/health');
      if (current(session, version)) $('llm-health').textContent = `${health.provider}${health.model ? ' · ' + health.model : ''}: ${health.detail}`;
    } catch (error) { if (current(session, version)) $('llm-health').textContent = error.message; }
  }
  async function configureUser(user) {
    if (!user.permissions?.includes('monitoring:read')) return;
    allowed = true; timer = window.setInterval(refresh, REFRESH_MS);
    await refresh();
  }
  $('system-refresh').addEventListener('click', refresh);
  return {reset, configureUser, refresh};
}
