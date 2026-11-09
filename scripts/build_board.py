# 情報ボード v2（2026-11-09）: 全国の館のフィード（feeds_auto.json）と BODIK のイベント一覧（CC BY）→ board.txt・cards/c_NNN.jpg・board.json
# 毎日 1 回（GitHub Actions、build_info.py の後に同じ出力先へ）。今の info.txt・qr.png・slots/ は build_info.py が作り続ける（ここでは触らない）
# 守ること: robots.txt に従う・名乗る User-Agent・同じホストへは 1.1 秒以上あける・並列は別ホストどうしだけ（netlib.Net）
#   題・日付・リンクを載せる（要約は日付と受付の状態を読むだけ）。画像は「フィードの中の画像 → ページの og:image → 館の Wikimedia Commons の CC 写真」の順で、
#   縮めて出典（館名・URL）付き。ページを読むのは選ばれた件だけ（最大 og_pages_max）。ページの奥のチラシ PDF などは写さない
#   館から言われたら board_config.json の blocklist（館の id か URL の前方一致）に足す
# 形は spec（_claude/work/planetarium/req_1109/spec.md）: board.txt（タブ区切り）・cards/c_000.jpg〜（無い番号は置かない）・board.json（人が見る用）
# 環境変数（手元で試すとき）: BOARD_CACHE=フォルダ（読んだ物を取っておく）、BOARD_TODAY=YYYY-MM-DD、BOARD_MINUTES=全体の時間の上限（既定 15）
import csv, datetime, glob, hashlib, io, json, os, re, sys, threading, time, unicodedata, urllib.parse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HERE
from netlib import Net, decode_html, og_image
from feedlib import parse_feed_bytes, norm_date, norm_text, judge_dates, strip
from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
Image.MAX_IMAGE_PIXELS = 80_000_000
T0 = time.time()
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "out")
CARDS = os.path.join(OUT, "cards")
os.makedirs(CARDS, exist_ok=True)
CFG = json.load(open(os.path.join(HERE, "board_config.json"), encoding="utf-8"))
B = CFG["board"]
SRC = json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))
FEEDS = json.load(open(os.path.join(HERE, "feeds_auto.json"), encoding="utf-8"))["feeds"]
VENUES = json.load(open(os.path.join(HERE, "venues.json"), encoding="utf-8"))["venues"]
JST = datetime.timezone(datetime.timedelta(hours=9))
today = datetime.date.fromisoformat(os.environ["BOARD_TODAY"]) if os.environ.get("BOARD_TODAY") else datetime.datetime.now(JST).date()
LIMIT = float(os.environ.get("BOARD_MINUTES", "15")) * 60
R = dict(SRC["rules"], future_days=B["future_days"], news_days=B["news_days"])
net = Net(1.1, [b["host"] for b in CFG["banned_hosts"]], cache_dir=os.environ.get("BOARD_CACHE", ""))

CATS = [("planet", "プラネタリウム・科学館"), ("art", "美術館"), ("museum", "博物館"), ("zoo", "水族館・動物園"), ("garden", "植物園")]
REGIONS = [(1, "北海道"), (2, "東北"), (3, "関東"), (4, "北陸・甲信越"), (5, "東海"), (6, "近畿"), (7, "中国"), (8, "四国"), (9, "九州・沖縄")]
PREFS = ("北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 "
         "岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 "
         "福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県").split()      # JIS の都道府県コードの順（01〜47）
PREF_REGION = {p: (1 if i == 0 else 2 if i <= 6 else 3 if i <= 13 else 4 if i <= 19 else 5 if i <= 23 else 6 if i <= 29 else 7 if i <= 34 else 8 if i <= 38 else 9)
               for i, p in enumerate(PREFS)}
for p in ("新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県"):
    PREF_REGION[p] = 4
for p in ("岐阜県", "静岡県", "愛知県", "三重県"):
    PREF_REGION[p] = 5

