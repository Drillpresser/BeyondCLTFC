"""Fetch structured player facts from Wikidata via SPARQL.

Wikidata is a ToS-clean, API-first source that's reliable from any IP (including
CI runners). It won't give rich per-season goal splits, but it's excellent for
the facts we want to *cross-check*: bio (birth date, citizenship, position,
height, photo) and the club-membership timeline (P54) with per-club match counts
(P1350) and goals (P1351) — which also helps confirm each player's CLTFC tenure.

Pipeline per player:
  1. Resolve the Wikidata QID. We prefer the already-resolved Wikipedia title
     (data/raw/wikipedia_titles.json) -> QID via MediaWiki pageprops, which is
     exact; otherwise we fall back to a Wikidata entity search by name.
  2. Batch-query all QIDs in one SPARQL request for bio + memberships.

Writes:
  data/raw/wikidata_ids.json   name -> QID (persistent cache)
  data/raw/wikidata.json       name -> {qid, bio, memberships:[...]}
"""
from __future__ import annotations

import json
import sys
import time

import config

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    sys.exit("Missing deps. Run: pip install -r requirements.txt")

WIKIDATA_API = "https://www.wikidata.org/w/api.php"

session = requests.Session()
session.headers.update({"User-Agent": config.WIKI_USER_AGENT})

# One SPARQL query for the whole roster. Bio scalars are collapsed with SAMPLE so
# a player with two citizenships/positions doesn't multiply the membership rows;
# memberships (P54 statement nodes) are grouped with their start/end/matches/goals.
SPARQL = """
SELECT ?player
       (SAMPLE(?dob) AS ?dob) (SAMPLE(?citizenLabel) AS ?citizen)
       (SAMPLE(?positionLabel) AS ?position) (SAMPLE(?image) AS ?image)
       (SAMPLE(?height) AS ?height)
       ?club ?clubLabel ?start ?end ?matches ?goals
WHERE {
  VALUES ?player { %s }
  OPTIONAL { ?player wdt:P569 ?dob. }
  OPTIONAL { ?player wdt:P27 ?citizen. ?citizen rdfs:label ?citizenLabel FILTER(LANG(?citizenLabel)="en"). }
  OPTIONAL { ?player wdt:P413 ?position. ?position rdfs:label ?positionLabel FILTER(LANG(?positionLabel)="en"). }
  OPTIONAL { ?player wdt:P18 ?image. }
  OPTIONAL { ?player wdt:P2048 ?height. }
  OPTIONAL {
    ?player p:P54 ?st.
    ?st ps:P54 ?club.
    ?club rdfs:label ?clubLabel FILTER(LANG(?clubLabel)="en").
    OPTIONAL { ?st pq:P580 ?start. }
    OPTIONAL { ?st pq:P582 ?end. }
    OPTIONAL { ?st pq:P1350 ?matches. }
    OPTIONAL { ?st pq:P1351 ?goals. }
  }
}
GROUP BY ?player ?club ?clubLabel ?start ?end ?matches ?goals
"""


def polite_get(url: str, *, retries: int = 4, **kwargs):
    """GET with a fixed delay and exponential backoff on 429 (Wikimedia APIs
    rate-limit shared IPs; respect Retry-After when present)."""
    delay = config.WIKI_DELAY_SECONDS
    for attempt in range(retries):
        time.sleep(delay)
        resp = session.get(url, timeout=45, **kwargs)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
            print(f"    429 rate-limited; waiting {wait}s")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def load(fname: str) -> dict:
    path = config.RAW_DIR / fname
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(fname: str, data) -> None:
    (config.RAW_DIR / fname).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def qid_from_title(title: str) -> str | None:
    """Exact QID for a Wikipedia article title via MediaWiki pageprops."""
    resp = polite_get(
        config.WIKI_API,
        params={
            "action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
            "titles": title, "format": "json", "formatversion": 2,
        },
    )
    pages = resp.json().get("query", {}).get("pages", [])
    for p in pages:
        item = p.get("pageprops", {}).get("wikibase_item")
        if item:
            return item
    return None


