import json
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from sqlalchemy import select, func
from app.main import app
from app.core.config import Settings, get_settings
from app.auth.models import User, Role
from app.auth.security import hash_password
from app.changes.models import SsidPlan, WifiScopeGrant
from app.changes.wifi_inventory import WifiInventory
from app.changes.dependencies import get_ssid_service
from app.changes.csv_service import utc_now
from app.chat.tools import invoke_tool, ChatToolPermissionError, openrouter_tool_definitions
from app.auth.roles import effective_permissions


@pytest.fixture()
def ssid_setup(client,db_session,admin_user,login):
    tech_role=db_session.scalar(select(Role).where(Role.name=='tecnico'))
    tech=User(email='tech@example.com',hashed_password=hash_password('test-password'),roles=[tech_role])
    db_session.add(tech);db_session.commit()
    settings=Settings(_env_file=None,unifi_inventory_mode='mock')
    app.dependency_overrides[get_settings]=lambda:settings
    _,admin=login('admin@example.com','admin-password')
    _,headers=login('tech@example.com','test-password')
    data={'name':'Feria','site_id':'demo-site','event_name':'Feria','ap_ids':['demo-ap-1'],
          'networks':[{'id':'demo-network-20','parent_interface':'igc1','tag':20}],
          'security_profiles':['perfil-clientes'],'user_ids':[tech.id]}
    response=client.post('/api/v1/changes/wifi-scopes',headers=admin,json=data)
    assert response.status_code==201,response.text
    scope=response.json()['id']
    proposal={'scope_id':scope,'ssid':'Clientes-Feria','ap_ids':['demo-ap-1'],
              'network_id':'demo-network-20','security_profile':'perfil-clientes','purpose':'Atender cliente'}
    return SimpleNamespace(admin=admin,headers=headers,scope=scope,proposal=proposal,data=data,tech=tech,settings=settings)


def test_technician_plan_confirm_and_recovery_are_private_durable_and_do_not_execute(client,db_session,ssid_setup):
    x=ssid_setup
    result=client.post('/api/v1/changes/ssid-plans',headers=x.headers,json=x.proposal)
    assert result.status_code==201,result.text
    plan=result.json(); assert plan['simulated'] is True
    assert client.get(f"/api/v1/changes/ssid-plans/{plan['id']}",headers=x.admin).status_code==404
    payload={'revision':plan['revision'],'row_numbers':[1]}
    response=client.post(f"/api/v1/changes/ssid-plans/{plan['id']}/confirm",headers=x.headers,json=payload)
    assert response.status_code==200,response.text
    assert response.json()['execution_status']=='awaiting_executor'
    assert response.json()['status']=='confirmed'
    assert client.post(f"/api/v1/changes/ssid-plans/{plan['id']}/confirm",headers=x.headers,json=payload).json()==response.json()
    assert client.get('/api/v1/changes/ssid-plans',headers=x.headers).json()[0]['id']==plan['id']
    assert db_session.scalar(select(func.count()).select_from(SsidPlan))==1


def test_technician_cannot_configure_scopes_or_use_unassigned_scope(client,db_session,ssid_setup):
    x=ssid_setup
    assert client.post('/api/v1/changes/wifi-scopes',headers=x.headers,json=x.data).status_code==403
    db_session.delete(db_session.get(WifiScopeGrant,(x.scope,x.tech.id)));db_session.commit()
    assert client.get('/api/v1/changes/wifi-scopes',headers=x.headers).json()==[]
    assert client.post('/api/v1/changes/ssid-plans',headers=x.headers,json=x.proposal).status_code==404
    assert client.post('/api/v1/changes/ssid-plans',json=x.proposal).status_code==401


@pytest.mark.parametrize('field,value',[('ap_ids',['foreign-ap']),('network_id','foreign-network'),('security_profile','foreign-profile')])
def test_scope_resources_are_revalidated_on_api(client,ssid_setup,field,value):
    x=ssid_setup
    response=client.post('/api/v1/changes/ssid-plans',headers=x.headers,json={**x.proposal,field:value})
    assert response.status_code==409


def test_csv_uses_same_scope_validation_and_confirms_only_selected_rows(client,ssid_setup):
    x=ssid_setup
    csv='parent_interface,tag,event_name,purpose,ssid\nigc1,20,Feria,Prueba,Clientes-A\nigc1,30,Feria,Prueba,Clientes-B\n'
    payload={k:x.proposal[k] for k in ['scope_id','ap_ids','security_profile']};payload['csv_text']=csv
    response=client.post('/api/v1/changes/ssid-plans/csv',headers=x.headers,json=payload)
    assert response.status_code==201,response.text
    plan=response.json();assert not plan['rows'][0]['errors'];assert plan['rows'][1]['errors']
    path=f"/api/v1/changes/ssid-plans/{plan['id']}/confirm"
    assert client.post(path,headers=x.headers,json={'revision':plan['revision'],'row_numbers':[3]}).status_code==409
    result=client.post(path,headers=x.headers,json={'revision':plan['revision'],'row_numbers':[2]})
    assert result.status_code==200,result.text
    assert result.json()['selection']==[2]


