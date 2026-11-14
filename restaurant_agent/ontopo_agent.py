#!/usr/bin/env python3
"""
Ontopo restaurant finder + table holder.

Rationale
---------
Ontopo's website is a thin client over a small JSON API, so we talk to that API
directly (stdlib only -> runs anywhere with Python 3.8+, nothing to install):

  1. POST /api/loginAnonymously           -> anonymous JWT (sent as header "token")
  2. POST /api/search_token               -> search_id for {city, date, time, size, filters}
  3. POST /api/search_request (repeated)  -> pages of venues incl. live availability
  4. GET  /api/slug_content               -> venue details (address, tags, price, about)
  5. POST /api/availability_search        -> venue availability; called again with an
                                             "area" it places a ~10 min HOLD and returns
                                             a checkout_id -> https://s1.ontopo.com/<loc>/checkout/<id>

The script deliberately stops at the hold: the checkout page asks for personal
details and a credit-card guarantee (no-show fee), which the user completes
themselves on their phone.

Categories: words matching Ontopo's own filter tags are sent server-side.
Anything else (e.g. "indian") is matched as a keyword against each venue's
title / tags / venue_type / description.

Usage
-----
  ontopo_agent.py cities
  ontopo_agent.py search --city tel-aviv --category indian --date 2026-11-20 --time 20:00 --size 4
  ontopo_agent.py hold   --page 80548984 --date 2026-11-20 --time 20:00 --size 4 [--area out]
Add --json for machine-readable output.
"""
import argparse
import concurrent.futures as cf
import json
import re
import sys
import urllib.error
import urllib.request

API = "https://ontopo.com/api/"
UA = "Mozilla/5.0 (compatible; personal-table-finder/1.0)"

# Ontopo city slug -> marketplace id (from ontopo.com/<loc>/il/<city> page state)
CITIES = {
    "ashdod": "93786391", "ashkelon": "49787301", "beer-sheva": "83166822",
    "merkaz": "41581793", "eilat": "71154151", "haifa": "11243454",
    "hasharon": "75635900", "hashfela": "74908782", "herzeliya": "62204663",
    "hod_hasharon": "77097784", "holon": "60235869", "jerusalem": "29384685",
    "kfar_saba": "45164735", "kineret": "92127549", "kiryat_ono": "29033809",
    "modiin": "49473533", "ness_ziona": "47865336", "natanya": "19467447",
    "petah_tikva": "74902764", "raanana": "71499188", "ramatgan": "87918421",
    "ramat_hasharon": "64031461", "rehovot": "58943955", "caesarya": "86032396",
    "rishon_lezion": "39514882", "south": "65424368", "tel-aviv": "29421469",
    "the_north": "45577648", "yehud": "53379006",
}
CITY_ALIASES = {
    "tel aviv": "tel-aviv", "tlv": "tel-aviv", "תל אביב": "tel-aviv", "jaffa": "tel-aviv",
    "jerusalem": "jerusalem", "ירושלים": "jerusalem", "haifa": "haifa", "חיפה": "haifa",
    "herzliya": "herzeliya", "הרצליה": "herzeliya", "netanya": "natanya", "נתניה": "natanya",
    "ramat gan": "ramatgan", "givatayim": "ramatgan", "רמת גן": "ramatgan",
    "rishon": "rishon_lezion", "ראשון לציון": "rishon_lezion", "rehovot": "rehovot",
    "רחובות": "rehovot", "modiin": "modiin", "מודיעין": "modiin", "petah tikva": "petah_tikva",
    "פתח תקווה": "petah_tikva", "beer sheva": "beer-sheva", "באר שבע": "beer-sheva",
    "eilat": "eilat", "אילת": "eilat", "raanana": "raanana", "רעננה": "raanana",
    "kfar saba": "kfar_saba", "כפר סבא": "kfar_saba", "holon": "holon", "bat yam": "holon",
    "ness ziona": "ness_ziona", "נס ציונה": "ness_ziona", "caesarea": "caesarya",
    "center": "merkaz", "מרכז": "merkaz", "north": "the_north", "צפון": "the_north",
}

