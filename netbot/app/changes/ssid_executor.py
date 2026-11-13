"""Escritura independiente para el contrato público UniFi Network 10.6.106.

No se importa código del otro producto. Toda llamada requiere un plan confirmado y una
autorización inmediatamente anterior a la escritura. Ninguna excepción, cabecera ni
cuerpo del controlador sale de este módulo: pueden contener secretos.
"""
import json
from contextlib import asynccontextmanager
from urllib.parse import quote, urlsplit

import httpx

from app.core.errors import ServiceUnavailable

CONTRACT = '10.6.106'
# Campos de solo lectura del detalle que el contrato no admite en PUT.
READ_ONLY_FIELDS = {'id', 'metadata'}
PERSONAL_SECURITY = {'WPA2_PERSONAL', 'WPA3_PERSONAL', 'WPA2_WPA3_PERSONAL'}


class WriteUncertain(Exception):
    """No se reintenta: el controlador puede haber aplicado la escritura."""


def _path(site_id, resource, item_id=None):
    path = f'sites/{quote(site_id, safe="")}/{resource}'
    return path if item_id is None else f'{path}/{quote(item_id, safe="")}'


class UniFiSsidWriter:
    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport

    def api_key(self):
        key = self.settings.unifi_write_api_key or self.settings.unifi_api_key
        return key.get_secret_value()

    def _require_enabled(self):
        s = self.settings
        if not s.unifi_write_enabled or s.unifi_api_contract != CONTRACT or s.unifi_inventory_mode != 'api':
            raise ServiceUnavailable('La escritura UniFi requiere habilitación explícita y contrato 10.6.106.')
        base = urlsplit(s.unifi_api_base_url or '')
        if (base.scheme != 'https' or base.username or base.password or base.query or base.fragment
                or not (s.unifi_write_api_key or s.unifi_api_key)):
            raise ServiceUnavailable('La conexión UniFi no está configurada de forma válida.')

    @asynccontextmanager
    async def _client(self):
        s = self.settings
        async with httpx.AsyncClient(base_url=s.unifi_api_base_url.rstrip('/') + '/',
                                     headers={'X-API-Key': self.api_key()}, verify=s.unifi_ca_bundle or True,
                                     timeout=s.unifi_timeout_seconds, follow_redirects=False,
                                     transport=self.transport) as client:
            yield client

    async def _require_contract(self, client):
        info = await client.get('info')
        if info.status_code != 200 or info.json().get('applicationVersion') != self.settings.unifi_api_contract:
            raise ServiceUnavailable('La versión del controlador no coincide con el contrato de escritura habilitado.')

    # ------------------------------------------------------------------ creación
    def profile(self, name):
        try:
            profiles = json.loads(self.settings.ssid_security_profiles_json.get_secret_value())
            p = profiles[name]
            if p['type'] != 'WPA2_PERSONAL' or not isinstance(p['passphrase'], str) or not 8 <= len(p['passphrase']) <= 63:
                raise ValueError()
            if (not isinstance(p.get('bands'), list) or not p['bands'] or not set(p['bands']) <= {2.4, 5}
                    or len(p['bands']) != len(set(p['bands']))):
                raise ValueError()
            if 'client_isolation' in p and not isinstance(p['client_isolation'], bool):
                raise ValueError()
            return p
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ServiceUnavailable('Perfil de seguridad ausente o no compatible con el contrato habilitado.') from None

    def body(self, proposal):
        p = self.profile(proposal.security_profile)
        return {'type': 'STANDARD', 'name': proposal.ssid, 'enabled': True,
                'network': {'type': 'SPECIFIC', 'networkId': proposal.network_id},
                'broadcastingDeviceFilter': {'type': 'DEVICES', 'deviceIds': proposal.ap_ids},
                'broadcastingFrequenciesGHz': p['bands'],
                'securityConfiguration': {'type': 'WPA2_PERSONAL', 'passphrase': p['passphrase'],
                                          'fastRoamingEnabled': False, 'pmfMode': 'OPTIONAL'},
                'channel2gLockedTo6': False, 'clientIsolationEnabled': bool(p.get('client_isolation', True)),
                'dtimPeriod2gLockedTo3': False, 'hideName': False, 'multicastToUnicastConversionEnabled': False,
                'uapsdEnabled': False, 'advertiseDeviceName': False, 'arpProxyEnabled': False,
                'bssTransitionEnabled': False}

    async def create(self, site_id, proposal, authorize):
        self._require_enabled()
        body = self.body(proposal)
        try:
            async with self._client() as client:
                await self._require_contract(client)
                authorize()
                result = await client.post(_path(site_id, 'wifi/broadcasts'), json=body)
                if result.status_code != 201:
                    # Incluso un error HTTP puede seguir a una aplicación parcial en un proxy.
                    raise WriteUncertain()
                data = result.json()
                if not isinstance(data.get('id'), str) or not data['id']:
                    raise WriteUncertain()
                return data['id']
        except (httpx.HTTPError, ValueError, TypeError):
            raise WriteUncertain() from None

    async def verify(self, site_id, external_id, proposal):
        try:
            async with self._client() as client:
                response = await client.get(_path(site_id, 'wifi/broadcasts', external_id))
                response.raise_for_status()
                b = response.json()
                expected = self.body(proposal)
                return (b.get('id') == external_id and b.get('name') == proposal.ssid and b.get('enabled') is True
                        and b.get('network') == expected['network']
                        and b.get('broadcastingDeviceFilter', {}).get('type') == 'DEVICES'
                        and set(b.get('broadcastingDeviceFilter', {}).get('deviceIds', [])) == set(proposal.ap_ids)
                        and set(b.get('broadcastingFrequenciesGHz', [])) == set(expected['broadcastingFrequenciesGHz'])
                        and b.get('clientIsolationEnabled') == expected['clientIsolationEnabled']
                        and b.get('securityConfiguration', {}).get('type') == 'WPA2_PERSONAL')
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            return False

    async def delete_created(self, site_id, external_id, ssid):
        """Compensación: elimina únicamente el SSID que creó este trabajo.

        Devuelve True si el recurso ya no existe. Si el identificador apunta a otro nombre,
        no se borra: pudo ser reutilizado por un tercero.
        """
        self._require_enabled()
        path = _path(site_id, 'wifi/broadcasts', external_id)
        try:
            async with self._client() as client:
                current = await client.get(path)
                if current.status_code == 404:
                    return True
                current.raise_for_status()
                if current.json().get('name') != ssid:
                    return False
                removed = await client.delete(path)
                if removed.status_code not in (200, 204, 404):
                    return False
                return (await client.get(path)).status_code == 404
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return False

    # --------------------------------------------------------- cambio de VLAN (HU010)
    async def update_vlan(self, site_id, broadcast_id, current_network_id, target_network_id, authorize):
        """Reasocia un SSID existente a otra red existente.

        El contrato 10.6.106 solo ofrece PUT (reemplazo completo): se reenvía el detalle
        leído, sin campos de solo lectura, cambiando únicamente la referencia de red. Si
        el controlador devuelve la clave censurada no se escribe: reenviarla la sustituiría.
        Un error después de iniciar el PUT es incierto y no debe reintentarse.
        """
        self._require_enabled()
        if (not all(isinstance(x, str) and x for x in (site_id, broadcast_id, current_network_id, target_network_id))
                or current_network_id == target_network_id):
            raise ServiceUnavailable('Identificadores de VLAN/SSID inválidos.')
        path = _path(site_id, 'wifi/broadcasts', broadcast_id)
        async with self._client() as client:
            try:
                await self._require_contract(client)
                before = await client.get(path)
                before.raise_for_status()
                detail = before.json()
                if (detail.get('id') != broadcast_id
                        or detail.get('network') != {'type': 'SPECIFIC', 'networkId': current_network_id}):
                    raise ServiceUnavailable('El SSID cambió antes de la escritura; requiere otra propuesta.')
                body = self._replacement_body(detail, target_network_id)
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
                raise ServiceUnavailable('No fue posible revalidar el SSID antes de escribir.') from None
            authorize()  # última autorización inmediatamente antes de escribir
            try:
                response = await client.put(path, json=body)
                if response.status_code != 200:
                    raise WriteUncertain()
            except (httpx.HTTPError, ValueError, TypeError):
                raise WriteUncertain() from None

    @staticmethod
    def _replacement_body(detail, network_id):
        security = detail.get('securityConfiguration')
        if not isinstance(security, dict) or not isinstance(security.get('type'), str):
            raise ServiceUnavailable('El controlador no entregó la seguridad del SSID; no se modifica.')
        if security['type'] in PERSONAL_SECURITY:
            passphrase = security.get('passphrase')
            if not isinstance(passphrase, str) or len(passphrase) < 8 or set(passphrase) <= {'*', '•'}:
                raise ServiceUnavailable('El controlador censura la clave del SSID; no se modifica para no sustituirla.')
        body = {key: value for key, value in detail.items() if key not in READ_ONLY_FIELDS}
        body['network'] = {'type': 'SPECIFIC', 'networkId': network_id}
        return body

    async def read_network(self, site_id, broadcast_id):
        """Red actualmente asociada (solo lectura), para conciliar un resultado incierto."""
        async with self._client() as client:
            try:
                response = await client.get(_path(site_id, 'wifi/broadcasts', broadcast_id))
                response.raise_for_status()
                network = response.json().get('network')
                if not isinstance(network, dict) or network.get('type') != 'SPECIFIC':
                    raise ValueError()
                return network['networkId']
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
                raise ServiceUnavailable('No se pudo leer la red actual del SSID.') from None

    async def verify_vlan(self, site_id, broadcast_id, ssid, target_network_id):
        """Comprobación read-only de identidad y red, sin revelar datos sensibles."""
        try:
            async with self._client() as client:
                response = await client.get(_path(site_id, 'wifi/broadcasts', broadcast_id))
                response.raise_for_status()
                data = response.json()
                return (data.get('id') == broadcast_id and data.get('name') == ssid
                        and data.get('network') == {'type': 'SPECIFIC', 'networkId': target_network_id})
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            return False

    # ------------------------------------------------------------- reinicio (HU011)
    async def device(self, site_id, device_id):
        """Estado mínimo de un equipo adoptado. Lo no informado queda desconocido."""
        async with self._client() as client:
            try:
                response = await client.get(_path(site_id, 'devices', device_id))
                response.raise_for_status()
                data = response.json()
                if data.get('id') != device_id or not isinstance(data.get('state'), str):
                    raise ValueError()
                features = data.get('features') if isinstance(data.get('features'), dict) else {}
                uptime = None
                stats = await client.get(_path(site_id, 'devices', device_id) + '/statistics/latest')
                if stats.status_code == 200 and isinstance(stats.json(), dict):
                    value = stats.json().get('uptimeSec')
                    uptime = value if isinstance(value, int) and not isinstance(value, bool) else None
                return {'id': device_id, 'name': str(data.get('name') or device_id)[:255], 'state': data['state'],
                        'access_point': 'accessPoint' in features, 'uptime_seconds': uptime}
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                raise ServiceUnavailable('No se pudo consultar el dispositivo en UniFi.') from None

    async def connected_clients(self, site_id, device_id):
        """Clientes cuyo enlace es el equipo. None = el controlador no permitió determinarlo."""
        try:
            async with self._client() as client:
                count = offset = 0
                for _ in range(25):
                    response = await client.get(_path(site_id, 'clients'), params={'offset': offset, 'limit': 200})
                    response.raise_for_status()
                    page = response.json()
                    rows, total = page['data'], page['totalCount']
                    if not isinstance(rows, list) or not isinstance(total, int):
                        return None
                    count += sum(1 for row in rows if row.get('uplinkDeviceId') == device_id)
                    offset += len(rows)
                    if not rows or offset >= total:
                        return count
                return None
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            return None

    async def restart(self, site_id, device_id, authorize):
        """Envía un único reinicio. Un reinicio no se deshace ni se repite a ciegas."""
        self._require_enabled()
        async with self._client() as client:
            try:
                await self._require_contract(client)
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                raise ServiceUnavailable('No fue posible validar el controlador antes de reiniciar.') from None
            authorize()
            try:
                response = await client.post(_path(site_id, 'devices', device_id) + '/actions',
                                             json={'action': 'RESTART'})
                if response.status_code not in (200, 202, 204):
                    raise WriteUncertain()
            except (httpx.HTTPError, ValueError, TypeError):
                raise WriteUncertain() from None
