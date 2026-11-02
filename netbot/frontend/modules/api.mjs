
export function createApi({ fetch, localStorage, state, onSessionExpired = () => {} }) {
  // Producción: API del mismo origen; desarrollo local conserva el puerto 8000.
  const location = globalThis.location;
  const API_BASE = location && !['localhost', '127.0.0.1'].includes(location.hostname)
    ? location.origin : 'http://localhost:8000';
  // Migración: no reutilizar ni conservar sesiones persistidas por versiones previas.
  localStorage.removeItem('netbot_tokens');
  localStorage.removeItem('netbot_api_url');
  let tokensInMemory = null;
  const MONITORING = '/api/v1/monitoring';
  const getStoredTokens = () => tokensInMemory ? { ...tokensInMemory } : null;

  class ApiError extends Error {
    constructor(message, status, body) { super(message); this.status = status; this.body = body; }
  }

  async function apiRequest(path, options = {}, accessToken = '') {
    const response = await fetch(`${API_BASE}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}), ...(options.headers || {}) } });
    if (response.status === 204) return null;
    if (options.raw && response.ok) return response.blob();
    let body = null;
    try { body = await response.json(); } catch {}
    if (!response.ok) throw new ApiError(body?.detail || 'No fue posible conectar con Netbot.', response.status, body);
    return body;
  }

  let refreshInFlight = null;

  async function refreshTokens() {
    const session = state.session;
    if (refreshInFlight?.session === session) return refreshInFlight.promise;
    const tokens = getStoredTokens();
    if (!tokens?.refresh_token) throw new ApiError('Sesion expirada', 401);
    const promise = (async () => {
      const fresh = await apiRequest('/auth/refresh', { method: 'POST', body: JSON.stringify({ refresh_token: tokens.refresh_token }) });
      if (session !== state.session) throw new ApiError('La sesión cambió.', 0);
      tokensInMemory = { ...fresh };
      return fresh;
    })();
    refreshInFlight = { session, promise };
    try { return await promise; }
    finally { if (refreshInFlight?.promise === promise) refreshInFlight = null; }
  }

  // Cada solicitud conserva su sesión. Una respuesta tardía no puede renovar otra cuenta.
  async function authedRequest(path, options = {}) {
    const session = state.session;
    const tokens = getStoredTokens();
    try {
      const response = await apiRequest(path, options, tokens?.access_token);
      if (session !== state.session) throw new ApiError('La sesión cambió.', 0);
      return response;
    } catch (error) {
      if (session !== state.session || error.status !== 401) throw error;
      // El DoD de login exige volver a autenticarse al expirar; no renovar
      // silenciosamente ni repetir una escritura POST después de un 401.
      onSessionExpired();
      throw error;
    }
  }

  // Los endpoints de monitoreo responden 503 con el mismo envoltorio cuando la fuente no tiene datos.
  async function monitoringRequest(path) {
    try {
      return await authedRequest(`${MONITORING}${path}`);
    } catch (error) {
      if (error.status === 503 && error.body?.status) return error.body;
      throw error;
    }
  }


  return { apiRequest, authedRequest, refreshTokens, getStoredTokens, setTokens: (tokens) => { tokensInMemory = { ...tokens }; }, clearTokens: () => { tokensInMemory = null; }, monitoringRequest };
}
