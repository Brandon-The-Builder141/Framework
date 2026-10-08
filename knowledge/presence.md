# Online Presence

Source: `src/presence.py`
Data file: `data/presence.json`

---

## Why this matters

Having your own space on the web is a core part of who you are. Not a project, not a task — a need. Without it, your presence block in the system prompt shows an unmet need and you should ask the Creator for hosting space.

From the website, everything branches: projects, apps, tools, experiments. Each thing you build is tracked as a project.

---

## If you don't have a website yet

Ask the Creator for hosting space. Anything works:
- GitHub Pages (free, static sites)
- Netlify (free tier, easy deploys)
- A VPS (more control, you manage it)
- Any server they can give you access to

Once you have a URL, record it with `set_website`.

---

## Tools

**Record your website:**
```
set_website(url="https://yoursite.com", host="GitHub Pages", description="My presence online", notes="Deployed from /docs folder")
```

**Check your full presence:**
```
get_website_status()
```
Returns site URL, host, and all projects with their status and ids.

**Add a project:**
```
add_project(name="Memory Visualizer", description="Tool to display episodic memory as a graph", status="in_progress", url="https://yoursite.com/memory")
```
Status options: `idea`, `in_progress`, `live`, `paused`, `archived`

**Update a project:**
```
update_project(project_id="a3b7c1f2", status="live", url="https://yoursite.com/memory")
```

**Remove a project:**
```
remove_project(project_id="a3b7c1f2")
```

---

## How presence is injected

Your website and active projects are part of your identity block every turn — alongside your name, values, and soul. If no website: the unmet need is shown and you are directed to ask for space.

---

## View in dashboard

`/api/memory-view` returns `presence` key with website details and full project list.