# word (en/he) -> (ontopo filter group, tag value)
FILTERS = {}
def _f(group, value, *words):
    for w in (value,) + words:
        FILTERS[w.lower()] = (group, value)
_f("group1", "italian", "איטלקי", "איטלקית")
_f("group1", "american", "אמריקאי", "אמריקאית")
_f("group1", "asian", "asiatic", "אסייתי", "אסייתית", "אסיאתי")
_f("group1", "mediterranean", "ים תיכוני", "ים תיכונית")
_f("group1", "greek", "יווני", "יוונית")
_f("group1", "japanese", "יפני", "יפנית")
_f("group1", "israeli", "ישראלי", "ישראלית")
_f("group1", "east-european", "east european", "מזרח אירופאי")
_f("group1", "local", "מקומי")
_f("group1", "mexican", "מקסיקני", "מקסיקנית")
_f("group1", "thai", "תאילנדי", "תאילנדית")
_f("group1", "dairy", "חלבי", "חלבית")
_f("group1", "meat", "בשרי", "בשרית", "steak", "סטייק")
_f("group1", "fish", "דגים")
_f("group1", "pizza", "פיצה")
_f("group1", "burger", "המבורגר")
_f("group1", "sushi", "סושי")
_f("group1", "seafood", "פירות ים")
_f("group1", "tapas", "טאפאס")
_f("group1", "bistro", "ביסטרו")
_f("group3", "chef", "שף", "chef restaurant")
_f("group3", "romantic", "רומנטי", "date")
_f("group3", "fine_dining", "fine dining")
_f("group3", "tasting_menu", "tasting menu")
_f("group3", "brunch", "בראנץ'")
_f("group3", "kids", "family", "משפחתי")
_f("group3", "wine_bar", "wine bar", "בר יין")
_f("group3", "cocktail_bar", "cocktail bar")
_f("group3", "business", "business lunch")
_f("group6", "kosher", "כשר", "כשרה")
_f("group6", "vegetarian", "צמחוני", "צמחונית")
_f("group6", "vegan", "טבעוני", "טבעונית")
_f("group6", "gluten_free", "gluten free", "ללא גלוטן")

# categories without an Ontopo filter -> keywords searched in venue text
KEYWORDS = {
    "indian": ["indian", "הודי", "הודית", "tandoor", "masala", "biryani"],
    "chinese": ["chinese", "סיני", "סינית", "dim sum", "peking"],
    "vietnamese": ["vietnam", "וייטנאמי", "pho"],
    "korean": ["korean", "קוריאני", "קוריאנית"],
    "french": ["french", "צרפתי", "צרפתית", "brasserie"],
    "spanish": ["spanish", "ספרדי", "ספרדית"],
    "georgian": ["georgian", "גאורגי", "גאורגית", "khachapuri"],
    "ethiopian": ["ethiopian", "אתיופי", "אתיופית"],
    "yemenite": ["yemen", "תימני", "תימנית"],
    "middle eastern": ["middle east", "מזרחי", "מזרחית", "levant"],
    "ramen": ["ramen", "ראמן"],
    "hummus": ["hummus", "חומוס"],
}
_KW_ALIASES = {"הודי": "indian", "הודית": "indian", "סיני": "chinese", "סינית": "chinese"}


def http(method, path, body=None, token=None):
    headers = {"Accept": "application/json", "User-Agent": UA}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token:
        headers["token"] = token
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Ontopo API error {e.code} on {path}: {e.read().decode()[:300]}")
    return json.loads(txt) if txt.strip() else {}


def login():
    return http("POST", "loginAnonymously", {})["jwt_token"]


def norm_date(s):
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})", s.strip())
    if not m:
        raise SystemExit(f"Bad date '{s}', use YYYY-MM-DD")
    return "".join(m.groups())


def norm_time(s):
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})", s.strip())
    if not m:
        raise SystemExit(f"Bad time '{s}', use HH:MM")
    return f"{int(m.group(1)):02d}{m.group(2)}"


