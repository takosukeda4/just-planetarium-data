# 情報パネル: 各館の公式フィード（RSS/Atom）→ info.json / info.txt / qr.png、画像の枠 slots/slot_00.jpg〜（Wikimedia Commons の CC 画像だけ）
# 守ること: robots.txt を見る・1 日 1 回・名乗る User-Agent・フィードの画像と要約は載せない（要約は日付・受付の状態を読むだけ）・出典とリンクを必ず付ける
# 出す物（R65、2026-11-06 B14a）: これから開かれるイベント（先の物も）と、30 日以内の知らせ。
#   出さない物: 受付が終わった物・〆切が過ぎた物・開催日が過ぎた物・中止・開催報告など終わったことの知らせ。外した物と理由は info_filter.log
#   並べ方: ① イベント（次の開催日が近い順。開催中で「〜まで」の物は終わりの日）→ ② 知らせ（新しい順）
# 環境変数（手元で試すとき）: INFO_CACHE=フォルダ（フィードを 1 回だけ読んで取っておく）、INFO_TODAY=YYYY-MM-DD、SKIP_SLOTS=1（写真の枠を作らない）
import json, os, sys, re, datetime, hashlib, io, unicodedata, urllib.parse, urllib.robotparser, xml.etree.ElementTree as ET
from common import fetch, HERE
from feedlib import strip, parse_feed, norm_date, norm_text, judge_dates
from PIL import Image, ImageDraw, ImageFilter

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "out")
SRC = json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))
os.makedirs(os.path.join(OUT, "slots"), exist_ok=True)
JST = datetime.timezone(datetime.timedelta(hours=9))
today = datetime.date.fromisoformat(os.environ["INFO_TODAY"]) if os.environ.get("INFO_TODAY") else datetime.datetime.now(JST).date()
CACHE = os.environ.get("INFO_CACHE", "")
R = SRC["rules"]


def cfetch(url, timeout=30):
    """INFO_CACHE があれば、1 回読んだ物を取っておいて使い回す（手元で何度も試すとき、館のサイトを何度も読まない）"""
    if not CACHE:
        return fetch(url, timeout)
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".txt")
    if os.path.exists(fn):
        return open(fn, encoding="utf-8").read()
    t = fetch(url, timeout)
    open(fn, "w", encoding="utf-8").write(t)
    return t


def robots_ok(url):
    p = urllib.parse.urlparse(url)
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(cfetch("%s://%s/robots.txt" % (p.scheme, p.netloc), 15).splitlines())
        return rp.can_fetch("just-planetarium-data", url)
    except Exception:
        return True   # robots.txt がない・読めない = 制限なし


# フィードの読み取り・日付の読み取りは feedlib.py に移した（2026-11-09、build_board.py と共通）


CLOSED_T = re.compile(R["closed_title"])
CLOSED_D = re.compile(R["closed_desc"])
ASTRO = re.compile(R["astro_words"])
EVENTW = re.compile(R["event_words"])
SCI = re.compile(R["science_words"])   # 足りないときに埋める科学の催し（講座・教室は、科学の言葉があるときだけ）


def judge(f, title, desc, pub):
    """(残すか, 理由, 情報)"""
    bad = [x for x in SRC.get("exclude", []) if x in title]
    if bad:                                   # 展示・番組・イベントでない知らせ（休館・採用・入札・システム …）
        return False, "外す:" + bad[0], None
    tt = norm_text(title)
    m = CLOSED_T.search(tt) or CLOSED_D.search(norm_text(desc))
    if m:
        return False, "受付終了・終わった物:" + m.group(0), None
    # 館の種類で、題に要る言葉を変える。美術館・博物館は星・宇宙・天文の言葉がある物だけ
    if f["kind"] in ("museum", "space"):
        if not ASTRO.search(tt):
            return False, "対象外（星・宇宙の言葉なし）", None
    else:                                     # プラネタリウム・科学館・天文台: 星の言葉か、催しの言葉
        if not (ASTRO.search(tt) or EVENTW.search(tt) or (f.get("desc_keywords") and ASTRO.search(norm_text(desc)))):
            return False, "対象外（催し・星の言葉なし）", None
    ok, why, info = judge_dates(title, desc, pub, today, R, f.get("future_pub_is_event"))
    if not ok:
        return False, why, None
    info.pop("start", None)
    info["astro"] = bool(ASTRO.search(tt)) or f["kind"] == "astro"
    return True, "", info


