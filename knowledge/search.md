# Web Search

## search_web

**When to use:** User needs current info, news, facts, docs, or anything you don't have in memory.

**How:**
- `query`: Search string (e.g. "Python asyncio tutorial", "weather NYC").
- `max_results`: Optional, default 8.

**Examples:**
- Lookup: `search_web("xAI Grok API documentation")`
- Current events: `search_web("latest Python release 2025")`
- Troubleshoot: `search_web("Windows error 10048 fix")`

**Tips:** Use for real-time or recent information. Combine with other tools: search for the fix, then run_command to apply it.