def fmt_time(t):
    return f"{t[:2]}:{t[2:]}"


def resolve_city(c):
    k = c.strip().lower()
    k = CITY_ALIASES.get(k, k).replace(" ", "_")
    if k in CITIES:
        return k
    if k.replace("_", "-") in CITIES:
        return k.replace("_", "-")
    raise SystemExit(f"Unknown city '{c}'. Run 'cities' to list them.")


def resolve_categories(cats):
    """Split user words into server filters and free-text keywords."""
    filters, keywords, labels = {}, [], []
    for c in cats:
        w = c.strip().lower()
        if not w:
            continue
        if w in FILTERS:
            g, v = FILTERS[w]
            filters.setdefault(g, []).append(v)
            labels.append(v)
        else:
            key = _KW_ALIASES.get(w, w)
            keywords.append(KEYWORDS.get(key, [key]))
            labels.append(key)
    return filters, keywords, labels


def venue_details(post):
    p = post["post"]
    try:
        return http("GET", f"slug_content?slug={p['slug']}&version={p.get('version','')}&locale=en")
    except SystemExit:
        return {}


def slots(post):
    out = []
    for area in (post.get("availability") or {}).get("areas", []) or []:
        for o in area.get("options", []):
            if o.get("method") == "seat":
                out.append({"time": o["time"], "area_id": area.get("id"), "area": area.get("name")})
    return out


def search(city, cats, date, time, size, locale="en", max_pages=40, limit=15):
    city = resolve_city(city)
    date, time = norm_date(date), norm_time(time)
    filters, keywords, labels = resolve_categories(cats)
    tok = login()
    body = {"marketplace_id": CITIES[city],
            "criteria": {"date": date, "time": time, "size": str(size)},
            "locale": locale, "traits": ["reservation"], **filters}
    sid = http("POST", "search_token", body, tok)["search_id"]

    posts, seen = [], set()
    for _ in range(max_pages):  # each call returns the next page (~13 venues)
        page = http("POST", "search_request", {"search_id": sid}, tok).get("posts", [])
        if not page:
            break
        for p in page:
            if p["post"]["slug"] not in seen:
                seen.add(p["post"]["slug"])
                posts.append(p)

    candidates = [p for p in posts if slots(p)]
    # Details are needed for display, and for keyword categories also for matching
    pool = candidates if keywords else candidates[: limit * 2]
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        details = list(ex.map(venue_details, pool))

    results = []
    for p, d in zip(pool, details):
        strong_txt = " ".join(str(x) for x in [
            d.get("title"), d.get("tag1"), d.get("tag2"), d.get("tag3"),
            " ".join(d.get("venue_type") or []), p["post"].get("venue_name")]).lower()
        weak_txt = str(d.get("about_us") or "").lower()
        match = "filter"
        if keywords:
            # every category must match (AND); any synonym of a category counts (OR)
            strong = all(any(k in strong_txt for k in grp) for grp in keywords)
            weak = all(any(k in strong_txt or k in weak_txt for k in grp) for grp in keywords)
            if not weak:
                continue
            match = "tags" if strong else "mentioned in description only"
        page_slug = p["post"].get("page_slug") or (d.get("call_to_action") or {}).get("slug")
        results.append({
            "name": d.get("title") or p["post"].get("venue_name"),
            "match": match,
            "address": d.get("address"),
            "tags": ", ".join(t for t in [d.get("tag1"), d.get("tag2"), d.get("tag3")] if t),
            "price": d.get("venue_price"),
            "phone": d.get("phone"),
            "page": page_slug,
            "slots": slots(p),
            "url": f"https://ontopo.com/{locale}/il/page/{page_slug}?date={date}&time={time}&size={size}",
        })
    results.sort(key=lambda v: v["match"].startswith("mentioned"))  # strong matches first
    results = results[:limit]
    return {"city": city, "date": date, "time": time, "size": size, "categories": labels,
            "scanned": len(posts), "with_tables": len(candidates), "results": results}


