# フィードを自動で探す（1 回だけ流す。結果 scripts/feeds_auto.json をリポジトリに入れる。毎日は探さない）
# 各館（venues.json）の公式サイトのトップを 1 回読み、<link rel="alternate" type="application/rss+xml|atom+xml"> → 無ければ
#   定番の道（board_config.json の feed_paths。トップの URL のフォルダからの相対）を試す。
#   守ること: robots.txt に従う・名乗る User-Agent（common.UA）・同じホストへは 1.1 秒以上あける・並列は別ホストどうしだけ（netlib.Net）
#   外す物: 中身が 0 件・日付が読めない・最新が 1 年以上前・使ってはいけない所（banned_hosts）・blocklist
#   市や県のサイトの下にある館（トップが /soshiki/museum/ のような所）は、同じフォルダの下のフィードだけ（サイト全体のフィードは館の物でない）
#   同じフィードが 2 館以上で見つかったら、まとめのフィードなので外す
# 途中経過: _work/feedscan/progress.jsonl（1 館 1 行。止まっても続きから。git に入れない）
# 順番: 博物館（museum）以外の分野 → 博物館（サイトのある物）
# 使い方: python -I scripts/find_feeds.py [--minutes 110] [--workers 32] [--finalize]
import argparse, datetime, json, os, re, sys, threading, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HERE
from netlib import Net, decode_html, og_image
from feedlib import parse_feed_bytes, norm_date

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.normpath(os.path.join(HERE, ".."))
PROG_DIR = os.path.join(ROOT, "_work", "feedscan")
PROG = os.path.join(PROG_DIR, "progress.jsonl")
CFG = json.load(open(os.path.join(HERE, "board_config.json"), encoding="utf-8"))
SRC = json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))
VENUES = json.load(open(os.path.join(HERE, "venues.json"), encoding="utf-8"))["venues"]
JST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(JST).date()
MAX_AGE = CFG["board"]["feed_max_age_days"]
ORDER = ["planet", "zoo", "garden", "art", "museum"]
FEED_TYPES = re.compile(r"application/(rss|atom|rdf)\+xml|application/xml|text/xml", re.I)


def blocked(v_id, url):
    return any(b == v_id or (url and url.startswith(b)) for b in CFG["blocklist"])


def check_feed(net, url):
    """(使えるか, 情報)"""
    r = net.get(url, 20, 5_000_000)
    if not r.ok:
        return False, {"url": url, "why": r.err or "HTTP %s" % r.status}
    try:
        items = parse_feed_bytes(r.body, r.url)
    except Exception as e:
        return False, {"url": url, "why": "読めない " + str(e)[:50]}
    if not items:
        return False, {"url": url, "why": "中身 0 件"}
    ds = [d for d in (norm_date(x["date"]) for x in items) if d]
    if not ds:
        return False, {"url": url, "why": "日付なし", "n": len(items)}
    newest = max(ds)
    if (TODAY - newest).days > MAX_AGE:
        return False, {"url": url, "why": "最新が古い " + newest.isoformat(), "n": len(items)}
    return True, {"url": r.url if urllib.parse.urlparse(r.url).netloc == urllib.parse.urlparse(url).netloc else url,
                  "n": len(items), "newest": newest.isoformat(), "imgs": sum(1 for x in items if x["img"])}


def scope_ok(top_url, feed_url):
    """トップが深い所（市のサイトの下など）なら、フィードは同じフォルダの下だけ"""
    t, f = urllib.parse.urlparse(top_url), urllib.parse.urlparse(feed_url)
    base = t.path.rsplit("/", 1)[0] + "/"
    if base == "/":
        return True
    return f.netloc == t.netloc and f.path.startswith(base)