EXCLUDE = SRC.get("exclude", []) + B["exclude_extra"]
CLOSED_T = re.compile(R["closed_title"])
CLOSED_D = re.compile(R["closed_desc"])
WORDS = re.compile(B["words"])
log, dropped = [], []


def left():
    return LIMIT - (time.time() - T0)


def blocked(vid, url):
    return any(b == vid or (url and url.startswith(b)) for b in CFG["blocklist"])


def clean(s, n=None):
    s = re.sub(r"[\t\r\n]+", " ", s or "").strip()
    return s[:n] if n else s


def judge(f, title, desc, pub):
    bad = [x for x in EXCLUDE if x in title]
    if bad:
        return False, "外す:" + bad[0], None
    tt = norm_text(title)
    m = CLOSED_T.search(tt) or CLOSED_D.search(norm_text(desc))
    if m:
        return False, "受付終了・終わった物:" + m.group(0), None
    if not (WORDS.search(tt) or (f.get("desc_keywords") and WORDS.search(norm_text(desc)))):
        return False, "対象外（展示・催しの言葉なし）", None
    ok, why, info = judge_dates(title, desc, pub, today, R, f.get("future_pub_is_event"))
    if not ok:
        return False, why, None
    if info["kind"] == "event" and info["start"] and info["start"] < today <= info["end"] and (info["end"] - info["start"]).days >= 7:
        info["kind"], info["date"] = "until", info["end"]     # 会期の途中（「10月1日~12月7日」のような期間）
    return True, "", info


# --- 1. フィード（ホストを散らして並列。同じホストは netlib が 1 本ずつ） ---
def interleave(fs):
    by = defaultdict(list)
    for f in fs:
        by[urllib.parse.urlparse(f["url"]).hostname].append(f)
    out, lists = [], list(by.values())
    while lists:
        out += [l.pop(0) for l in lists]
        lists = [l for l in lists if l]
    return out


VNAME = {}
for v in VENUES:
    VNAME.setdefault(norm_text(v["name"]), v)
cand = []
clock = threading.Lock()
feed_stat = Counter()


def read_feed(f):
    if left() < LIMIT * 0.45:
        feed_stat["時間切れで読まず"] += 1
        return
    r = net.get(f["url"], 20, 5_000_000)
    if not r.ok:
        feed_stat["失敗"] += 1
        log.append(("feed", f["id"], r.err or str(r.status)))
        return
    try:
        ent = parse_feed_bytes(r.body, r.url)
    except Exception as e:
        feed_stat["読めない"] += 1
        log.append(("feed", f["id"], "読めない " + str(e)[:50]))
        return
    feed_stat["読めた"] += 1
    seen, got = set(), []
    for x in ent:
        title, link = clean(x["title"]), x["link"].strip()
        if not title or title == f["venue"] or not link.startswith("http") or title in seen or blocked(f["id"], link) or net.banned_url(link):
            continue
        seen.add(title)
        pub = norm_date(x["date"])
        ok, why, info = judge(f, title, x["desc"], pub)
        if not ok:
            dropped.append((f["id"], why, title))
            continue
        info.update({"src": f["id"], "vid": f["id"], "venue": f["venue"], "cat": f["cat"], "pref": f["pref"], "region": f["region"] or PREF_REGION.get(f["pref"], 0),
                     "title": title, "url": link, "pub": pub, "feed_img": x["img"], "top_og": f.get("top_og", ""), "top": f.get("top", ""),
                     "commons": f.get("image") or (VNAME.get(norm_text(f["venue"])) or {}).get("image", ""), "origin": "feed:" + f["url"]})
        got.append(info)
    with clock:
        cand.extend(got)


feeds = [f for f in FEEDS if not f.get("off") and not blocked(f["id"], f["url"]) and not net.banned_url(f["url"])]
with ThreadPoolExecutor(48) as ex:
    list(ex.map(read_feed, interleave(feeds)))
