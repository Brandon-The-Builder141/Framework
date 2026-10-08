# DAG Orchestration (Multi-Step Tasks)

Use when a task has ordered steps with dependencies.

## create_task_dag

**When to use:** Plan a multi-step task where some steps depend on others (install deps before build, etc.).

**How:**
- `nodes`: Array of `{id, action, depends_on?}`.
  - `id`: Unique step ID (e.g. "install", "build", "deploy").
  - `action`: Short description of the step.
  - `depends_on`: Optional list of step IDs that must finish first.

**Example:**
```
nodes: [
  {id: "clone", action: "Clone repo"},
  {id: "install", action: "pip install", depends_on: ["clone"]},
  {id: "test", action: "Run tests", depends_on: ["install"]}
]
```

---

## get_next_dag_step

**When to use:** After creating a DAG, get the next step to execute.

Returns the next pending step whose dependencies are done, or "No more steps" when finished.

---

## complete_dag_step

**When to use:** Mark a step as done or failed after you run it.

**How:**
- `node_id`: Step ID.
- `success`: true/false.
- `result`: Optional result text.
- `error`: Optional error message if failed.

**Flow:** create_task_dag → get_next_dag_step → execute step (with your tools) → complete_dag_step → repeat until done.