def test_expiry_tampering_and_revocation_block_confirmation(client,db_session,ssid_setup):
    x=ssid_setup
    plan=client.post('/api/v1/changes/ssid-plans',headers=x.headers,json=x.proposal).json()
    path=f"/api/v1/changes/ssid-plans/{plan['id']}/confirm"
    assert client.post(path,headers=x.headers,json={'revision':'0'*64,'row_numbers':[1]}).status_code==409
    db_session.delete(db_session.get(WifiScopeGrant,(x.scope,x.tech.id)));db_session.commit()
    assert client.post(path,headers=x.headers,json={'revision':plan['revision'],'row_numbers':[1]}).status_code==404
    db_session.add(WifiScopeGrant(scope_id=x.scope,user_id=x.tech.id));db_session.commit()
    row=db_session.get(SsidPlan,plan['id']);row.expires_at=utc_now()-timedelta(seconds=1);db_session.commit()
    assert client.post(path,headers=x.headers,json={'revision':plan['revision'],'row_numbers':[1]}).status_code==409


def test_changed_scope_invalidates_preview_and_cancel_does_not_approve(client,ssid_setup):
    x=ssid_setup
    plan=client.post('/api/v1/changes/ssid-plans',headers=x.headers,json=x.proposal).json()
    client.put(f'/api/v1/changes/wifi-scopes/{x.scope}',headers=x.admin,json={**x.data,'name':'Feria revisada'})
    path=f"/api/v1/changes/ssid-plans/{plan['id']}"
    assert client.post(path+'/confirm',headers=x.headers,json={'revision':plan['revision'],'row_numbers':[1]}).status_code==409
    assert client.post(path+'/cancel',headers=x.headers).json()['status']=='cancelled'


def test_chat_tool_prepares_without_persisting_and_has_no_execution_tool(client,db_session,ssid_setup):
    from app.changes.ssid_service import SsidPlanService
    from app.changes.ssid_schemas import SsidProposal
    from app.monitoring.factory import build_monitoring_service
    x=ssid_setup
    monitoring=build_monitoring_service(x.settings)
    service=SsidPlanService(db_session,x.settings,monitoring)
    async def run():
        result=await invoke_tool('prepare_ssid_creation',x.proposal,monitoring,effective_permissions(x.tech),ssid_context=(service,x.tech))
        assert result['status']=='awaiting_confirmation'
        with pytest.raises(ChatToolPermissionError):
            await invoke_tool('prepare_ssid_creation',x.proposal,monitoring,frozenset(),ssid_context=(service,x.tech))
        await monitoring.aclose()
    asyncio.run(run())
    assert db_session.scalar(select(func.count()).select_from(SsidPlan))==0
    names={t['function']['name'] for t in openrouter_tool_definitions(effective_permissions(x.tech))}
    assert 'prepare_ssid_creation' in names and not any('execute' in n or 'apply' in n for n in names)


def test_official_inventory_paginates_and_never_returns_security_configuration():
    paths=[]
    def respond(request):
        paths.append(request.url.path)
        assert request.headers['X-API-Key']=='test-only-key'
        if request.url.path.endswith('/info'): return httpx.Response(200,json={'applicationVersion':'10.6.106'})
        if request.url.path.endswith('/devices'): rows=[{'id':'ap1','name':'AP','features':['accessPoint']}]
        elif request.url.path.endswith('/networks'): rows=[{'id':'net1','name':'Red','vlanId':20}]
        else: rows=[{'id':'ssid1','name':'SSID','securityConfiguration':{'passphrase':'must-not-leave'}}]
        return httpx.Response(200,json={'data':rows,'totalCount':len(rows)})
    settings=Settings(_env_file=None,unifi_inventory_mode='api',unifi_api_base_url='https://controller.example.test/proxy/network/integration/v1',unifi_api_key='test-only-key')
    result=asyncio.run(WifiInventory(settings,httpx.MockTransport(respond)).read('site1'))
    assert len(paths)==4 and 'securityConfiguration' not in json.dumps(result)
    assert result['networks'][0]['tag']==20