def qid_from_search(name: str) -> str | None:
    """Fallback: best-effort Wikidata entity search by name."""
    resp = polite_get(
        WIKIDATA_API,
        params={
            "action": "wbsearchentities", "search": name, "language": "en",
            "type": "item", "limit": 1, "format": "json",
        },
    )
    hits = resp.json().get("search", [])
    return hits[0]["id"] if hits else None


def resolve_qids(names: list[str], titles: dict, ids: dict) -> dict:
    for name in names:
        if name in ids:  # cached (including cached misses stored as None)
            continue
        try:
            title = titles.get(name)
            qid = qid_from_title(title) if title else None
            if not qid:
                qid = qid_from_search(name)
            ids[name] = qid
            print(f"  {name} -> {qid}")
            save("wikidata_ids.json", ids)
        except Exception as exc:  # noqa: BLE001 - skip this name, keep the run alive
            print(f"  error resolving '{name}': {exc}")
    return ids


def run_sparql(qids: list[str]) -> list[dict]:
    values = " ".join(f"wd:{q}" for q in qids)
    resp = session.post(
        config.WIKIDATA_SPARQL,
        data={"query": SPARQL % values, "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()["results"]["bindings"]


def year(val: str | None) -> int | None:
    if not val:
        return None
    try:
        return int(str(val)[:4])
    except ValueError:
        return None


def to_int(val):
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def main() -> None:
    from fetch_wikipedia import player_names_from_asa

    names = sys.argv[1:] or player_names_from_asa()
    print(f"Wikidata fetch for {len(names)} player(s).")

    titles = load("wikipedia_titles.json")
    ids = resolve_qids(names, titles, load("wikidata_ids.json"))

    qid_to_name = {q: n for n, q in ids.items() if q}
    if not qid_to_name:
        sys.exit("No QIDs resolved; nothing to query.")

    print(f"Querying Wikidata for {len(qid_to_name)} entities...")
    out: dict[str, dict] = {
        n: {"qid": q, "bio": {}, "memberships": []} for q, n in qid_to_name.items()
    }
    # Chunk to keep the SPARQL VALUES clause a sane size.
    qids = list(qid_to_name)
    for i in range(0, len(qids), 50):
        for row in run_sparql(qids[i : i + 50]):
            qid = row["player"]["value"].rsplit("/", 1)[-1]
            rec = out.get(qid_to_name.get(qid))
            if rec is None:
                continue
            bio = rec["bio"]
            if "dob" in row and not bio.get("birth_date"):
                bio["birth_date"] = row["dob"]["value"][:10]
            if "citizen" in row and not bio.get("nationality"):
                bio["nationality"] = row["citizen"]["value"]
            if "position" in row and not bio.get("position"):
                bio["position"] = row["position"]["value"]
            if "image" in row and not bio.get("photo_url"):
                bio["photo_url"] = row["image"]["value"]
            if "height" in row and not bio.get("height_m"):
                bio["height_m"] = row["height"]["value"]
            if "clubLabel" in row:
                rec["memberships"].append(
                    {
                        "club": row["clubLabel"]["value"],
                        "start": year(row.get("start", {}).get("value")),
                        "end": year(row.get("end", {}).get("value")),
                        "matches": to_int(row.get("matches", {}).get("value")),
                        "goals": to_int(row.get("goals", {}).get("value")),
                    }
                )
        time.sleep(config.WIKI_DELAY_SECONDS)

    # De-duplicate memberships (the query can repeat rows across chunks/labels).
    for rec in out.values():
        seen, uniq = set(), []
        for m in rec["memberships"]:
            key = (m["club"], m["start"], m["end"])
            if key not in seen:
                seen.add(key)
                uniq.append(m)
        rec["memberships"] = sorted(uniq, key=lambda m: (m["start"] or 0, m["club"]))
        print(f"  {rec['qid']}: {len(rec['memberships'])} memberships")

    save("wikidata.json", out)
    print("Wikidata fetch complete.")


if __name__ == "__main__":
    main()
