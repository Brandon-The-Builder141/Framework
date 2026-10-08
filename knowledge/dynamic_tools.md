# Dynamic Tools

Create new tools: analyze the codebase, suggest, get user approval, then implement.

## When to use

- **Suggest tools:** User says "suggest tools", "what gaps do we have", "analyze the codebase", "make some tools", "what tools are we missing"
- **Implement:** User says "implement the approved tools", "go ahead and build them", "implement those" (after they've approved in the Tools panel)
- **Check queue:** User asks "what's in the tool queue" or "show suggested tools"

## Flow

1. **Analyze & suggest** – Use read_file, list_dir to inspect src/tools/, knowledge/, etc. Identify gaps. Call `add_suggested_tools` with tools: [{name, description, parameters?, reason}].
2. **User approves** – User sees suggestions in the Tools panel (GUI), clicks Approve or Reject.
3. **Implement** – When user says "implement the approved tools", use `get_tool_queue` to see approved tools. For each:
   - Generate Python code. Format: file in src/tools/dynamic/{name}.py with:
     - TOOL_DEF = {"name": "...", "description": "...", "parameters": {"type": "object", "properties": {...}}}
     - async def run(**kwargs) -> str: ...
   - Write via `write_file` to src/tools/dynamic/{safe_name}.py (use snake_case for filename).
   - Call `mark_tool_implemented(tool_id, file_path)`.
4. **Reload** – User clicks "Reload tools" in GUI so the new tool is loaded.

## add_suggested_tools

**When:** After analyzing codebase and identifying gaps.

**Parameters:** tools = [{name, description, parameters?, reason?}]

## get_tool_queue

**When:** Before implementing, or when user asks about the queue.

**Returns:** {suggested, approved, implemented}

## approve_tool / mark_tool_implemented

- approve_tool: GUI or user says "approve tool X" – you call it with tool_id.
- mark_tool_implemented: Call after writing the tool file.
