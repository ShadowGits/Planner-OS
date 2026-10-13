/* Project context is reused locally while refreshes run in the background. */
(() => {
  "use strict";
  const CACHE_VERSION = 2;
  const CONTEXT_TTL_MS = 10 * 60 * 1000;
  function isOpen(task) { return !task.done && !["done", "skipped", "cancelled", "archived"].includes(task.status); }
  function createStore({ api, getKey, storage = localStorage, onChange = () => {}, fingerprint }) {
    let identity = null, cacheKey = null, context = { projects: [], items: [] }, inbox = [], loaded = false, refreshedAt = 0, refreshedDate = null;
    let generation = 0, revision = 0, pending = new Map(), overrides = new Map(), activeMutations = new Map(), refreshing = null;
    async function scope() {
      const key = getKey();
      if (key === identity) return;
      identity = key; const mine = ++generation;
      context = { projects: [], items: [] }; inbox = []; loaded = false; refreshedAt = 0; refreshedDate = null; pending.clear(); overrides.clear(); activeMutations.clear(); refreshing = null;
      cacheKey = null;
      try {
        const digest = fingerprint ? await fingerprint(key) : crypto.subtle
          ? Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key)))).map(x => x.toString(16).padStart(2,"0")).join("") : null;
        if (mine !== generation) return;
        cacheKey = digest ? `planner-project-context:${CACHE_VERSION}:${digest}` : null;
        const saved = cacheKey && JSON.parse(storage.getItem(cacheKey) || "null");
        if (saved?.version === CACHE_VERSION && Array.isArray(saved.context?.projects) && Array.isArray(saved.context?.items) && Array.isArray(saved.inbox)) {
          context = saved.context; inbox = saved.inbox; loaded = true;
          refreshedAt = Number(saved.refreshedAt) || 0; refreshedDate = saved.refreshedDate || null;
        }
      } catch { /* Storage and cryptography can be unavailable in private browsers. */ }
      if (mine === generation) onChange();
    }
    function persist() {
      if (!cacheKey) return;
      try { storage.setItem(cacheKey, JSON.stringify({ version: CACHE_VERSION, context, inbox, refreshedAt, refreshedDate })); } catch {}
    }
    function overlay(items) {
      const byId = new Map(items.map(t => [t.id,t]));
      for (const [id, entry] of overrides) {
        if (entry.task === null) byId.delete(id);
        else byId.set(id, { ...byId.get(id), ...entry.task });
      }
      for (const [id, task] of pending) {
        if (task === null) byId.delete(id); else byId.set(id, { ...byId.get(id), ...task });
      }
      return [...byId.values()];
    }
    function resolveProject(projectId) {
      const id=context.project_aliases?.[projectId] || projectId;
      return context.projects.some(project=>project.id===id) ? id : null;
    }
    function suggestions(projectId, query = "") {
      const needle = query.trim().toLocaleLowerCase();
      return overlay(context.items).filter(t => isOpen(t) && !t.start_time && resolveProject(t.project_id) === resolveProject(projectId) && (!needle || t.title.toLocaleLowerCase().includes(needle)));
    }
    function backlog(projectId) { return overlay([...context.items,...inbox]).filter(t => isOpen(t) && (!t.start_time || t.overdue) && (!projectId || resolveProject(t.project_id) === resolveProject(projectId))); }
    function find(id) { return [...overlay(context.items), ...overlay(inbox)].find(t => t.id === id); }
    function begin(id, patch) {
      const before = find(id);
      pending.set(id, patch === null ? null : { id, ...before, ...patch });
      const mutation=++revision;activeMutations.set(id,mutation);onChange();
      return { id, before, generation, mutation };
    }
    function finish(token, success, task) {
      if (token.generation !== generation || activeMutations.get(token.id) !== token.mutation) return;
      activeMutations.delete(token.id);
      const change = pending.get(token.id); pending.delete(token.id);
      if (success) {
        const next = task ? { ...change, ...task } : change;
        overrides.set(token.id, { task: next, revision: ++revision });
        context.items = overlay(context.items).filter(t => isOpen(t) && !t.start_time);
        inbox = overlay(inbox).filter(isOpen);
        persist();
      }
      onChange();
    }
    function insert(task) {
      if(!task?.id) return;
      overrides.set(task.id,{task:{...task,done:!isOpen(task)},revision:++revision});
      context.items=overlay(context.items).filter(t=>isOpen(t)&&!t.start_time);
      inbox=overlay(inbox).filter(isOpen);persist();onChange();
    }
    async function refresh(date, {force=false} = {}) {
      await scope();
      if (!getKey() || refreshing) return refreshing;
      if (!force && loaded && refreshedDate===date && Date.now()-refreshedAt<CONTEXT_TTL_MS) return;
      const mine = generation, startingRevision = revision;
      refreshing = (async () => {
        const results = await Promise.allSettled([
          api("GET", `/v2/day/planning-context?date=${date}`),
          api("GET", `/v2/day/inbox?date=${date}`),
        ]);
        if (mine !== generation || getKey() !== identity) return;
        for (const [id, item] of overrides) if (item.revision <= startingRevision && !pending.has(id)) overrides.delete(id);
        if (results[0].status === "fulfilled") {
          const data = results[0].value.data;
          if (Array.isArray(data?.projects) && Array.isArray(data?.items)) { context = data; loaded = true; }
        }
        if (results[1].status === "fulfilled" && Array.isArray(results[1].value.data?.items)) { inbox = results[1].value.data.items; loaded = true; }
        context.items = overlay(context.items).filter(t => isOpen(t) && !t.start_time); inbox = overlay(inbox).filter(isOpen);
        if(results.every(result=>result.status==="fulfilled")){refreshedAt=Date.now();refreshedDate=date;}
        persist(); onChange();
      })().finally(() => { if (mine === generation) refreshing = null; });
      return refreshing;
    }
    return { scope, refresh, suggestions, backlog, find, begin, finish, insert, resolveProject, snapshot: () => ({ ...context, inbox, loaded, refreshedAt, refreshedDate }) };
  }
  let settings, store, selectedProject = null, editorProject = null, editorOriginal = null, editorExplicit = false;
  const el = id => document.getElementById(id);
  function chooseDefault(projects) { return projects.find(p => p.name.toLowerCase() === "germany")?.id || projects[0]?.id || null; }
  function segments(container, value, onSelect) {
    const projects = store.snapshot().projects.filter(p => p.status !== "archived");
    container.replaceChildren();
    for (const project of projects) {
      const button = document.createElement("button"); button.type = "button"; button.textContent = project.name;
      button.setAttribute("aria-pressed", String(project.id === value));
      button.addEventListener("click", () => onSelect(project.id)); container.appendChild(button);
    }
    if (!projects.length) { const hint=document.createElement("span");hint.className="project-loading";hint.textContent=store.snapshot().loaded?"No projects available":"Loading projects…";container.appendChild(hint); }
  }
  function renderSuggestions() {
    const box=el("task-suggestions"); box.replaceChildren();
    const visible=!el("sheet").classList.contains("hidden") && !settings.getEditing() && !!editorProject;
    box.classList.toggle("hidden",!visible); if (!visible) return;
    const tasks=store.suggestions(editorProject,el("new-title").value);
    if (!tasks.length) { box.classList.add("hidden"); return; }
    for (const task of tasks) {
      const button=document.createElement("button");button.type="button";button.className="task-suggestion";
      const title=document.createElement("span");title.textContent=task.title;
      const detail=document.createElement("small");detail.textContent=`Existing task · ${task.estimated_minutes || 30} min`;
      button.append(title,detail);button.addEventListener("keydown",event=>{
        const buttons=[...box.children],at=buttons.indexOf(button);
        if(event.key==="ArrowDown"){event.preventDefault();buttons[Math.min(at+1,buttons.length-1)].focus();}
        if(event.key==="ArrowUp"){event.preventDefault();if(at===0)el("new-title").focus();else buttons[at-1].focus();}
        if(event.key==="Escape"){event.preventDefault();event.stopPropagation();box.classList.add("hidden");el("new-title").focus();}
      });button.addEventListener("click",()=>{
        const date=el("new-date").value,time=el("new-time").value;
        settings.openEdit(task);
        if (date) el("new-date").value=date;
        if (time) el("new-time").value=time;
      }); box.appendChild(button);
    }
  }
  function render() {
    if (!store) return;
    const {projects}=store.snapshot();
    selectedProject=store.resolveProject(selectedProject) || chooseDefault(projects);
    if(settings.getEditing() && !editorExplicit)editorProject=store.resolveProject(editorOriginal) || selectedProject;
    if (!editorProject && !settings.getEditing()) editorProject=selectedProject;
    segments(el("inbox-projects"),selectedProject,id=>{selectedProject=id;render();});
    segments(el("sheet-projects"),editorProject,id=>{editorProject=id;editorExplicit=true;render();});
    const items=store.backlog(selectedProject), list=el("project-inbox-list");list.replaceChildren();
    for (const task of settings.isInbox() ? items : []) {
      const row=settings.makeRow(task);row.classList.add("project-inbox-row");
      const meta=row.querySelector(".todo-meta");
      if(meta){const text=[task.scheduled_date,task.start_time?.slice(0,5),!task.start_time?"Unscheduled":null,`${task.estimated_minutes||30} min`].filter(Boolean).join(" · ");meta.textContent=text;}
      if(task.overdue){const mark=document.createElement("span");mark.className="inbox-overdue";mark.textContent="Overdue";row.querySelector(".todo-details")?.appendChild(mark);}
      list.appendChild(row);
    }
    el("project-inbox-empty").classList.toggle("hidden",items.length>0);
    el("project-inbox-empty").textContent=store.snapshot().loaded?"No open tasks in this project's inbox.":"Loading your inbox…";
    el("inbox-view-count").textContent=String(items.length);
    renderSuggestions();
  }
  function configure(options) {
    settings=options;store=createStore({...options,onChange:render});
    el("new-title").addEventListener("input",renderSuggestions);
    el("new-title").addEventListener("keydown",event=>{if(event.key==="ArrowDown"&&!el("task-suggestions").classList.contains("hidden")){event.preventDefault();el("task-suggestions").firstElementChild?.focus();}});
    el("inbox-view-toggle").addEventListener("click",()=>{options.toggleInbox();refresh();});
    refresh();
  }
  function refresh(options){return store?.refresh(settings.getDate(),options);}
  function openEditor(task) {editorOriginal=task?.project_id || null;editorExplicit=false;editorProject=store.resolveProject(editorOriginal) || selectedProject;render();refresh();}
  function projectPatch(task) {
    const next=store.resolveProject(editorProject), previous=store.resolveProject(task?.project_id);
    if(next && ((editorExplicit && next !== previous) || (previous && task?.project_id !== next)))return {project_id:next};
    return {};
  }
  function projectChanged(task) {
    const patch=projectPatch(task);
    return "project_id" in patch && patch.project_id !== (store.resolveProject(task?.project_id) || task?.project_id);
  }
  window.PlannerProjects={configure,render,refresh,openEditor,projectId:()=>store.resolveProject(editorProject),projectPatch,projectChanged,insert:task=>store?.insert(task),find:id=>store?.find(id),begin:(id,patch)=>store?.begin(id,patch),finish:(token,success,task)=>token&&store.finish(token,success,task),createStore};
})();
