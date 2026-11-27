import pytest
from test_planner_core import repo, services
from test_day_api import client, runtime, APP_KEY

def test_asap_is_tenant_scoped_open_and_independent_of_date(repo, services):
    tasks = services[0]
    a = tasks.create_task('Urgent fixture', scheduled_date='2020-01-01', metadata={'asap': True})['data']['task']
    tasks.create_task('Ordinary critical', priority='critical')
    b = tasks.create_task('Closed fixture', metadata={'asap': True})['data']['task']
    tasks.complete_task(b['id'])
    assert [x['id'] for x in tasks.asap_items()] == [a['id']]

def test_asap_api_create_close_and_auth(client):
    assert client.post('/v2/day/asap', json={'title':'Fixture'}).status_code == 401
    r=client.post('/v2/day/asap',headers=APP_KEY,json={'title':'Urgent fixture'})
    assert r.status_code==201
    task=r.json()['data']['task']
    assert task['metadata']['asap'] is True
    items=client.get('/v2/day/inbox?date=2030-01-01',headers=APP_KEY).json()['data']['asap_items']
    assert [x['id'] for x in items]==[task['id']]
    assert client.patch('/v2/day/tasks/'+task['id'],headers=APP_KEY,json={'done':True}).status_code==200
    assert client.get('/v2/day/inbox',headers=APP_KEY).json()['data']['asap_items']==[]

def test_asap_query_is_projected_strict_and_tenant_scoped(repo, services, monkeypatch):
    calls=[]
    original=repo.gateway.select
    def select(table, **kw):
        calls.append((table, kw))
        return original(table, **kw)
    monkeypatch.setattr(repo.gateway,'select',select)
    services[0].asap_items()
    table,kw=calls[-1]
    assert table=='planner_tasks'
    assert kw['filters']=={**repo._tenant(),'metadata->>asap':True,'status':['todo','in_progress','blocked']}
    assert kw['columns']=='id,title,status,scheduled_date,start_time,estimated_minutes,created_at'
    def failed(*a,**kw):raise RuntimeError('read failed')
    monkeypatch.setattr(repo.gateway,'select',failed)
    with pytest.raises(RuntimeError,match='read failed'):services[0].asap_items()
