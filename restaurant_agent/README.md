# Restaurant table agent (Ontopo)

Ask Claude in any session on this repo, e.g. from the phone:

> Indian restaurant, 4 people, Friday 20:00, Tel Aviv

Claude (via the `book-table` skill in `.claude/skills/`) searches Ontopo, lists
restaurants with free tables, and after you pick one, holds it for ~10 minutes and
sends you the checkout link. You confirm on your phone (details + card guarantee).

## Why it works this way
- **Direct API, not page clicking**: ontopo.com is a front end over a JSON API; calling
  it is faster and less fragile than driving a browser. Python stdlib only, so it runs in
  any fresh cloud session with nothing to install.
- **Categories**: words matching Ontopo's own filters (cuisine, dietary, "moments") are
  filtered server-side. Others (e.g. *indian*, *chinese*, *georgian*) are matched as
  keywords in venue name/tags (strong) or description (weak, flagged).
- **Stops at the hold**: final confirmation needs your personal details and a credit card
  guarantee, so you finish it yourself.
- **Tabit**: not included; its site rejects automated requests from the cloud environment.

## Manual use
```bash
python3 restaurant_agent/ontopo_agent.py cities
python3 restaurant_agent/ontopo_agent.py search --city tel-aviv --category asian,vegetarian \
        --date 2026-11-20 --time 20:00 --size 2
python3 restaurant_agent/ontopo_agent.py hold --page 36960535 --date 2026-11-20 --time 20:00 --size 2
```
Add `--json` for machine-readable output.
