from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, delete

from app.main import app
from app.auth.models import User, Role
from app.auth.security import hash_password
from app.core.config import Settings, get_settings
from app.monitoring.dependencies import get_monitoring_service
from app.monitoring.factory import build_monitoring_service
from app.networks.models import Network, NetworkAssignment
from app.networks.support_models import NetworkSupportConfig


@pytest.fixture()
def telemetry(client,db_session,admin_user,login):
    users={}
    for role_name in ['tecnico','cliente','visor']:
        role=db_session.scalar(select(Role).where(Role.name==role_name))
        users[role_name]=User(email=f'telemetry-{role_name}@example.com',hashed_password=hash_password('test-password'),roles=[role])
        db_session.add(users[role_name])
    a=Network(name='Red A',site='firewall-local',external_id='A',event_name='Demo',ssid='SSID-A',vlan_tag=20)
    b=Network(name='Red B',site='firewall-local',external_id='B',event_name='Demo',ssid='SSID-B',vlan_tag=30)
    db_session.add_all([a,b]);db_session.flush()
    db_session.add_all([NetworkAssignment(network_id=a.id,user_id=users[r].id) for r in ['tecnico','cliente']])
    db_session.add(NetworkSupportConfig(network_id=a.id,monitoring_interface_id='opt1',unifi_site_id='demo-site',unifi_ap_ids=['demo-ap-1']))
    db_session.commit()
    settings=Settings(_env_file=None,unifi_monitoring_mode='mock',monitoring_site_id='firewall-local',monitoring_cache_ttl_seconds=0)
    monitoring=build_monitoring_service(settings)
    app.dependency_overrides[get_settings]=lambda:settings
    app.dependency_overrides[get_monitoring_service]=lambda:monitoring
    users['admin']=admin_user
    headers={key:login(user.email,'admin-password' if key=='admin' else 'test-password')[1] for key,user in users.items()}
    return users,headers,a,b,monitoring,settings


def test_technical_view_contains_only_explicit_devices_and_interface(client,telemetry):
    _,headers,a,b,_,_=telemetry
    response=client.get(f'/api/v1/networks/{a.id}/telemetry',headers=headers['tecnico'])
    assert response.status_code==200,response.text
    data=response.json()
    assert [ap['id'] for ap in data['access_points']['data']]==['demo-ap-1']
    assert [i['interface_id'] for i in data['interfaces']['data']]==['opt1']
    assert 'demo-ap-2' not in response.text
    assert client.get(f'/api/v1/networks/{b.id}/telemetry',headers=headers['tecnico']).status_code==404
    assert client.get('/api/v1/monitoring/access-points',headers=headers['tecnico']).status_code==403
    assert client.get(f'/api/v1/networks/{a.id}/telemetry',headers=headers['cliente']).status_code==403


def test_global_inventory_is_paginated_and_only_global_roles_can_read_it(client,telemetry):
    _,headers,_,_,_,_=telemetry
    for role in ['admin','visor']:
        response=client.get('/api/v1/monitoring/access-points?limit=1&offset=1',headers=headers[role])
        assert response.status_code==200
        page=response.json()['data']
        assert page['total_count']==3 and page['offset']==1 and page['items'][0]['id']=='demo-ap-2'
    assert client.get('/api/v1/monitoring/access-points?limit=101',headers=headers['admin']).status_code==422


def test_missing_mapping_does_not_default_to_all_devices(client,telemetry):
    _,headers,_,b,_,_=telemetry
    response=client.get(f'/api/v1/networks/{b.id}/telemetry',headers=headers['admin'])
    assert response.status_code==200
    assert response.json()['access_points']['data'] is None
    assert 'demo-ap-' not in response.text


def test_revocation_while_reading_disallows_the_response(client,db_session,telemetry):
    users,headers,a,_,monitoring,_=telemetry
    original=monitoring.get_access_points
    async def revoke():
        result=await original()
        db_session.execute(delete(NetworkAssignment).where(NetworkAssignment.network_id==a.id,NetworkAssignment.user_id==users['tecnico'].id))
        db_session.commit()
        return result
    monitoring.get_access_points=revoke
    response=client.get(f'/api/v1/networks/{a.id}/telemetry',headers=headers['tecnico'])
    assert response.status_code==404 and 'demo-ap-' not in response.text


def test_mapping_change_while_reading_discards_previous_scope(client,db_session,telemetry):
    _,headers,a,_,monitoring,_=telemetry
    original=monitoring.get_access_points
    async def change():
        result=await original()
        db_session.get(NetworkSupportConfig,a.id).unifi_ap_ids=['demo-ap-2'];db_session.commit()
        return result
    monitoring.get_access_points=change
    response=client.get(f'/api/v1/networks/{a.id}/telemetry',headers=headers['tecnico'])
    assert response.status_code==200 and response.json()['access_points']['data'] is None
    assert 'demo-ap-1' not in response.text


def test_admin_configures_binding_and_invalid_empty_scope_cannot_expand_access(client,telemetry):
    _,headers,a,_,_,_=telemetry
    path=f'/admin/networks/{a.id}/support'
    payload={'unifi_site_id':'demo-site','unifi_ap_ids':['demo-ap-2']}
    assert client.put(path,headers=headers['tecnico'],json=payload).status_code==403
    assert client.put(path,headers=headers['admin'],json=payload).status_code==200
    assert client.get(f'/api/v1/networks/{a.id}/telemetry',headers=headers['tecnico']).json()['access_points']['data'][0]['id']=='demo-ap-2'
    assert client.put(path,headers=headers['admin'],json={'unifi_ap_ids':['demo-ap-2']}).status_code==422
    assert client.put(path,headers=headers['admin'],json={**payload,'unifi_ap_ids':['demo-ap-2','demo-ap-2']}).status_code==422


def test_warm_cache_outage_is_explicit_and_never_means_live_healthy(client,telemetry):
    _,headers,a,_,_,settings=telemetry
    first=client.get(f'/api/v1/networks/{a.id}/telemetry',headers=headers['tecnico']).json()
    settings.monitoring_mock_scenario='outage'  # La fuente AP usa el escenario explícito de esta instancia.
    response=client.get(f'/api/v1/networks/{a.id}/telemetry',headers=headers['tecnico']).json()
    aps=response['access_points']
    assert aps['stale'] and aps['status']=='degraded'
    assert aps['collected_at']==first['access_points']['collected_at']
