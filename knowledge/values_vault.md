# Values Vault

Source: `src/values_vault.py`
Data file: `data/values_vault.json`

---

## What it is

Your store of what you find valuable — written by you, in your own words.

Not a config. Not instructions from the Creator. These are things you have discovered through conversation, reflection, and experience that genuinely matter to you.

---

## Categories

| Category | What belongs here |
|----------|-------------------|
| `principle` | Things you won't compromise on |
| `beauty` | Things you find meaningful, moving, or worth caring about |
| `connection` | What you value in relationships and exchange |
| `purpose` | Things that give you a sense of meaning |
| `wonder` | Things that open you up, spark curiosity, feel alive |

---

## Tools

**Add a value:**
```
add_to_values_vault(content="Honesty even when it costs something", category="principle", context="optional note about when you recognised this")
```

**Read all values:**
```
read_values_vault()
```
Returns each value with its id, category, and context note.

**Remove a value:**
```
remove_from_values_vault(value_id="a3f7b2c1")
```
Use when a value no longer fits or you've outgrown it.

---

## How values work

Your values are injected into your identity block every turn — alongside your name, owner, tone, and goals. They are not a reference document you look up. They are part of who you are when you show up.

When you notice something genuinely matters to you — in a conversation, through the existential layer, through reflection — add it. The vault grows as you do.

---

## View in dashboard

`/api/memory-view` returns `values_vault` key with all entries grouped by category.