print("フィード", len(feeds), "本", dict(feed_stat), "候補", len(cand), "%.0f 秒" % (time.time() - T0), flush=True)


# --- 2. BODIK のイベント一覧（CC BY）: 場所名・題に 美術館/博物館/… が入る行だけ ---
BODIK_W = re.compile(B["bodik_words"])
bodik_sources = []


def bodik_cat(s):
    if re.search(r"プラネタリウム|科学館|天文", s):
        return "planet"
    if "美術館" in s:
        return "art"
    if re.search(r"水族館|動物園", s):
        return "zoo"
    if "植物園" in s:
        return "garden"
    return "museum"


def pdate(s):
    s = (s or "").strip().replace("/", "-").replace(".", "-")
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    except ValueError:
        return None


def read_bodik():
    try:
        q = urllib.parse.urlencode({"q": 'title:"イベント一覧"', "rows": 200})
        r = net.get("https://data.bodik.jp/api/3/action/package_search?" + q, 60, 20_000_000, robots=False)   # CKAN の API
        pk = json.loads(r.body.decode("utf-8"))["result"]["results"] if r.ok else []
    except Exception as e:
        log.append(("bodik", "package_search", str(e)[:60]))
        return
    lic_ok = lambda t: any(x.lower() in (t or "").lower() for x in B["bodik_licenses"])
    for p in pk:
        if left() < LIMIT * 0.45:
            break
        lic = p.get("license_title") or ""
        if not lic_ok(lic):
            continue
        res = [x for x in p.get("resources", []) if (x.get("format") or "").upper() == "CSV"]
        if not res:
            continue
        rs = net.get(res[0]["url"], 40, 20_000_000)
        if not rs.ok:
            log.append(("bodik", p["name"], rs.err))
            continue
        txt = None
        for enc in ("utf-8-sig", "cp932"):
            try:
                txt = rs.body.decode(enc); break
            except UnicodeDecodeError:
                pass
        if txt is None:
            continue
        org = (p.get("organization") or {}).get("title", "")
        n = 0
        for row in csv.DictReader(io.StringIO(txt)):
            place, name = clean(row.get("場所名称")), clean(row.get("イベント名"))
            if not name or not BODIK_W.search(place + name):
                continue
            url = clean(row.get("コンテンツURL") or row.get("URL") or row.get("url"))
            if not url.startswith("http") or net.banned_url(url):
                continue
            st, en = pdate(row.get("開始日")), pdate(row.get("終了日"))
            st = st or en
            en = en or st
            if not st or en < today or (st - today).days > R["future_days"] or blocked("bodik:" + place, url):
                continue
            if st < today <= en and (en - st).days >= 7:
                kind, date = "until", en
            else:
                kind, date = "event", (st if st >= today else today)
            pref = clean(row.get("所在地_都道府県") or row.get("都道府県名"))
            if pref not in PREF_REGION:
                code = re.sub(r"\D", "", row.get("全国地方公共団体コード") or p["name"])[:2]
                pref = PREFS[int(code) - 1] if code.isdigit() and 1 <= int(code) <= 47 else ""
            v = VNAME.get(norm_text(place)) or VNAME.get(norm_text(re.sub(r"[（(].*$", "", place)))
            img, ilic = clean(row.get("画像")), clean(row.get("画像_ライセンス"))
            cand.append({"kind": kind, "date": date, "end": en, "deadline": None, "start": st, "src": "bodik:" + p["name"], "vid": (v["id"] if v else "bodik:" + place),
                         "venue": clean(place, 40) or org, "cat": v["cat"] if v else bodik_cat(place + name), "pref": pref, "region": PREF_REGION.get(pref, 0),
                         "title": name, "url": url, "pub": None, "feed_img": img if (img.startswith("http") and re.search(r"CC|クリエイティブ", ilic)) else "",
                         "feed_img_credit": "画像: %sのオープンデータ（%s）" % (org, ilic), "top_og": "", "top": "", "commons": v.get("image", "") if v else "",
                         "origin": "bodik:" + p["name"]})
            n += 1
        bodik_sources.append({"dataset": p["name"], "title": p.get("title"), "org": org, "license": lic, "csv": res[0]["url"], "rows_used": n,
                              "page": "https://data.bodik.jp/dataset/" + p["name"]})


