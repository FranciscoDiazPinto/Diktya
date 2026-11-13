"""Escritura independiente para el contrato público UniFi Network 10.6.106.
No se importa código del otro producto. Toda llamada requiere un plan confirmado.
"""
import json
from urllib.parse import quote
import httpx
from app.core.errors import ServiceUnavailable


class WriteUncertain(Exception):
    """No se reintenta: el controlador puede haber aplicado la escritura."""


class UniFiSsidWriter:
    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport

    def api_key(self):
        return (self.settings.unifi_write_api_key or self.settings.unifi_api_key).get_secret_value()

    def profile(self, name):
        try:
            profiles=json.loads(self.settings.ssid_security_profiles_json.get_secret_value())
            p=profiles[name]
            if p['type']!='WPA2_PERSONAL' or not isinstance(p['passphrase'],str) or not 8<=len(p['passphrase'])<=63:
                raise ValueError()
            if not isinstance(p.get('bands'),list) or not p['bands'] or not set(p['bands']) <= {2.4,5} or len(p['bands'])!=len(set(p['bands'])):
                raise ValueError()
            if 'client_isolation' in p and not isinstance(p['client_isolation'],bool):
                raise ValueError()
            return p
        except (AttributeError,KeyError,TypeError,ValueError):
            raise ServiceUnavailable('Perfil de seguridad ausente o no compatible con el contrato habilitado.') from None

    def body(self, proposal):
        p=self.profile(proposal.security_profile)
        return {'type':'STANDARD','name':proposal.ssid,'enabled':True,
            'network':{'type':'SPECIFIC','networkId':proposal.network_id},
            'broadcastingDeviceFilter':{'type':'DEVICES','deviceIds':proposal.ap_ids},
            'broadcastingFrequenciesGHz':p['bands'],
            'securityConfiguration':{'type':'WPA2_PERSONAL','passphrase':p['passphrase'],'fastRoamingEnabled':False,'pmfMode':'OPTIONAL'},
            'channel2gLockedTo6':False,'clientIsolationEnabled':bool(p.get('client_isolation',True)),
            'dtimPeriod2gLockedTo3':False,'hideName':False,'multicastToUnicastConversionEnabled':False,
            'uapsdEnabled':False,'advertiseDeviceName':False,'arpProxyEnabled':False,'bssTransitionEnabled':False}

    async def create(self, site_id, proposal, authorize):
        s=self.settings
        if not s.unifi_write_enabled or s.unifi_api_contract!='10.6.106' or s.unifi_inventory_mode!='api':
            raise ServiceUnavailable('La escritura UniFi requiere habilitación explícita y contrato 10.6.106.')
        # Reutilizar la validación de URL/TLS del inventario antes de construir este cliente.
        from urllib.parse import urlsplit
        base=urlsplit(s.unifi_api_base_url or '')
        if base.scheme!='https' or base.username or base.password or base.query or base.fragment or not (s.unifi_write_api_key or s.unifi_api_key):
            raise ServiceUnavailable('La conexión UniFi no está configurada de forma válida.')
        body=self.body(proposal)
        path=f'sites/{quote(site_id,safe="")}/wifi/broadcasts'
        try:
            async with httpx.AsyncClient(base_url=s.unifi_api_base_url.rstrip('/')+'/',headers={'X-API-Key':self.api_key()},
                verify=s.unifi_ca_bundle or True,timeout=s.unifi_timeout_seconds,follow_redirects=False,transport=self.transport) as client:
                info=await client.get('info')
                if info.status_code!=200 or info.json().get('applicationVersion')!=s.unifi_api_contract:
                    raise ServiceUnavailable('La versión del controlador no coincide con el contrato de escritura habilitado.')
                authorize()
                result=await client.post(path,json=body)
                if result.status_code!=201:
                    # Incluso un error HTTP puede seguir a una aplicación parcial en un proxy.
                    raise WriteUncertain()
                data=result.json()
                if not isinstance(data.get('id'),str) or not data['id']:
                    raise WriteUncertain()
                return data['id']
        except (httpx.HTTPError,ValueError,TypeError):
            raise WriteUncertain() from None

    async def verify(self, site_id, external_id, proposal):
        s=self.settings
        path=f'sites/{quote(site_id,safe="")}/wifi/broadcasts/{quote(external_id,safe="")}'
        try:
            async with httpx.AsyncClient(base_url=s.unifi_api_base_url.rstrip('/')+'/',headers={'X-API-Key':self.api_key()},
                    verify=s.unifi_ca_bundle or True,timeout=s.unifi_timeout_seconds,follow_redirects=False,transport=self.transport) as client:
                response=await client.get(path);response.raise_for_status();b=response.json()
                expected=self.body(proposal)
                return (b.get('id')==external_id and b.get('name')==proposal.ssid and b.get('enabled') is True
                    and b.get('network')==expected['network']
                    and b.get('broadcastingDeviceFilter',{}).get('type')=='DEVICES'
                    and set(b.get('broadcastingDeviceFilter',{}).get('deviceIds',[]))==set(proposal.ap_ids)
                    and set(b.get('broadcastingFrequenciesGHz',[]))==set(expected['broadcastingFrequenciesGHz'])
                    and b.get('clientIsolationEnabled')==expected['clientIsolationEnabled']
                    and b.get('securityConfiguration',{}).get('type')=='WPA2_PERSONAL')
        except (httpx.HTTPError,ValueError,TypeError,KeyError):
            return False


    async def update_vlan(self, site_id, broadcast_id, current_network_id, target_network_id, authorize):
        """H10: PATCH mínimo; contrato de actualización pendiente de validación en UniFi real.

        No se envían campos de seguridad, nombre, AP ni contraseña.
        Un error después de iniciar PATCH siempre es incierto y no debe reintentarse.
        """
        from urllib.parse import urlsplit
        s = self.settings
        if not (s.unifi_write_enabled and s.unifi_api_contract == '10.6.106'
                and s.unifi_inventory_mode == 'api'):
            raise ServiceUnavailable('Escritura H10 deshabilitada o contrato no autorizado.')
        base = urlsplit(s.unifi_api_base_url or '')
        if (base.scheme != 'https' or base.username or base.password or base.query
                or base.fragment or not s.unifi_api_key):
            raise ServiceUnavailable('Configuración UniFi inválida.')
        if (not all(isinstance(x, str) and x for x in
                    (site_id, broadcast_id, current_network_id, target_network_id))
                or current_network_id == target_network_id):
            raise ServiceUnavailable('Identificadores de VLAN/SSID inválidos.')
        path = f'sites/{quote(site_id,safe="")}/wifi/broadcasts/{quote(broadcast_id,safe="")}'
        async with httpx.AsyncClient(
            base_url=s.unifi_api_base_url.rstrip('/')+'/',
            headers={'X-API-Key': s.unifi_api_key.get_secret_value()},
            verify=s.unifi_ca_bundle or True, timeout=s.unifi_timeout_seconds,
            follow_redirects=False, transport=self.transport,
        ) as client:
            try:
                info = await client.get('info')
                if info.status_code != 200 or info.json().get('applicationVersion') != s.unifi_api_contract:
                    raise ServiceUnavailable('Versión UniFi no compatible con el contrato autorizado.')
                before = await client.get(path)
                before.raise_for_status()
                data = before.json()
                if (data.get('id') != broadcast_id
                        or data.get('network') != {'type': 'SPECIFIC', 'networkId': current_network_id}):
                    raise ServiceUnavailable('El SSID cambió antes de la escritura; requiere otra propuesta.')
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                raise ServiceUnavailable('No fue posible revalidar el SSID antes de escribir.') from None
            authorize()  # última autorización inmediatamente antes del PATCH
            try:
                response = await client.patch(path, json={
                    'network': {'type': 'SPECIFIC', 'networkId': target_network_id},
                })
                if response.status_code not in (200, 204):
                    raise WriteUncertain()
            except (httpx.HTTPError, ValueError, TypeError):
                raise WriteUncertain() from None

    async def verify_vlan(self, site_id, broadcast_id, ssid, target_network_id):
        """Comprobación read-only de identidad y red, sin revelar datos sensibles."""
        s = self.settings
        path = f'sites/{quote(site_id,safe="")}/wifi/broadcasts/{quote(broadcast_id,safe="")}'
        try:
            async with httpx.AsyncClient(
                base_url=s.unifi_api_base_url.rstrip('/')+'/',
                headers={'X-API-Key': s.unifi_api_key.get_secret_value()},
                verify=s.unifi_ca_bundle or True, timeout=s.unifi_timeout_seconds,
                follow_redirects=False, transport=self.transport,
            ) as client:
                response = await client.get(path)
                response.raise_for_status()
                data = response.json()
                return (data.get('id') == broadcast_id and data.get('name') == ssid
                        and data.get('network') == {'type': 'SPECIFIC', 'networkId': target_network_id})
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return False