cand, report, dropped = [], [], []
for f in SRC["feeds"]:
    if f.get("off"):
        continue
    try:
        if not robots_ok(f["url"]):
            report.append((f["id"], "robots.txt で不可"))
            continue
        ent = parse_feed(cfetch(f["url"], 30))
    except Exception as e:
        report.append((f["id"], "失敗 " + str(e)[:60]))
        continue
    n = 0
    seen_t = set()
    for title, link, d, desc, short in ent:
        if not title or title == f["venue"] or not link.startswith("http") or title in seen_t:
            continue
        seen_t.add(title)
        pub = norm_date(d)
        ok, why, info = judge(f, title, desc, pub)
        if not ok:
            dropped.append((f["id"], why, title))
            continue
        info.update({"src": f["id"], "venue": f["venue"], "title": title, "url": link, "qr_url": short, "pub": pub})
        cand.append(info)
        n += 1
    report.append((f["id"], "%d 件（フィード %d）" % (n, len(ent))))

# 選ぶ: 星・宇宙の物（題に星・宇宙の言葉がある物と、天文台の物）は全部。科学館のほかの催しは、題に science_words（サイエンス・実験・工作・観察 …）が
#   ある物だけを、全部で target 件になるまで近い順に足す（クマ対策の講座・手形アートのような物は出さない）。
#   1 館 per_venue 件まで。古い物で埋めない（足りなければ少ないまま）
# 並べる: イベント（次の日が近い順。開催中の「〜まで」の物はその日）→ 知らせ（新しい順）。全部で max_items 件まで
order = lambda x: (0, x["date"].toordinal(), x["venue"]) if x["kind"] != "news" else (1, -x["date"].toordinal(), x["venue"])
per, sel = {}, []
for c in sorted(cand, key=lambda x: (not x["astro"],) + order(x)):
    if per.get(c["src"], 0) >= SRC["per_venue"]:
        dropped.append((c["src"], "1 館 %d 件まで" % SRC["per_venue"], c["title"]))
        continue
    if not c["astro"] and not SCI.search(norm_text(c["title"])):
        dropped.append((c["src"], "星・宇宙・科学の催しでない", c["title"]))
        continue
    if not c["astro"] and len(sel) >= SRC["target"]:
        dropped.append((c["src"], "星・宇宙の物でなく、%d 件に足りている" % SRC["target"], c["title"]))
        continue
    per[c["src"]] = per.get(c["src"], 0) + 1
    sel.append(c)
sel.sort(key=order)
items = sel[:SRC["max_items"]]
dropped += [(c["src"], "全部で %d 件まで" % SRC["max_items"], c["title"]) for c in sel[SRC["max_items"]:]]


# --- QR: 件ごとの元のページの QR を 1 枚の qr.png（正方形）に。マス i = 件 i（左上から右へ、行ごと） ---
Q = SRC["qr"]
QS, QC, QR_ROWS = Q["size"], Q["cols"], Q["rows"]
QCELL = QS // QC
qr_img = Image.new("L", (QS, QS), 255)
qr_ok = 0
try:
    import segno
except ImportError:
    segno = None
try:
    import zxingcpp                                  # 作った QR を読み直して確かめる（入っていれば）
except ImportError:
    zxingcpp = None
def qr_reads(img, want):
    """そのまま・縮めて・ぼかして JPEG にして、の 3 つとも読めるか（携帯のカメラに近い悪い条件）"""
    w = img.width
    b = io.BytesIO()
    img.resize((round(w * 0.75),) * 2, Image.BILINEAR).filter(ImageFilter.GaussianBlur(0.8)).save(b, "JPEG", quality=50)
    for t in (img, img.resize((round(w * 0.7),) * 2, Image.BILINEAR), Image.open(b)):
        got = [x.text for x in zxingcpp.read_barcodes(t)]
        if got != [want]:
            return False
    return True