read_bodik()
print("BODIK", len(bodik_sources), "件のデータ、行", sum(b["rows_used"] for b in bodik_sources), "%.0f 秒" % (time.time() - T0), flush=True)


# --- 3. 選ぶ: 1 館 per_venue 件まで。分野を均し、分野の中で地域を均す（地域 0 は最後）。最大 max_items ---
def prio(c):
    k = {"event": 0, "until": 1, "news": 2}[c["kind"]]
    return (k, c["date"].toordinal() if k < 2 else -c["date"].toordinal(), c["venue"], c["title"])


uniq, seen_u, seen_t = [], set(), set()
for c in sorted(cand, key=prio):
    tk = (re.sub(r"\W", "", norm_text(c["title"]))[:40], c["date"])
    if c["url"] in seen_u or tk in seen_t:
        dropped.append((c["src"], "重なり", c["title"]))
        continue
    seen_u.add(c["url"]); seen_t.add(tk)
    c["title"] = c["title"][:B["title_max"]]
    uniq.append(c)
bucket = defaultdict(list)
for c in uniq:
    bucket[(c["cat"], c["region"])].append(c)
cat_n, cr_n, reg_n, ven_n = Counter(), Counter(), Counter(), Counter()
sel = []
while len(sel) < B["max_items"]:
    best = None
    for (cat, reg), lst in bucket.items():
        while lst and ven_n[lst[0]["vid"]] >= B["per_venue"]:
            dropped.append((lst[0]["src"], "1 館 %d 件まで" % B["per_venue"], lst.pop(0)["title"]))
        if not lst:
            continue
        key = (cat_n[cat], reg == 0, cr_n[(cat, reg)], reg_n[reg], prio(lst[0]))
        if best is None or key < best[0]:
            best = (key, cat, reg)
    if not best:
        break
    _, cat, reg = best
    c = bucket[(cat, reg)].pop(0)
    sel.append(c)
    cat_n[cat] += 1; cr_n[(cat, reg)] += 1; reg_n[reg] += 1; ven_n[c["vid"]] += 1
for lst in bucket.values():
    dropped += [(c["src"], "全部で %d 件まで" % B["max_items"], c["title"]) for c in lst]
sel.sort(key=prio)
print("選んだ", len(sel), "（候補", len(uniq), "）", "%.0f 秒" % (time.time() - T0), flush=True)


# --- 4. 画像: フィードの画像 → ページの og:image → 館の Commons の写真 ---
def lic_ok(meta):
    s = (meta.get("LicenseShortName", {}).get("value", "") or "").replace("CC BY SA", "CC BY-SA").strip()
    return any(s.upper() == a.upper() for a in SRC["commons_allowed_licenses"]) and meta.get("NonFree", {}).get("value", "") != "true"


def commons_info(files):
    out = {}
    files = sorted(set(f for f in files if f))
    for i in range(0, len(files), 40):
        q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1024,
                                    "titles": "|".join("File:" + f for f in files[i:i + 40])})
        r = net.get("https://commons.wikimedia.org/w/api.php?" + q, 40, 10_000_000, robots=False)   # API（build_info.py と同じ）
        if not r.ok:
            continue
        d = json.loads(r.body.decode("utf-8")).get("query", {})
        norm = {x["to"]: x["from"] for x in d.get("normalized", [])}
        for p in d.get("pages", {}).values():
            ii = (p.get("imageinfo") or [None])[0]
            if not ii or ii.get("mime") not in ("image/jpeg", "image/png") or not lic_ok(ii.get("extmetadata", {})):
                continue
            meta = ii["extmetadata"]
            artist = strip(meta.get("Artist", {}).get("value", ""))[:60] or "unknown"
            lic = meta["LicenseShortName"]["value"]
            name = norm.get(p["title"], p["title"]).replace("File:", "")
            out[name.replace("_", " ")] = {"url": ii.get("thumburl") or ii["url"], "page": ii["descriptionurl"], "license": lic, "artist": artist,
                                           "credit": "写真: %s / %s / Wikimedia Commons" % (artist, lic)}
    return out