def scan(net, v):
    rec = {"id": v["id"], "web": v["web"], "t": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    web = v["web"]
    if net.banned_url(web):
        rec["status"] = "banned"; return rec
    r = net.get(web, 20, 3_000_000)
    if not r.ok:
        rec["status"] = "top:" + (r.err or str(r.status)); return rec
    top = r.url
    rec["top"] = top
    h = decode_html(r.body, r.ctype)
    rec["top_og"] = og_image(h, top)
    tried, fails = [], []
    cands = []
    for m in re.finditer(r"<link\b[^>]*>", h, re.I):
        tag = m.group(0)
        if not re.search(r"rel=[\"']?alternate", tag, re.I) or not FEED_TYPES.search(tag):
            continue
        hm = re.search(r"href=[\"']([^\"']+)", tag, re.I)
        if hm:
            u = urllib.parse.urljoin(top, hm.group(1).replace("&amp;", "&"))
            if "comments/feed" in u or "/wp-json/" in u:
                continue
            cands.append(("alt", u))
    base = top.split("#")[0].split("?")[0]
    base = base if base.endswith("/") else base.rsplit("/", 1)[0] + "/"
    cands += [("path", urllib.parse.urljoin(base, p)) for p in CFG["feed_paths"]]
    for how, u in cands:
        if u in tried or len(tried) >= 8:
            continue
        if not scope_ok(top, u):
            fails.append({"url": u, "why": "サイト全体のフィード"}); continue
        if blocked(v["id"], u) or net.banned_url(u):
            continue
        tried.append(u)
        ok, info = check_feed(net, u)
        if ok:
            info["how"] = how
            rec["feed"] = info
            break
        fails.append(info)
        if net.dead and (urllib.parse.urlparse(u).hostname or "").lower() in net.dead:
            break
    rec["status"] = "found" if rec.get("feed") else "none"
    rec["fails"] = fails[:8]
    return rec


def load_progress():
    done = {}
    if os.path.exists(PROG):
        for line in open(PROG, encoding="utf-8"):
            try:
                x = json.loads(line)
                done[x["id"]] = x
            except ValueError:
                pass
    return done


def finalize():
    done = load_progress()
    vmap = {v["id"]: v for v in VENUES}
    feeds, by_url = [], {}
    for x in done.values():
        if x.get("status") == "found":
            by_url.setdefault(x["feed"]["url"], []).append(x)
    shared = {u for u, xs in by_url.items() if len({vmap[x["id"]]["name"] for x in xs if x["id"] in vmap}) >= 2}
    for x in done.values():
        v = vmap.get(x["id"])
        if not v or x.get("status") != "found" or x["feed"]["url"] in shared or blocked(v["id"], x["feed"]["url"]):
            continue
        if x["feed"]["url"] in {f["url"] for f in feeds}:
            continue
        feeds.append({"id": v["id"], "venue": v["name"], "cat": v["cat"], "pref": v["pref"], "region": v["region"], "url": x["feed"]["url"],
                      "top": x.get("top", v["web"]), "top_og": x.get("top_og", ""), "image": v.get("image", ""),
                      "n": x["feed"]["n"], "newest": x["feed"]["newest"], "how": x["feed"]["how"], "origin": "auto"})
    # 今の sources.json のフィード（19）も分野・都道府県を付けて入れる（同じ URL があればこちらを優先）
    REGION = {v["pref"]: v["region"] for v in VENUES if v["pref"] and v["region"]}
    for f in SRC["feeds"]:
        cat, pref = CFG["sources_meta"].get(f["id"], ["planet", ""])
        e = {"id": f["id"], "venue": f["venue"], "cat": cat, "pref": pref, "region": REGION.get(pref, 0), "url": f["url"],
             "top": "", "top_og": "", "image": "", "origin": "sources"}
        for k in ("future_pub_is_event", "desc_keywords"):
            if f.get(k):
                e[k] = True
        if f.get("off") or net_banned(f["url"]):
            e["off"] = True
            e["off_why"] = f.get("off_why", "使ってはいけない所")
        feeds = [x for x in feeds if x["url"].rstrip("/") != f["url"].rstrip("/")]
        feeds.append(e)
    ORD = {c: i for i, c in enumerate(ORDER)}
    feeds.sort(key=lambda f: (ORD.get(f["cat"], 9), f["region"] or 99, f["venue"]))
    want = [v for v in VENUES if v["web"]]
    st = {"venues_with_web": len(want), "scanned": sum(1 for v in want if v["id"] in done),
          "found": sum(1 for x in done.values() if x.get("status") == "found"), "shared_dropped": len(shared)}
    fn = os.path.join(HERE, "feeds_auto.json")
    with open(fn, "w", encoding="utf-8", newline="\n") as fo:
        fo.write(json.dumps({"_note": "find_feeds.py で探したフィード（%s）と sources.json のフィード。毎日の build_board.py が読む。"
                                      "origin=auto は自動で見つけた物（題・日付・リンクと、フィードの中の画像・ページの og:image を使う）" % TODAY.isoformat(),
                             "updated": TODAY.isoformat(), "scan": st}, ensure_ascii=False)[:-1] + ',\n"feeds":[\n')
        fo.write(",\n".join(json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in feeds))
        fo.write("\n]}\n")
    from collections import Counter
    on = [f for f in feeds if not f.get("off")]
    print("feeds_auto.json:", len(on), "本（off を除く）", st)
    print("分野", Counter(f["cat"] for f in on))
    print("地域", sorted(Counter(f["region"] for f in on).items()))


_banned = [b["host"] for b in CFG["banned_hosts"]]


def net_banned(url):
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(h == b or h.endswith("." + b) for b in _banned)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=110)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--only", default="", help="分野だけ（カンマ区切り）")
    a = ap.parse_args()
    if a.finalize:
        finalize(); return
    os.makedirs(PROG_DIR, exist_ok=True)
    done = load_progress()
    ORD = {c: i for i, c in enumerate(ORDER)}
    todo = [v for v in VENUES if v["web"] and v["id"] not in done and not blocked(v["id"], v["web"])
            and (not a.only or v["cat"] in a.only.split(","))]
    todo.sort(key=lambda v: (ORD[v["cat"]], v["region"] or 99))
    # 同じホストの館は散らす（並列のスレッドが同じホストで待たないように）
    seen, first, later = set(), [], []
    for v in todo:
        h = urllib.parse.urlparse(v["web"]).hostname
        (later if h in seen else first).append(v)
        seen.add(h)
    todo = first + later
    print("残り", len(todo), "済み", len(done))
    net = Net(1.1, _banned)
    deadline = time.time() + a.minutes * 60
    wlock = threading.Lock()
    stats = {"n": 0, "found": 0}
    t0 = time.time()

    def job(v):
        if time.time() > deadline:
            return
        try:
            rec = scan(net, v)
        except Exception as e:
            rec = {"id": v["id"], "web": v["web"], "status": "error " + str(e)[:80]}
        with wlock:
            with open(PROG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            stats["n"] += 1
            stats["found"] += rec.get("status") == "found"
            if stats["n"] % 100 == 0:
                print("  %d 館 / 見つけた %d / %.0f 分 / 読んだ %d" % (stats["n"], stats["found"], (time.time() - t0) / 60, net.count), flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(job, todo))
    print("今回", stats, "読んだ", net.count, "%.0f 分" % ((time.time() - t0) / 60))
    finalize()


if __name__ == "__main__":
    main()
