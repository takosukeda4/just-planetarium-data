# 館の一覧（1 回だけ流す。結果 scripts/venues.json をリポジトリに入れる）
# 出どころ: Wikidata の SPARQL（CC0）。日本（P17=Q17）の プラネタリウム・科学館・天文台・美術館・博物館・水族館・動物園・植物園
#   名前（ja）・都道府県（P131 をたどって「日本の都道府県」Q50337）・公式サイト（P856）・画像（P18、Commons のファイル名）・座標（P625）
#   閉じた館（P576 解散・廃止 / P3999 閉館日）は除く
# 分野は種類の Q 番号から決める。重なりは細かい方を優先: planet > zoo > garden > art > museum（美術館 > 博物館 など）
# 使い方: python -I scripts/build_venues.py   → scripts/venues.json
import json, os, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I でも common を読む
from common import UA, HERE

sys.stdout.reconfigure(encoding="utf-8")
ENDPOINT = "https://query.wikidata.org/sparql"

# 分野 → 種類（P31/P279* でたどる）。並びが優先の順
CLASSES = [
    ("planet", ["Q148319", "Q588140", "Q1254933"]),   # プラネタリウム・科学館（science museum）・天文台（astronomical observatory）
    ("zoo", ["Q2281788", "Q43501"]),                  # 水族館・動物園
    ("garden", ["Q167346"]),                          # 植物園
    ("art", ["Q207694", "Q1007870"]),                 # 美術館・アートギャラリー
    ("museum", ["Q33506"]),                           # 博物館（資料館・記念館などは下位の種類で入る）
]
PRIORITY = [c for c, _ in CLASSES]

REGION = {}
for r, prefs in [(1, "北海道"), (2, "青森県 岩手県 宮城県 秋田県 山形県 福島県"), (3, "茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県"),
                 (4, "新潟県 富山県 石川県 福井県 山梨県 長野県"), (5, "岐阜県 静岡県 愛知県 三重県"),
                 (6, "滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県"), (7, "鳥取県 島根県 岡山県 広島県 山口県"),
                 (8, "徳島県 香川県 愛媛県 高知県"), (9, "福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県")]:
    for p in prefs.split():
        REGION[p] = r

QUERY = """
SELECT ?item ?label (SAMPLE(?prefLabel) AS ?pref) (GROUP_CONCAT(DISTINCT ?web; separator=" ") AS ?webs)
       (SAMPLE(?img) AS ?image) (SAMPLE(?coord) AS ?c) WHERE {
  ?item wdt:P31/wdt:P279* wd:%s ; wdt:P17 wd:Q17 ; rdfs:label ?label .
  FILTER(LANG(?label) = "ja")
  FILTER NOT EXISTS { ?item wdt:P576 [] }
  FILTER NOT EXISTS { ?item wdt:P3999 [] }
  OPTIONAL { ?item wdt:P131* ?p . ?p wdt:P31 wd:Q50337 ; rdfs:label ?prefLabel . FILTER(LANG(?prefLabel) = "ja") }
  OPTIONAL { ?item wdt:P856 ?web }
  OPTIONAL { ?item wdt:P18 ?img }
  OPTIONAL { ?item wdt:P625 ?coord }
} GROUP BY ?item ?label
"""


def sparql(q):
    for n in range(4):
        try:
            req = urllib.request.Request(ENDPOINT, data=urllib.parse.urlencode({"query": q, "format": "json"}).encode(),
                                         headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))["results"]["bindings"]
        except Exception as e:
            print("  やり直し", n + 1, str(e)[:80])
            time.sleep(10 * (n + 1))
    raise RuntimeError("SPARQL が通らない")


def pick_web(s):
    ws = [w for w in (s or "").split() if w.startswith("http")]
    if not ws:
        return ""
    bad = lambda w: any(x in w.lower() for x in ("/en/", "/en", "english", "facebook.com", "twitter.com", "x.com/", "instagram.com"))
    return sorted(ws, key=lambda w: (bad(w), not w.startswith("https"), len(w)))[0]


def main():
    out = {}
    for cat, qs in CLASSES:
        for q in qs:
            t0 = time.time()
            rows = sparql(QUERY % q)
            print(cat, q, len(rows), "件", "%.0f 秒" % (time.time() - t0))
            for b in rows:
                qid = b["item"]["value"].rsplit("/", 1)[-1]
                v = out.get(qid)
                if v is None:
                    v = out[qid] = {"id": qid, "name": b["label"]["value"], "pref": "", "region": 0, "cat": cat, "types": [],
                                    "web": "", "image": "", "lat": None, "lon": None}
                if PRIORITY.index(cat) < PRIORITY.index(v["cat"]):
                    v["cat"] = cat
                if q not in v["types"]:
                    v["types"].append(q)
                if not v["pref"] and "pref" in b:
                    v["pref"] = b["pref"]["value"]
                    v["region"] = REGION.get(v["pref"], 0)
                if not v["web"] and "webs" in b:
                    v["web"] = pick_web(b["webs"]["value"])
                if not v["image"] and "image" in b:
                    v["image"] = urllib.parse.unquote(b["image"]["value"].rsplit("/", 1)[-1])
                if v["lat"] is None and "c" in b:
                    try:
                        lon, lat = b["c"]["value"].replace("Point(", "").replace(")", "").split()
                        v["lat"], v["lon"] = round(float(lat), 5), round(float(lon), 5)
                    except ValueError:
                        pass
            time.sleep(2)
    # 都道府県が分からない館は、座標から一番近い（40 km 以内）都道府県の分かっている館に合わせる（pref_guess=true）
    import math
    known = [v for v in out.values() if v["pref"] and v["lat"] is not None]
    for v in out.values():
        if v["pref"] or v["lat"] is None:
            continue
        best, bd = None, 1e9
        for k in known:
            dy = (k["lat"] - v["lat"]) * 111.0
            dx = (k["lon"] - v["lon"]) * 111.0 * math.cos(math.radians(v["lat"]))
            d = dx * dx + dy * dy
            if d < bd:
                best, bd = k, d
        if best and bd <= 40 * 40:
            v["pref"], v["region"], v["pref_guess"] = best["pref"], best["region"], True
    # 天文台（Q1254933）だけで座標の無い物は宇宙の望遠鏡（ひのとり・ようこう など）なので除く
    for k in [k for k, v in out.items() if v["types"] == ["Q1254933"] and v["lat"] is None and not v["pref"]]:
        del out[k]
    vs = sorted(out.values(), key=lambda v: (PRIORITY.index(v["cat"]), v["region"] or 99, v["pref"], v["name"]))
    fn = os.path.join(HERE, "venues.json")
    with open(fn, "w", encoding="utf-8", newline="\n") as f:
        f.write('{"_note":"Wikidata（CC0）から 2026-11-09 に作った館の一覧（scripts/build_venues.py）。cat: planet/art/museum/zoo/garden、region: 1〜9（0=不明）、image: Commons のファイル名（P18）",\n"venues":[\n')
        f.write(",\n".join(json.dumps(v, ensure_ascii=False, separators=(",", ":")) for v in vs))
        f.write("\n]}\n")
    from collections import Counter
    print("全部", len(vs), "サイトあり", sum(1 for v in vs if v["web"]), "画像あり", sum(1 for v in vs if v["image"]), "地域不明", sum(1 for v in vs if not v["region"]))
    print("分野", Counter(v["cat"] for v in vs))
    print("分野（サイトあり）", Counter(v["cat"] for v in vs if v["web"]))
    print("地域", sorted(Counter(v["region"] for v in vs).items()))


if __name__ == "__main__":
    main()
