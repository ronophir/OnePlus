---
name: book-table
description: Find a restaurant in Israel on Ontopo by food category (asian, indian, vegetarian, italian, kosher, romantic... in English or Hebrew) for a date, time and party size, then hold the chosen table and give the user the checkout link to confirm. Use when the user asks to find, reserve, book or "invite" a table / restaurant.
---

# Book a table (Ontopo)

Tool: `restaurant_agent/ontopo_agent.py` (Python 3 stdlib, no install). Run from the repo root.

## 1. Collect the request
Need: **category**, **date**, **time**, **party size**, **city**.
- Resolve relative dates ("Friday", "tomorrow") with `TZ=Asia/Jerusalem date`.
- City defaults to `tel-aviv` only if the user has used it before in the conversation; otherwise ask. `python3 restaurant_agent/ontopo_agent.py cities` lists cities.
- Several categories are allowed (`--category asian,vegetarian` = both must apply).

## 2. Search
```
python3 restaurant_agent/ontopo_agent.py search --city <city> --category <cat> --date YYYY-MM-DD --time HH:MM --size N --limit 8
```
Takes ~5-20 s (keyword categories like "indian" scan every venue). Show the user a short numbered list: name, price, tags, address, free times. Results marked `(!) mentioned in description only` are weak matches; say so.

If nothing matches: say it plainly, then offer alternatives (±1 h, another day, a nearby city, or the closest filter category, e.g. asian for indian).

## 3. Hold the chosen table — only after the user picks
```
python3 restaurant_agent/ontopo_agent.py hold --page <page> --date YYYY-MM-DD --time <exact free slot HH:MM> --size N [--area <area name>]
```
Send the `checkout_url` as a clickable link and tell the user the table is held **~10 minutes**; they open it on the phone, enter name/phone and the card guarantee, and confirm.

## Rules
- Never place a hold without the user choosing a specific restaurant and time.
- Never enter the user's personal or payment details anywhere; the user completes checkout themselves.
- Mention the no-show/cancellation fee shown on checkout exists (typically per guest).
- Tabit is not supported (its site blocks automated access from this environment).