def execution_service(db_session, x, writer):
    from app.changes.ssid_service import SsidPlanService
    from pydantic import SecretStr
    settings=Settings(_env_file=None,unifi_inventory_mode='api',unifi_write_enabled=True,unifi_api_contract='10.6.106',
        monitoring_provider='opnsense',opnsense_base_url='https://firewall.example.test',opnsense_api_key='test',opnsense_api_secret='test',
        monitoring_site_id='lab',ssid_security_profiles_json=json.dumps({'perfil-clientes':{'type':'WPA2_PERSONAL','passphrase':'test-only-password','bands':[2.4,5]}}))
    response=SimpleNamespace(stale=False,status=SimpleNamespace(value='ok'),source='opnsense',collected_at=utc_now(),
        data=[SimpleNamespace(parent_interface='igc1',tag=20)])
    monitoring=SimpleNamespace(get_vlan_inventory=AsyncMock(return_value=response))
    inventory=SimpleNamespace(read=AsyncMock(return_value={'source':'unifi','simulated':False,'application_version':'10.6.106',
        'aps':[{'id':'demo-ap-1','name':'Lab AP','state':'ONLINE'}],'networks':[{'id':'demo-network-20','tag':20}],'ssids':[]}))
    service=SsidPlanService(db_session,settings,monitoring,inventory=inventory,writer=writer)
    service.save_scope(x.tech if False else db_session.query(User).filter_by(email='admin@example.com').one(),
        __import__('app.changes.ssid_schemas',fromlist=['ScopeWrite']).ScopeWrite(**{**x.data,'monitoring_site_id':'lab'}),x.scope)
    return service


def test_worker_claims_approval_reauthorizes_and_verifies_without_duplicate_execution(client,db_session,ssid_setup):
    from app.changes.ssid_schemas import SsidProposal,SsidConfirm
    from app.core.errors import Conflict
    x=ssid_setup
    async def create(site,proposal,authorize): authorize();return 'created-by-plan'
    writer=SimpleNamespace(profile=lambda _: {},create=AsyncMock(side_effect=create),verify=AsyncMock(return_value=True))
    service=execution_service(db_session,x,writer)
    async def run():
        plan=await service.prepare(x.tech,SsidProposal(**x.proposal))
        await service.confirm(x.tech,plan.id,SsidConfirm(revision=plan.revision,row_numbers=[1]))
        result=await service.execute(plan.id)
        assert result.status=='completed'
        assert result.execution_results==[{'ssid':x.proposal['ssid'],'external_id':'created-by-plan','status':'verified_configuration'}]
        with pytest.raises(Conflict): await service.execute(plan.id)
    asyncio.run(run());assert writer.create.await_count==1


def test_uncertain_write_is_durable_keeps_lease_and_is_never_retried(client,db_session,ssid_setup):
    from app.changes.ssid_schemas import SsidProposal,SsidConfirm
    from app.changes.models import WifiWriteLease
    from app.core.errors import Conflict
    from app.changes.ssid_executor import WriteUncertain
    x=ssid_setup
    writer=SimpleNamespace(profile=lambda _: {},create=AsyncMock(side_effect=WriteUncertain()),verify=AsyncMock())
    service=execution_service(db_session,x,writer)
    async def run():
        plan=await service.prepare(x.tech,SsidProposal(**x.proposal))
        await service.confirm(x.tech,plan.id,SsidConfirm(revision=plan.revision,row_numbers=[1]))
        assert (await service.execute(plan.id)).status=='uncertain'
        with pytest.raises(Conflict): await service.execute(plan.id)
        second=await service.prepare(x.tech,SsidProposal(**x.proposal))
        await service.confirm(x.tech,second.id,SsidConfirm(revision=second.revision,row_numbers=[1]))
        with pytest.raises(Conflict): await service.execute(second.id)
    asyncio.run(run())
    assert writer.create.await_count==1 and db_session.scalar(select(func.count()).select_from(WifiWriteLease))==1


def test_writer_uses_official_create_contract_and_rejects_other_version():
    from app.changes.ssid_executor import UniFiSsidWriter
    from app.changes.ssid_schemas import SsidProposal
    from app.core.errors import ServiceUnavailable
    posted=[];version=['10.6.106'];authorizations=[]
    def respond(request):
        if request.url.path.endswith('/info'): return httpx.Response(200,json={'applicationVersion':version[0]})
        assert request.method=='POST'
        body=json.loads(request.content);posted.append(body)
        return httpx.Response(201,json={'id':'new-broadcast'})
    settings=Settings(_env_file=None,unifi_inventory_mode='api',unifi_api_base_url='https://controller.example.test/proxy/network/integration/v1',
        unifi_api_key='test-only-key',unifi_write_enabled=True,unifi_api_contract='10.6.106',
        ssid_security_profiles_json=json.dumps({'p':{'type':'WPA2_PERSONAL','passphrase':'test-only-psk','bands':[2.4,5]}}))
    writer=UniFiSsidWriter(settings,httpx.MockTransport(respond))
    proposal=SsidProposal(scope_id=1,ssid='New SSID',network_id='network1',ap_ids=['ap1'],security_profile='p',purpose='Test')
    assert asyncio.run(writer.create('site1',proposal,lambda:authorizations.append(True)))=='new-broadcast'
    body=posted[0]
    assert body['broadcastingDeviceFilter']=={'type':'DEVICES','deviceIds':['ap1']}
    assert body['network']=={'type':'SPECIFIC','networkId':'network1'}
    assert body['securityConfiguration']['type']=='WPA2_PERSONAL'
    assert body['securityConfiguration']['passphrase']=='test-only-psk'
    required={'channel2gLockedTo6','clientIsolationEnabled','dtimPeriod2gLockedTo3','enabled','hideName',
        'multicastToUnicastConversionEnabled','name','securityConfiguration','type','uapsdEnabled','advertiseDeviceName',
        'arpProxyEnabled','broadcastingFrequenciesGHz','bssTransitionEnabled'}
    assert required<=body.keys() and authorizations==[True]
    version[0]='other-version'
    with pytest.raises(ServiceUnavailable): asyncio.run(writer.create('site1',proposal,lambda:None))
    assert len(posted)==1