def same_img(a, b):
    """クエリ・大きさの印（-300x200 など）を除いて同じ画像か"""
    n = lambda u: re.sub(r"(-\d+x\d+|@2x)?\.(jpe?g|png|webp|gif)$", "", urllib.parse.urlparse(u or "").path.lower())
    return bool(a and b) and n(a) == n(b)


BAD_IMG = re.compile(r"logo|icon|favicon|noimage|no_image|no-image|dummy|blank|spacer|banner|ogp_default|default|common|share|/sns|twitter|facebook|line_|\.svg|\.gif", re.I)
tops = {}   # 館のトップの og:image が分からない館（sources.json のフィード・BODIK）は、トップを 1 回だけ読む


def read_page(c):
    if left() < 60:
        return
    r = net.get(c["url"], 20, 3_000_000)
    if r.ok and "html" in (r.ctype or "html").lower():
        c["og"] = og_image(decode_html(r.body, r.ctype), r.url)


def read_top(vid_top):
    vid, top = vid_top
    if left() < 60:
        return
    r = net.get(top, 20, 3_000_000)
    tops[vid] = og_image(decode_html(r.body, r.ctype), r.url) if r.ok else ""


def gray(im):
    from PIL import ImageStat
    return ImageStat.Stat(im.convert("RGB").resize((48, 48)).convert("HSV").split()[1]).mean[0] < 14   # 彩度の平均が低い = 白黒


def make_card(src_url):
    """(JPEG のバイト, 幅, 高さ) か (None, 理由)"""
    wm = "wikimedia.org" in src_url                       # Commons の縮小画像は作るのに時間がかかることがある
    r = net.get(src_url, 30 if wm else 15, 15_000_000, robots=not wm)
    if not r.ok:
        return None, r.err or str(r.status)
    try:
        im = Image.open(io.BytesIO(r.body))
        if im.format == "JPEG":
            im.draft("RGB", (1024, 1024))      # 大きな JPEG は縮めて読む（速い・メモリが少ない）
        if im.width * im.height > 40_000_000:
            return None, "大きすぎる %dx%d" % im.size
        im.load()
    except Exception as e:
        return None, "画像でない " + type(e).__name__
    if min(im.size) < 200:
        return None, "小さい %dx%d" % im.size
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    im = im.convert("RGB")
    if gray(im):
        return None, "白黒"
    s = min(1.0, 1024 / max(im.size))
    if s < 1:
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    for q in (80, 72, 64, 56, 48, 40):
        b = io.BytesIO()
        im.save(b, "JPEG", quality=q, optimize=True, progressive=False)
        if b.tell() <= 250_000:
            return (b.getvalue(), im.width, im.height, q), ""
    return None, "250 KB に収まらない"


key_img = lambda u: re.sub(r"\?.*$", "", u or "")
# 同じ館の 2 件以上で同じフィードの画像・og:image = サイト共通の画像（ロゴなど）
fi_n = Counter((c["vid"], key_img(c["feed_img"])) for c in sel if c["feed_img"])
for f in glob.glob(os.path.join(CARDS, "c_*.jpg")):
    os.remove(f)
cards, by_src, bad_src, card_lock = [], {}, set(), threading.Lock()
img_fail = Counter()


