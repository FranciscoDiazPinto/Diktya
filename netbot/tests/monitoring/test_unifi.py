import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import Settings
from app.monitoring.providers.unifi import UniFiAccessPointProvider
from app.monitoring.schemas import AccessPointState, IssueKind


def settings(**kwargs):
    return Settings(_env_file=None,unifi_monitoring_mode='api',unifi_api_base_url='https://controller.test/integration/v1',
        unifi_api_key='fake-test-api-key',unifi_monitoring_site_id='site-a',**kwargs)


def device(id='ap-one',**extra):
    return {'id':id,'name':'AP <script>','features':['accessPoint'],'state':'ONLINE','model':'Demo','password':'must-never-leave-adapter',**extra}


async def test_paginated_inventory_statistics_are_direct_objects_and_only_safe_fields_leave_adapter():
    requests=[]
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/info'):return httpx.Response(200,json={'applicationVersion':'10.6.106'})
        if request.url.path.endswith('/statistics/latest'):
            return httpx.Response(200,json={'uptimeSec':0,'cpuUtilizationPct':0.0,'lastHeartbeatAt':'2026-10-30T12:00:00Z','apiKey':'must-never-leave-adapter'})
        offset=int(request.url.params['offset'])
        return httpx.Response(200,json={'data':[device('ap-one' if offset==0 else 'switch',features=['accessPoint'] if offset==0 else ['switching'])],
                                       'totalCount':2,'offset':offset,'count':1})
    result=await UniFiAccessPointProvider(settings(),transport=httpx.MockTransport(handler)).collect()
    assert len(result.data)==1 and result.data[0].state==AccessPointState.ONLINE
    assert result.data[0].uptime_seconds==0 and result.data[0].cpu_percent==0
    assert result.data[0].last_heartbeat_at==datetime(2026,10,30,12,tzinfo=timezone.utc)
    assert result.data[0].telemetry_available
    assert all(r.method=='GET' and r.headers['X-API-Key']=='fake-test-api-key' for r in requests)
    assert len(requests)==4
    assert 'must-never-leave-adapter' not in json.dumps([p.model_dump(mode='json') for p in result.data])


@pytest.mark.parametrize('status,kind',[(401,IssueKind.AUTHENTICATION),(403,IssueKind.PERMISSION),
    (404,IssueKind.NOT_SUPPORTED),(429,IssueKind.RATE_LIMITED),(500,IssueKind.SERVER_ERROR),(302,IssueKind.INVALID_RESPONSE)])
async def test_upstream_errors_are_typed_and_do_not_leak_response(status,kind):
    provider=UniFiAccessPointProvider(settings(),transport=httpx.MockTransport(lambda _:httpx.Response(status,text='fake-secret-controller-body')))
    response=await provider.collect()
    assert response.data is None and response.issues[0].kind==kind
    assert 'fake-secret' not in response.issues[0].message


@pytest.mark.parametrize('mode,base',[('disabled','https://controller.test'),('api','http://controller.test'),('api','https://user:pass@controller.test')])
async def test_invalid_configuration_never_contacts_controller(mode,base):
    calls=[]
    config=settings();config.unifi_monitoring_mode=mode;config.unifi_api_base_url=base
    result=await UniFiAccessPointProvider(config,transport=httpx.MockTransport(lambda r:calls.append(r))).collect()
    assert result.data is None and result.issues[0].kind==IssueKind.CONFIGURATION and not calls


@pytest.mark.parametrize('failure',['duplicate','incomplete','changing-total','invalid-json'])
async def test_incoherent_pages_never_become_a_complete_inventory(failure):
    def handler(request):
        if request.url.path.endswith('/info'):return httpx.Response(200,json={'applicationVersion':'10.6.106'})
        offset=int(request.url.params['offset'])
        if failure=='invalid-json':return httpx.Response(200,text='not-json')
        if offset==0:return httpx.Response(200,json={'data':[device()],'totalCount':2})
        if failure=='duplicate':return httpx.Response(200,json={'data':[device()],'totalCount':2})
        if failure=='changing-total':return httpx.Response(200,json={'data':[device('two')],'totalCount':3})
        return httpx.Response(200,json={'data':[],'totalCount':2})
    result=await UniFiAccessPointProvider(settings(),transport=httpx.MockTransport(handler)).collect()
    assert result.data is None and result.issues[0].kind==IssueKind.INVALID_RESPONSE


async def test_statistics_failure_keeps_inventory_and_unknown_state_stays_unknown():
    def handler(request):
        if request.url.path.endswith('/info'):return httpx.Response(200,json={'applicationVersion':'10.6.106'})
        if request.url.path.endswith('/statistics/latest'):return httpx.Response(403,json={'secret':'not-public'})
        return httpx.Response(200,json={'data':[device(state='NEW_STATE')],'totalCount':1})
    result=await UniFiAccessPointProvider(settings(),transport=httpx.MockTransport(handler)).collect()
    assert result.data[0].state==AccessPointState.UNKNOWN and not result.data[0].telemetry_available
    assert result.data[0].uptime_seconds is None and result.data[0].last_heartbeat_at is None
    assert result.issues[0].optional and result.issues[0].kind==IssueKind.PERMISSION


async def test_slow_statistics_have_a_budget_and_do_not_erase_inventory():
    async def handler(request):
        if request.url.path.endswith('/info'):return httpx.Response(200,json={'applicationVersion':'10.6.106'})
        if request.url.path.endswith('/statistics/latest'):
            await asyncio.sleep(1)
            return httpx.Response(200,json={'uptimeSec':1})
        return httpx.Response(200,json={'data':[device()],'totalCount':1})
    result=await UniFiAccessPointProvider(settings(unifi_monitoring_statistics_budget_seconds=0.01),transport=httpx.MockTransport(handler)).collect()
    assert len(result.data)==1 and result.issues[0].kind==IssueKind.TIMEOUT and result.issues[0].optional


async def test_heartbeat_without_timezone_is_not_replaced_by_the_time_of_query():
    def handler(request):
        if request.url.path.endswith('/info'):return httpx.Response(200,json={'applicationVersion':'10.6.106'})
        if request.url.path.endswith('/statistics/latest'):return httpx.Response(200,json={'lastHeartbeatAt':'2026-10-30T12:00:00'})
        return httpx.Response(200,json={'data':[device()],'totalCount':1})
    result=await UniFiAccessPointProvider(settings(),transport=httpx.MockTransport(handler)).collect()
    assert result.data[0].last_heartbeat_at is None and result.issues[0].kind==IssueKind.INVALID_RESPONSE