for i, it in enumerate(items):
    it["qr"] = -1
    if not segno or i >= QC * QR_ROWS:
        continue
    q = segno.make(it["qr_url"], error=Q["error"], micro=False, boost_error=True)
    rows = [list(r) for r in q.matrix_iter(scale=1, border=Q["border"])]
    n = len(rows)
    sc = QCELL // n
    if sc < Q["min_px"]:
        dropped.append((it["src"], "QR なし: 細かすぎる（版 %s、%d モジュール）" % (q.version, n), it["title"]))
        continue
    cell = Image.new("L", (QCELL, QCELL), 255)       # マスの大きさのまま（周りの白は 4 モジュール以上になる）
    dr = ImageDraw.Draw(cell)
    ox = (QCELL - n * sc) // 2
    for y, r in enumerate(rows):
        for x, v in enumerate(r):
            if v:
                dr.rectangle([ox + x * sc, ox + y * sc, ox + x * sc + sc - 1, ox + y * sc + sc - 1], fill=0)
    if zxingcpp and not qr_reads(cell, it["qr_url"]):
        dropped.append((it["src"], "QR なし: 読み直せない（版 %s、1 モジュール %d px）" % (q.version, sc), it["title"]))
        continue
    qr_img.paste(cell, ((i % QC) * QCELL, (i // QC) * QCELL))
    it["qr"] = i
    it["qr_ver"] = q.version
    qr_ok += 1
# 灰色（L）の PNG は、VRChat の画像の読み込み（ClientSim）で白が赤に出たので、RGB の PNG で書く（11/6 B14b のあと）
qr_img.convert("RGB").save(os.path.join(OUT, "qr.png"), optimize=True)


# --- 画像の枠: Wikimedia Commons の「館ごとのカテゴリ」の中の、許可リストのライセンスの写真だけ。日替わり ---
def commons_cat(cat, limit=100):
    u = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=categorymembers&gcmtype=file&gcmlimit=%d&gcmtitle=%s"
         "&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiurlwidth=%d") % (limit, urllib.parse.quote(cat), SRC["slot_w"] * 2)
    return json.loads(fetch(u, 30)).get("query", {}).get("pages", {}).values()


def lic_ok(meta):
    s = (meta.get("LicenseShortName", {}).get("value", "") or "").replace("CC BY SA", "CC BY-SA").strip()
    return any(s.upper() == a.upper() for a in SRC["commons_allowed_licenses"]) and meta.get("NonFree", {}).get("value", "") != "true"


slots, W, H = [], SRC["slot_w"], SRC["slot_h"]
if os.environ.get("SKIP_SLOTS"):
    old = os.path.join(OUT, "info.json")
    slots = json.load(open(old, encoding="utf-8"))["slots"] if os.path.exists(old) else []
cats = sorted(SRC["commons_categories"], key=lambda c: hashlib.md5((c["cat"] + str(today)).encode()).hexdigest())
pool = {}    # カテゴリ -> 条件に合う写真（日替わりの順）
for c in ([] if os.environ.get("SKIP_SLOTS") else cats):
    try:
        pages = list(commons_cat(c["cat"]))
    except Exception as e:
        report.append(("commons:" + c["cat"], "失敗 " + str(e)[:50]))
        continue
    good = []
    for p in pages:
        ii = (p.get("imageinfo") or [None])[0]
        if not ii or ii.get("mime") not in ("image/jpeg", "image/png"):
            continue
        meta = ii.get("extmetadata", {})
        if not lic_ok(meta) or ii["width"] < 1000 or ii["width"] < ii["height"]:   # 横長だけ
            continue
        if any(x in p["title"].lower() for x in SRC.get("commons_title_skip", [])):
            continue
        good.append((p, ii, meta))
    good.sort(key=lambda g: hashlib.md5((g[0]["title"] + str(today)).encode()).hexdigest())
    pool[c["cat"]] = good
    report.append(("commons:" + c["cat"], "%d 枚（カテゴリ内 %d）" % (len(good), len(pages))))
seen = set()
for rnd in range(3):                # 1 周目は各カテゴリから 1 枚ずつ（偏らせない）。足りなければ 2 周目
    for c in cats:
        if len(slots) >= SRC["slots"]:
            break
        for p, ii, meta in pool.get(c["cat"], []):
            if p["title"] in seen:
                continue
            try:
                im = Image.open(io.BytesIO(fetch(ii["thumburl"], 40, True))).convert("RGB")
            except Exception:
                continue
            r = max(W / im.width, H / im.height)                                      # 中央を切って 16:9 に
            im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
            l, t = (im.width - W) // 2, (im.height - H) // 2
            im = im.crop((l, t, l + W, t + H))
            i = len(slots)
            im.save(os.path.join(OUT, "slots", "slot_%02d.jpg" % i), "JPEG", quality=82, optimize=True)
            seen.add(p["title"])
            artist = strip(meta.get("Artist", {}).get("value", ""))[:60] or "unknown"
            lic = meta["LicenseShortName"]["value"]
            slots.append({"i": i, "file": "slots/slot_%02d.jpg" % i, "title": p["title"].replace("File:", ""), "venue": c["label"],
                          "artist": artist, "license": lic, "credit": "%s / %s / Wikimedia Commons" % (artist, lic),
                          "page": ii["descriptionurl"]})
            break
for i in range(len(slots), SRC["slots"]):   # 取れなかった枠は無地（URL を必ず存在させる = Udon が 404 を見ない）
    Image.new("RGB", (W, H), (20, 26, 40)).save(os.path.join(OUT, "slots", "slot_%02d.jpg" % i), "JPEG", quality=70)
    slots.append({"i": i, "file": "slots/slot_%02d.jpg" % i, "title": "", "venue": "", "artist": "", "license": "", "credit": "", "page": ""})

iso = lambda d: d.isoformat() if d else ""
items_out = [{"src": it["src"], "venue": it["venue"], "title": it["title"][:60], "date": iso(it["date"]), "kind": it["kind"],
              "end": iso(it["end"]), "deadline": iso(it["deadline"]), "pub": iso(it["pub"]), "url": it["url"], "qr_url": it["qr_url"], "qr": it["qr"]} for it in items]
qr_meta = {"file": "qr.png", "size": QS, "cols": QC, "rows": QR_ROWS, "cell": QCELL, "count": qr_ok,
           "note": "マス i = items[i]（左上から右へ、行ごと）。Udon の uvRect = (col*cell/size, 1-(row+1)*cell/size, cell/size, cell/size)"}
doc = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "today": today.isoformat(), "items": items_out,
       "qr": qr_meta, "slots": slots,
       "note": "題・日付・リンクは各館の公式フィードから（要約は日付と受付の状態を読むだけで載せない）。画像は Wikimedia Commons の CC 等のみ（slots の license / artist / page）。チラシ等の画像は転載しない。"}
json.dump(doc, open(os.path.join(OUT, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
with open(os.path.join(OUT, "info.txt"), "w", encoding="utf-8", newline="\n") as f:
    # Udon 用: タブ区切り。1 行目 #qr（いまの PlanetInfoPanel は #items より前の行を読み飛ばす）→ #items → #slots
    # #qr<TAB>ファイル<TAB>画像の一辺 px<TAB>列<TAB>行<TAB>マスの一辺 px<TAB>QR のある件の数
    # #items の行: 館 題 日付 URL ｜ ここから足した列: QR のマス(-1=なし) 種類(event/until/news) 終わりの日 〆切 発表日
    f.write("\t".join(["#qr", "qr.png", str(QS), str(QC), str(QR_ROWS), str(QCELL), str(qr_ok)]) + "\n")
    f.write("#items\n")
    for it in items_out:
        f.write("\t".join([it["venue"], it["title"], it["date"], it["url"], str(it["qr"]), it["kind"], it["end"], it["deadline"], it["pub"]]) + "\n")
    f.write("#slots\n")
    for s in slots:
        f.write("\t".join([s["file"], s["title"][:50], s["artist"], s["license"], s["credit"]]) + "\n")
with open(os.path.join(OUT, "info_filter.log"), "w", encoding="utf-8") as f:   # 仕分けの記録（外した物・残した物）
    f.write("# %s の仕分け。DROP 館 理由 題 / KEEP 館 種類 日付 題\n" % today.isoformat())
    for d in dropped:
        f.write("DROP\t%s\t%s\t%s\n" % d)
    for it in items_out:
        f.write("KEEP\t%s\t%s\t%s\t%s\n" % (it["src"], it["kind"], it["date"], it["title"]))
for r in report:
    print(*r)
print("dropped", len(dropped), "items", len(items), "qr", qr_ok, "slots with image", sum(1 for s in slots if s["license"]))