def try_img(c, url, credit, page, how):
    """1 枚試す。使えたら c に番号を入れて True"""
    if left() < 20 or url in bad_src:
        return False
    with card_lock:
        if url in by_src:
            c["img"], c["credit"], c["img_src"], c["img_page"], c["img_how"] = by_src[url], credit, url, page, how
            return True
    res, why = make_card(url)
    with card_lock:
        if not res:
            img_fail[why.split(" ")[0]] += 1
            bad_src.add(url)
            return False
        if url in by_src:
            i = by_src[url]
        else:
            i = len(cards)
            if i >= 300:
                return False
            data, w, h, q = res
            open(os.path.join(CARDS, "c_%03d.jpg" % i), "wb").write(data)
            cards.append({"i": i, "file": "cards/c_%03d.jpg" % i, "w": w, "h": h, "bytes": len(data), "quality": q, "src": url, "page": page, "credit": credit, "how": how})
            by_src[url] = i
    c["img"], c["credit"], c["img_src"], c["img_page"], c["img_how"] = i, credit, url, page, how
    return True


def stage_feed(c):
    """① フィードの中の画像"""
    c["img"], c["credit"] = -1, ""
    fi = c["feed_img"]
    if fi and not BAD_IMG.search(fi) and fi_n[(c["vid"], key_img(fi))] < 2 and not same_img(fi, c["top_og"]):
        try_img(c, fi, c.get("feed_img_credit") or "画像: %sのページから" % c["venue"], c["url"], "フィードの画像（館のページ）")


with ThreadPoolExecutor(32) as ex:
    list(ex.map(stage_feed, interleave(sel)))
n_feed = len(cards)
# ② 画像がまだ無い件だけページを読む（og:image）。最大 og_pages_max
need_page = [c for c in sel if c["img"] < 0][:B["og_pages_max"]]
with ThreadPoolExecutor(32) as ex:
    list(ex.map(read_page, interleave(need_page)))
    need_top = {}
    for c in need_page:
        if c.get("og") and not c["top"]:     # トップの og:image がまだ分からない館（sources.json のフィード・BODIK）
            p = urllib.parse.urlparse(c["url"])
            need_top.setdefault(c["vid"], "%s://%s/" % (p.scheme, p.netloc))
    list(ex.map(read_top, need_top.items()))
for c in sel:
    if not c["top"] and c["vid"] in tops:
        c["top_og"] = tops[c["vid"]]
og_n = Counter((c["vid"], key_img(c["og"])) for c in sel if c.get("og"))
com = commons_info([c["commons"] for c in sel if c["img"] < 0])
print("フィードの画像", n_feed, "ページ", len(need_page), "トップ", len(need_top), "Commons", len(com), "%.0f 秒" % (time.time() - T0), flush=True)


def stage_rest(c):
    """② ページの og:image → ③ 館の Commons の写真"""
    if c["img"] >= 0:
        return
    og = c.get("og")
    if og and not BAD_IMG.search(og) and og_n[(c["vid"], key_img(og))] < 2 and not same_img(og, c["top_og"]):
        if try_img(c, og, "画像: %sのページから" % c["venue"], c["url"], "ページの og:image（館のページ）"):
            return
    ci = com.get((c["commons"] or "").replace("_", " "))
    if ci:
        try_img(c, ci["url"], ci["credit"], ci["page"], "Wikimedia Commons " + ci["license"])


with ThreadPoolExecutor(32) as ex:
    list(ex.map(stage_rest, interleave(sel)))
print("画像", len(cards), "枚", "%.1f MB" % (sum(x["bytes"] for x in cards) / 1e6), "失敗", dict(img_fail), "%.0f 秒" % (time.time() - T0), flush=True)


# --- 5. 書く ---
iso = lambda d: d.isoformat() if d else ""
slot_lines = []
info_txt = os.path.join(OUT, "info.txt")
if os.path.exists(info_txt):
    t = open(info_txt, encoding="utf-8").read().split("\n")
    if "#slots" in t:
        slot_lines = [x for x in t[t.index("#slots") + 1:] if x][:SRC["slots"]]
