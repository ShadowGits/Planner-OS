"""Project picker context and identity-preserving task reassignment."""
from tests.test_planner_core import services, repo, USER_ID, WORKSPACE_ID
from uuid import uuid4
import pytest
from planner_core.repository import PlannerCoreError


def test_context_includes_future_loose_tasks_but_not_closed_scheduled_or_split_roots(services):
    tasks, projects, _, _ = services
    project=projects.create_project("Germany")["data"]["project"]
    future=tasks.create_task("Future loose", project_id=project["id"], scheduled_date="2030-01-01")["data"]["task"]
    timed=tasks.create_task("Timed", project_id=project["id"], scheduled_date="2030-01-01", start_time="09:00")["data"]["task"]
    closed=tasks.create_task("Closed", project_id=project["id"])["data"]["task"]
    tasks.complete_task(closed["id"])
    root=tasks.create_task("Split root", project_id=project["id"])["data"]["task"]
    child=tasks.create_task("Loose child", project_id=project["id"],parent_task_id=root["id"])["data"]["task"]
    foreign={**future,"id":str(uuid4()),"user_id":str(uuid4()),"workspace_id":str(uuid4())}
    tasks.repository.gateway.insert("planner_tasks", foreign)
    result=tasks.planning_context()["data"]
    assert {t["id"] for t in result["items"]}=={future["id"],child["id"]}
    assert result["projects"]==[{"id":project["id"],"name":"Germany","status":"active"}]


def test_changing_project_preserves_identity_history_and_detaches_incompatible_milestone(services):
    tasks,projects,_,_=services
    germany=projects.create_project("Germany")["data"]["project"]["id"]
    life=projects.create_project("Life other than Germany")["data"]["project"]["id"]
    milestone=projects.add_milestone(germany,"A1")["data"]["milestone"]["id"]
    original=tasks.create_task("Study",project_id=germany,milestone_id=milestone,notes="Keep notes")["data"]["task"]
    tasks.complete_task(original["id"])
    result=tasks.update_task(original["id"],{"project_id":life})["data"]["task"]
    assert result["id"]==original["id"] and result["notes"]=="Keep notes"
    assert result["status"]=="done" and result["milestone_id"] is None
    assert len(tasks.repository.list_rows("task_completions"))==1
    with pytest.raises(PlannerCoreError,match="selected project"):
        tasks.update_task(original["id"],{"milestone_id":milestone,"project_id":life})


def test_project_change_rejects_foreign_project_before_writing(services):
    tasks,projects,_,_=services
    original=tasks.create_task("Own")["data"]["task"]
    foreign=str(uuid4())
    tasks.repository.gateway.insert("projects",{"id":foreign,"user_id":str(uuid4()),"workspace_id":str(uuid4()),"name":"Foreign"})
    with pytest.raises(PlannerCoreError,match="workspace"):
        tasks.update_task(original["id"],{"project_id":foreign})
    assert tasks.repository.get_row("planner_tasks",original["id"])["project_id"] is None


def test_milestone_can_move_project_without_recreation(services):
    tasks,projects,_,_=services
    old=projects.create_project("Language")["data"]["project"]["id"]
    new=projects.create_project("Germany")["data"]["project"]["id"]
    milestone=projects.add_milestone(old,"A1")["data"]["milestone"]
    updated=projects.update_milestone(milestone["id"],{"project_id":new})["data"]["milestone"]
    assert updated["id"]==milestone["id"] and updated["project_id"]==new


def test_linking_milestone_without_explicit_project_retains_dashboard_workflow(services):
    tasks,projects,_,_=services
    project=projects.create_project("Germany")["data"]["project"]["id"]
    milestone=projects.add_milestone(project,"Visa")["data"]["milestone"]["id"]
    task=tasks.create_task("Appointment")["data"]["task"]
    result=tasks.update_task(task["id"],{"milestone_id":milestone})["data"]["task"]
    assert result["project_id"]==project and result["milestone_id"]==milestone


def test_context_resolves_retained_source_projects_without_archiving_them(services):
    tasks, projects, _, _ = services
    ids = {
        name: projects.create_project(name)["data"]["project"]["id"]
        for name in ("Germany", "Life other than Germany", "Study", "Fitness")
    }
    context = tasks.planning_context()["data"]
    assert {row["name"] for row in context["projects"]} == {"Germany", "Life other than Germany"}
    assert context["project_aliases"] == {
        ids["Germany"]: ids["Germany"],
        ids["Life other than Germany"]: ids["Life other than Germany"],
        ids["Study"]: ids["Germany"],
        ids["Fitness"]: ids["Life other than Germany"],
    }
    assert len(tasks.repository.list_rows("projects", {"status": "active"})) == 4
