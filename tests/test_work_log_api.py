"""Actual-work API authorization, durable retry contract, and day progress."""
from uuid import uuid4
from test_day_api import client, runtime, APP_KEY, USER_ID, WORKSPACE_ID
from planner_api.work_log import planned_seconds


def add_task(runtime, **fields):
    return runtime.service_client.insert('planner_tasks', {'user_id': str(USER_ID), 'workspace_id': str(WORKSPACE_ID), 'title': 'Deep work', 'estimated_minutes': 180, 'scheduled_date': '2026-10-02', **fields})[0]


def test_work_requires_key_and_valid_input(client, runtime):
    task = add_task(runtime)
    assert client.get(f"/v2/day/tasks/{task['id']}/work").status_code == 401
    assert client.post(f"/v2/day/tasks/{task['id']}/work", headers=APP_KEY, json={'request_id': str(uuid4()), 'seconds': -1, 'source': 'manual'}).status_code == 422
    assert client.post(f"/v2/day/tasks/{task['id']}/work", headers=APP_KEY, json={'request_id': str(uuid4()), 'seconds': 5400, 'source': 'manual', 'split': True}).status_code == 400


def test_partial_progress_and_completed_task_history(client, runtime):
    task = add_task(runtime, status='done')
    runtime.service_client.insert('task_work_sessions', {'user_id': str(USER_ID), 'workspace_id': str(WORKSPACE_ID), 'task_ref': task['id'], 'seconds': 5400, 'planned_seconds': 10800, 'source': 'manual'})
    runtime.service_client.insert('task_work_sessions', {'user_id': str(uuid4()), 'workspace_id': str(WORKSPACE_ID), 'task_ref': task['id'], 'seconds': 99, 'planned_seconds': 10800, 'source': 'manual'})
    response = client.get(f"/v2/day/tasks/{task['id']}/work", headers=APP_KEY)
    assert response.status_code == 200
    data = response.json()['data']
    assert data['worked_seconds'] == data['remaining_seconds'] == 5400
    assert data['task']['done'] and data['timezone'] == 'Asia/Kolkata'
    day = client.get('/v2/day?date=2026-10-02', headers=APP_KEY).json()['data']
    item = next(item for item in day['items'] if item['id'] == task['id'])
    assert item['planned_seconds'] == 10800 and item['worked_seconds'] == 5400


def test_post_scopes_atomic_rpc_and_preserves_retry_id(client, runtime):
    task = add_task(runtime)
    calls=[]
    def rpc(name, payload):
        calls.append((name,payload)); return {'remaining_seconds':5400,'done':False}
    runtime.service_client.rpc=rpc
    request_id=str(uuid4())
    body={'request_id':request_id,'seconds':5400,'source':'timer','finish':True,'split':True,'remainder_date':'2026-10-02','remainder_time':'18:00'}
    response=client.post(f"/v2/day/tasks/{task['id']}/work",headers=APP_KEY,json=body)
    assert response.status_code==200, response.text
    name,payload=calls[0]
    assert name=='planner_log_work'
    assert payload['p_user_id']==str(USER_ID) and payload['p_workspace_id']==str(WORKSPACE_ID)
    assert payload['p_request_id']==request_id and payload['p_seconds']==5400
    assert payload['p_remainder_time']=='18:00'


def test_missing_migration_is_explicit_and_does_not_break_day(client, runtime):
    task=add_task(runtime)
    original=runtime.service_client.select
    def select(table, **kwargs):
        if table=='task_work_sessions': raise RuntimeError('PGRST205: schema cache')
        return original(table,**kwargs)
    runtime.service_client.select=select
    response=client.get(f"/v2/day/tasks/{task['id']}/work",headers=APP_KEY)
    assert response.status_code==409 and '0035' in response.text
    assert client.get('/v2/day?date=2026-10-02',headers=APP_KEY).status_code==200


def test_exact_split_budget_ignores_stale_marker_after_estimate_edit():
    assert planned_seconds({'estimated_minutes':1,'metadata':{'_work_budget':{'minutes':1,'seconds':43}}})==43
    assert planned_seconds({'estimated_minutes':2,'metadata':{'_work_budget':{'minutes':1,'seconds':43}}})==120


def test_general_split_uses_scoped_atomic_rpc_and_stable_request(client, runtime):
    task = add_task(runtime)
    calls = []
    runtime.service_client.rpc = lambda name, payload: calls.append((name, payload)) or {'first_id': str(uuid4()), 'second_id': str(uuid4())}
    body = {'request_id': str(uuid4()), 'first_seconds': 5400, 'expected_remaining': 10800}
    assert client.post(f"/v2/day/tasks/{task['id']}/split", json=body).status_code == 401
    response = client.post(f"/v2/day/tasks/{task['id']}/split", headers=APP_KEY, json=body)
    assert response.status_code == 200, response.text
    name, payload = calls[0]
    assert name == 'planner_split_task'
    assert payload == {'p_user_id': str(USER_ID), 'p_workspace_id': str(WORKSPACE_ID), 'p_request_id': body['request_id'], 'p_task_id': task['id'], 'p_first_seconds': 5400, 'p_expected_remaining': 10800}


def test_general_split_rejects_bad_input_and_reports_missing_migration(client, runtime):
    task = add_task(runtime)
    body = {'request_id': str(uuid4()), 'first_seconds': 10800, 'expected_remaining': 10800}
    assert client.post(f"/v2/day/tasks/{task['id']}/split", headers=APP_KEY, json=body).status_code == 400
    body['first_seconds'] = 5400
    def rpc(name, payload):
        raise RuntimeError('PGRST202: function missing from schema cache')
    runtime.service_client.rpc = rpc
    response = client.post(f"/v2/day/tasks/{task['id']}/split", headers=APP_KEY, json=body)
    assert response.status_code == 409 and '0036' in response.text
    assert client.post('/v2/day/tasks/not-a-uuid/split', headers=APP_KEY, json=body).status_code == 422


def test_general_split_reports_stale_state_without_creating_tasks(client, runtime):
    task = add_task(runtime)
    before = list(runtime.service_client.tables['planner_tasks'])
    def rpc(name, payload):
        raise RuntimeError('SPLIT_INVALID: The remaining work changed. Refresh before splitting.')
    runtime.service_client.rpc = rpc
    response = client.post(f"/v2/day/tasks/{task['id']}/split", headers=APP_KEY, json={'request_id': str(uuid4()), 'first_seconds': 5400, 'expected_remaining': 10800})
    assert response.status_code == 400 and 'remaining work changed' in response.text
    assert runtime.service_client.tables['planner_tasks'] == before
