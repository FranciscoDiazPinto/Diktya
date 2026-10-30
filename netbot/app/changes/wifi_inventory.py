"""Inventario mínimo UniFi. Solo lectura: este adaptador no aprovisiona equipos."""
from urllib.parse import quote, urlsplit
import httpx
from app.core.config import Settings
from app.core.errors import ServiceUnavailable


class WifiInventory:
    def __init__(self, settings: Settings, transport=None):
        self.settings, self.transport = settings, transport

    async def read(self, site_id: str) -> dict:
        s = self.settings
        if s.unifi_inventory_mode == 'mock':
            if site_id != 'demo-site':
                raise ServiceUnavailable('El inventario simulado solo contiene demo-site.')
            return {'source':'mock', 'simulated':True, 'site_id':site_id,
                    'aps':[{'id':'demo-ap-1','name':'AP de demostración'}],
                    'networks':[{'id':'demo-network-20','name':'VLAN demo 20','tag':20}], 'ssids':[]}
        if s.unifi_inventory_mode != 'api' or not s.unifi_api_base_url or not s.unifi_api_key:
            raise ServiceUnavailable('Configura el inventario UniFi o habilita explícitamente el modo mock.')
        url = urlsplit(s.unifi_api_base_url)
        if url.scheme != 'https' or url.username or url.password or url.query or url.fragment:
            raise ServiceUnavailable('La URL base UniFi debe usar HTTPS y no contener credenciales ni parámetros.')
        try:
            async with httpx.AsyncClient(base_url=s.unifi_api_base_url.rstrip('/')+'/',
                    headers={'X-API-Key':s.unifi_api_key.get_secret_value()}, verify=s.unifi_ca_bundle or True,
                    timeout=s.unifi_timeout_seconds, follow_redirects=False, transport=self.transport) as client:
                info = await client.get('info')
                info.raise_for_status()
                version = info.json()['applicationVersion']
                if not isinstance(version, str) or not version:
                    raise ValueError()
                async def pages(resource):
                    items = []
                    for _ in range(50):
                        response = await client.get(f'sites/{quote(site_id, safe="")}/{resource}', params={'offset':len(items),'limit':200})
                        response.raise_for_status()
                        data = response.json()
                        rows = data['data']
                        if not isinstance(rows,list) or not isinstance(data['totalCount'],int) or data['totalCount'] < 0:
                            raise ValueError()
                        items.extend(rows)
                        if len(items) > data['totalCount'] or len({r['id'] for r in items}) != len(items):
                            raise ValueError()
                        if not rows or len(items) >= data['totalCount']:
                            if len(items) < data['totalCount']: raise ValueError()
                            return items
                    raise ValueError()
                devices = await pages('devices')
                networks = await pages('networks')
                broadcasts = await pages('wifi/broadcasts')
                return {'source':'unifi', 'simulated':False, 'site_id':site_id, 'application_version':version,
                        'aps':[{'id':d['id'],'name':d['name']} for d in devices if 'accessPoint' in d.get('features',[])],
                        'networks':[{'id':n['id'],'name':n['name'],'tag':n['vlanId']} for n in networks],
                        'ssids':[{'id':b['id'],'ssid':b['name']} for b in broadcasts]}
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            # No propagar headers, URL ni cuerpos del controlador.
            raise ServiceUnavailable('No se pudo obtener un inventario UniFi completo. Revisa versión, permisos, ruta y TLS.') from None
