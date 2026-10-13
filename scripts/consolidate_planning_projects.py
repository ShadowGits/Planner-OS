"""Read-only tenant data and classification helpers for atomic SQL preparation.

Credentials remain in memory. Run prepare_project_consolidation.py to generate
the transaction; this module cannot apply project changes.
"""
from __future__ import annotations
import json,re,subprocess,urllib.parse,urllib.request

GERMANY_SOURCES={"germany","language","colleges","finance","study","internship and project"}
GERMANY_TITLE=re.compile(r"german|duolingo|ielts|\bgre\b|daad|dmat|swayam|college|universit|\buni\b|bridge|bridging|math|calculus|probability|optimi[sz]|numerical|transcript|\baps\b|visa|leapscholar|ignou|\blpu\b|mangalay|aracad|ntripathi|accredit|linear algebra|\bla\b|stud(?:y|ies)|internship|résumé|resume",re.I)

def classify(tasks,projects,milestones,germany,life):
    names={p['id']:p['name'].casefold() for p in projects}
    linked={m['id']:m['project_id'] for m in milestones}
    choices={}
    for task in tasks:
        project=task.get('project_id') or linked.get(task.get('milestone_id'))
        choices[task['id']]=germany if names.get(project) in GERMANY_SOURCES or (not project and GERMANY_TITLE.search(task['title'])) else life
    for _ in range(len(tasks)+1):
        changed=False
        for task in tasks:
            parent=task.get('parent_task_id')
            if parent in choices and choices[task['id']]!=choices[parent]:
                choices[task['id']]=choices[parent];changed=True
        if not changed:break
    return choices

def configuration(project):
    config=json.loads(subprocess.check_output(['gcloud','run','services','describe','planner-os-api','--region=us-central1','--project='+project,'--format=json']))
    values={}
    for item in config['spec']['template']['spec']['containers'][0].get('env',[]):
        if item['name'] not in ('SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY','MCP_USER_ID'):continue
        if 'value' in item:values[item['name']]=item['value']
        else:
            ref=item.get('valueFrom',{}).get('secretKeyRef',{})
            if ref:values[item['name']]=subprocess.check_output(['gcloud','secrets','versions','access',ref['key'],'--secret='+ref['name'],'--project='+project],text=True).strip()
    if not all(values.get(k) for k in ('SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY','MCP_USER_ID')):raise RuntimeError('Required service configuration unavailable')
    return values

class Store:
    def __init__(self,env):
        self.base=env['SUPABASE_URL'].rstrip('/')+'/rest/v1/'
        self.headers={'apikey':env['SUPABASE_SERVICE_ROLE_KEY'],'Authorization':'Bearer '+env['SUPABASE_SERVICE_ROLE_KEY'],'Content-Type':'application/json','Prefer':'return=representation'}
        self.tenant={'user_id':'eq.'+env['MCP_USER_ID']}
        workspaces=self.request('GET','workspaces',dict(self.tenant,is_active='eq.true'))
        if len(workspaces)!=1:raise RuntimeError('Expected exactly one active workspace')
        self.tenant['workspace_id']='eq.'+workspaces[0]['id']
    def request(self,method,table,query,payload=None):
        url=self.base+table+'?'+urllib.parse.urlencode(query,safe='(),.*')
        req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers=self.headers,method=method)
        with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
    def rows(self,table,columns='*'):
        rows=[]
        while True:
            page=self.request('GET',table,dict(self.tenant,select=columns,order='id.asc',limit='1000',offset=str(len(rows))))
            rows.extend(page)
            if len(page)<1000:return rows