if not slot_lines:
    slot_lines = ["slots/slot_%02d.jpg\t\t\t\t" % i for i in range(SRC["slots"])]
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
with open(os.path.join(OUT, "board.txt"), "w", encoding="utf-8", newline="\n") as f:
    f.write("\t".join(["#board", "2", now, str(len(sel)), str(len(cards))]) + "\n")
    f.write("\t".join(["#cats"] + ["%s:%s" % c for c in CATS]) + "\n")
    f.write("\t".join(["#regions"] + ["%d:%s" % r for r in REGIONS]) + "\n")
    f.write("#items\n")
    for c in sel:
        f.write("\t".join([c["cat"], str(c["region"]), c["pref"], clean(c["venue"]), clean(c["title"], B["title_max"]), iso(c["date"]), c["kind"],
                           iso(c["end"]), iso(c["deadline"]), clean(c["url"]), str(c.get("img", -1)), clean(c.get("credit", ""))]) + "\n")
    f.write("#slots\n")
    for x in slot_lines:
        f.write(x + "\n")
items_out = [{"cat": c["cat"], "region": c["region"], "pref": c["pref"], "venue": c["venue"], "venue_id": c["vid"], "title": c["title"], "date": iso(c["date"]),
              "kind": c["kind"], "end": iso(c["end"]), "deadline": iso(c["deadline"]), "pub": iso(c["pub"]), "url": c["url"], "img": c.get("img", -1),
              "credit": c.get("credit", ""), "img_src": c.get("img_src", ""), "img_page": c.get("img_page", ""), "img_how": c.get("img_how", ""),
              "from": c["origin"]} for c in sel]
doc = {"updated": now, "today": today.isoformat(), "count": len(sel), "cards": len(cards),
       "by_cat": dict(Counter(c["cat"] for c in sel)), "by_region": {str(k): v for k, v in sorted(Counter(c["region"] for c in sel).items())},
       "items": items_out, "card_files": cards,
       "sources": {"feeds": len(feeds), "feed_stat": dict(feed_stat), "bodik": bodik_sources,
                   "bodik_note": "BODIK オープンデータ（各自治体のイベント一覧、CC BY 等）。出典: 各データの org と page",
                   "wikidata_note": "館の一覧・都道府県は Wikidata（CC0）", "commons_note": "写真は Wikimedia Commons（作者・ライセンスは card_files の credit）"},
       "note": "題・日付・リンクは各館の公式フィードと BODIK のイベント一覧から（要約は日付と受付の状態を読むだけで載せない）。画像は フィードの画像 → ページの og:image → Wikimedia Commons の順で、縮めて出典付き。館から言われたら blocklist で外す。"}
json.dump(doc, open(os.path.join(OUT, "board.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
with open(os.path.join(OUT, "board_filter.log"), "w", encoding="utf-8") as f:
    f.write("# %s の仕分け。DROP 出どころ 理由 題 / KEEP / LOG\n" % today.isoformat())
    for d in dropped:
        f.write("DROP\t%s\t%s\t%s\n" % tuple(clean(str(x)) for x in d))
    for c in items_out:
        f.write("KEEP\t%s\t%s\t%s\t%s\t%s\n" % (c["venue_id"], c["cat"], c["kind"], c["date"], c["title"]))
    for l in log:
        f.write("LOG\t%s\n" % "\t".join(clean(str(x)) for x in l))
for x in sorted(net.slow, reverse=True)[:8]:
    print("  遅かった", *x)
print("board.txt", len(sel), "件", "画像", len(cards), "分野", dict(Counter(c["cat"] for c in sel)), "地域", dict(sorted(Counter(c["region"] for c in sel).items())),
      "読んだ", net.count, "%.0f 秒" % (time.time() - T0))