def test_worker_rejects_ssid_creation_if_an_approved_ap_goes_offline(db_session, ssid_setup):
    from app.changes.ssid_schemas import SsidConfirm, SsidProposal
    from app.core.errors import Conflict

    actor = ssid_setup.tech
    writer = SimpleNamespace(profile=lambda _: {}, create=AsyncMock())
    service = execution_service(db_session, ssid_setup, writer)

    async def run():
        proposal = SsidProposal(**ssid_setup.proposal)
        plan = await service.prepare(actor, proposal)
        await service.confirm(actor, plan.id, SsidConfirm(revision=plan.revision, row_numbers=[1]))
        service.inventory.read.return_value['aps'][0]['state'] = 'OFFLINE'
        with pytest.raises(Conflict):
            await service.execute(plan.id)
        writer.create.assert_not_awaited()

    asyncio.run(run())


def test_event_excel_previews_wifi_rows_without_persisting_secrets(client, db_session, ssid_setup):
    from base64 import b64encode
    from io import BytesIO
    from zipfile import ZipFile

    spreadsheet = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    document = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    package = 'http://schemas.openxmlformats.org/package/2006/relationships'

    def row(number, event, ssid, vlan, key=''):
        text_cells = {'A': event, 'B': ssid, 'D': key}
        cells = ''.join(
            f'<c r="{column}{number}" t="inlineStr"><is><t>{value}</t></is></c>'
            for column, value in text_cells.items()
        )
        return f'<row r="{number}">{cells}<c r="C{number}"><v>{vlan}</v></c></row>'

    rows = row(1, 'Evento', 'WiFi / SSID', 'N° Vlan', 'Clave')
    rows += row(3, 'Feria', 'Clientes-A', '20.0', 'secret-workbook-value')
    rows += row(4, 'Feria', '', '30')  # Fila de cableado.
    rows += row(5, 'Feria', 'Clientes-B', '99')
    rows += row(6, 'Otro evento', 'Clientes-C', '20')
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{spreadsheet}" xmlns:r="{document}">'
                         '<sheets><sheet name="Histórico" r:id="history"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="{package}">'
                         f'<Relationship Id="history" Type="{document}/worksheet" Target="worksheets/sheet2.xml"/>'
                         '</Relationships>')
        archive.writestr('xl/worksheets/sheet2.xml', f'<worksheet xmlns="{spreadsheet}">'
                         f'<sheetData>{rows}</sheetData></worksheet>')

    setup = ssid_setup
    payload = {key: setup.proposal[key] for key in ('scope_id', 'security_profile', 'ap_ids')}
    payload['xlsx_base64'] = b64encode(buffer.getvalue()).decode('ascii')
    path = '/api/v1/changes/ssid-plans/xlsx'
    assert client.post(path, json=payload).status_code == 401
    response = client.post(path, headers=setup.headers, json=payload)
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan['status'] == 'preview' and not plan['selection']
    assert [row['row_number'] for row in plan['rows']] == [3, 5, 6]
    valid, *invalid = plan['rows']
    assert valid['proposal']['network_id'] == 'demo-network-20'
    assert valid['proposal']['ap_ids'] == ['demo-ap-1']
    assert all(row['errors'] and row['proposal'] is None for row in invalid)
    assert 'secret-workbook-value' not in response.text
    assert 'secret-workbook-value' not in str(db_session.scalars(select(SsidPlan)).one().rows)
    confirm = f"/api/v1/changes/ssid-plans/{plan['id']}/confirm"
    assert client.post(confirm, headers=setup.headers,
                       json={'revision': plan['revision'], 'row_numbers': [5]}).status_code == 409
    assert client.post(confirm, headers=setup.headers,
                       json={'revision': plan['revision'], 'row_numbers': [3]}).status_code == 200