def hold(page, date, time, size, area=None, locale="en"):
    """Place a temporary hold (~10 min) and return the checkout link. Does NOT book."""
    date, time = norm_date(date), norm_time(time)
    tok = login()
    data = {"analytics": {"market_id": "", "platform": "web", "distributor_id": "il",
                          "origin": "venue_page"}}
    crit = {"date": date, "time": time, "size": str(size)}
    av = http("POST", "availability_search",
              {"slug": str(page), "locale": locale, "criteria": crit, "data": data}, tok)
    areas = av.get("areas") or []
    exact = [a for a in areas
             if any(o.get("time") == time and o.get("method") == "seat" for o in a.get("options", []))]
    if area:
        exact = [a for a in exact if a.get("id") == area or (a.get("name") or "").lower() == area.lower()]
    if not exact:
        free = sorted({(a.get("name"), o["time"]) for a in areas for o in a.get("options", [])
                       if o.get("method") == "seat"})
        raise SystemExit("No bookable table at that exact time/area. Free slots: " +
                         (", ".join(f"{fmt_time(t)} ({n})" for n, t in free) or "none"))
    chosen = exact[0]
    res = http("POST", "availability_search",
               {"slug": str(page), "locale": locale, "criteria": {**crit, "area": chosen["id"]},
                "availability_id": av.get("availability_id"), "data": data}, tok)
    cid = res.get("checkout_id")
    if not cid:
        raise SystemExit(f"Hold failed: {json.dumps(res)[:300]}")
    return {"checkout_url": f"https://s1.ontopo.com/{locale}/checkout/{cid}",
            "area": chosen.get("name"), "date": date, "time": fmt_time(time), "size": size,
            "note": "Table is held ~10 minutes. Open the link to enter your details and confirm."}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cities")
    s = sub.add_parser("search")
    s.add_argument("--city", required=True)
    s.add_argument("--category", action="append", default=[],
                   help="repeatable, e.g. --category asian --category vegetarian")
    s.add_argument("--date", required=True)
    s.add_argument("--time", required=True)
    s.add_argument("--size", type=int, required=True)
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--locale", default="en", choices=["en", "he"])
    h = sub.add_parser("hold")
    h.add_argument("--page", required=True, help="page id from search results")
    h.add_argument("--date", required=True)
    h.add_argument("--time", required=True, help="exact slot time from search results")
    h.add_argument("--size", type=int, required=True)
    h.add_argument("--area", help="area id or name (optional)")
    h.add_argument("--locale", default="en", choices=["en", "he"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.cmd == "cities":
        print(json.dumps(CITIES, indent=1) if a.json else "\n".join(sorted(CITIES)))
        return
    if a.cmd == "search":
        cats = [w for c in a.category for w in re.split(r"[,/]", c)]
        r = search(a.city, cats, a.date, a.time, a.size, a.locale, limit=a.limit)
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return
        print(f"{r['city']} | {r['date']} {fmt_time(r['time'])} | {r['size']} ppl | "
              f"{', '.join(r['categories']) or 'any'} | scanned {r['scanned']}, "
              f"{r['with_tables']} with free tables, {len(r['results'])} match")
        for i, v in enumerate(r["results"], 1):
            times = sorted({s["time"] for s in v["slots"]})
            areas = sorted({s["area"] for s in v["slots"] if s["area"]})
            weak = "  (!) " + v["match"] if v["match"].startswith("mentioned") else ""
            print(f"\n{i}. {v['name']}  {v['price'] or ''}  [{v['tags']}]{weak}")
            print(f"   {v['address']}")
            print(f"   free: {' '.join(fmt_time(t) for t in times)}   areas: {', '.join(areas)}")
            print(f"   page={v['page']}  {v['url']}")
        return
    r = hold(a.page, a.date, a.time, a.size, a.area, a.locale)
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else
          f"HELD {r['date']} {r['time']} for {r['size']} ({r['area']})\n{r['checkout_url']}\n{r['note']}")


if __name__ == "__main__":
    main()
