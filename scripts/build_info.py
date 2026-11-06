# 情報パネル: 各館の公式フィード（RSS/Atom）→ info.json / info.txt、画像の枠 slots/slot_00.jpg〜（Wikimedia Commons の CC 画像だけ）
# 守ること: robots.txt を見る・1 日 1 回・名乗る User-Agent・フィードの画像は使わない・出典とリンクを必ず付ける
import json, os, sys, re, datetime, hashlib, io, urllib.parse, urllib.robotparser, xml.etree.ElementTree as ET
from common import fetch, HERE
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "out")
SRC = json.load(open(os.path.join(HERE, "sources.json"), encoding="utf-8"))
os.makedirs(os.path.join(OUT, "slots"), exist_ok=True)
today = datetime.date.today()


def robots_ok(url):
    p = urllib.parse.urlparse(url)
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(fetch("%s://%s/robots.txt" % (p.scheme, p.netloc), 15).splitlines())
        return rp.can_fetch("just-planetarium-data", url)
    except Exception:
        return True   # robots.txt がない・読めない = 制限なし


def strip(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def parse_feed(txt):
    root = ET.fromstring(txt.encode("utf-8"))
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        g = {}
        for c in it:
            g.setdefault(c.tag.split("}")[-1], c)
        title = re.sub(r" - ニュース$", "", strip(g["title"].text) if "title" in g else "")
        link = ""
        if "link" in g:
            link = g["link"].get("href") or g["link"].text or ""
        d = ""
        for k in ("pubDate", "updated", "published", "date"):
            if k in g and g[k].text:
                d = g[k].text.strip()
                break
        out.append((title, link.strip(), d))
    return out


def norm_date(s):
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except Exception:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s or "")
        return m.group(1) if m else ""


items, report, dropped, kept = [], [], [], []
for f in SRC["feeds"]:
    try:
        if not robots_ok(f["url"]):
            report.append((f["id"], "robots.txt で不可"))
            continue
        ent = parse_feed(fetch(f["url"], 30))
    except Exception as e:
        report.append((f["id"], "失敗 " + str(e)[:60]))
        continue
    n = 0
    for title, link, d in ent:
        if not title or title == f["venue"] or not link.startswith("http"):
            continue
        bad = [x for x in SRC.get("exclude", []) if x in title]
        if bad:                                   # 展示・番組・イベントでない知らせ（休館・採用・入札・システム …）
            dropped.append((f["id"], "外す:" + bad[0], title))
            continue
        if not any(k in title for k in f["keywords"]):
            dropped.append((f["id"], "対象外", title))
            continue
        kept.append((f["id"], title))
        items.append({"src": f["id"], "venue": f["venue"], "kind": f["kind"], "title": title[:60], "date": norm_date(d), "url": link})
        n += 1
        if n >= 3:
            break
    report.append((f["id"], "%d 件（フィード %d）" % (n, len(ent))))
items.sort(key=lambda x: x["date"], reverse=True)
items = items[:SRC["max_items"]]


# --- 画像の枠: Wikimedia Commons の「館ごとのカテゴリ」の中の、許可リストのライセンスの写真だけ。日替わり ---
def commons_cat(cat, limit=100):
    u = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=categorymembers&gcmtype=file&gcmlimit=%d&gcmtitle=%s"
         "&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiurlwidth=%d") % (limit, urllib.parse.quote(cat), SRC["slot_w"] * 2)
    return json.loads(fetch(u, 30)).get("query", {}).get("pages", {}).values()


def lic_ok(meta):
    s = (meta.get("LicenseShortName", {}).get("value", "") or "").replace("CC BY SA", "CC BY-SA").strip()
    return any(s.upper() == a.upper() for a in SRC["commons_allowed_licenses"]) and meta.get("NonFree", {}).get("value", "") != "true"


slots, W, H = [], SRC["slot_w"], SRC["slot_h"]
cats = sorted(SRC["commons_categories"], key=lambda c: hashlib.md5((c["cat"] + str(today)).encode()).hexdigest())
cand = {}    # カテゴリ -> 条件に合う写真（日替わりの順）
for c in cats:
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
    cand[c["cat"]] = good
    report.append(("commons:" + c["cat"], "%d 枚（カテゴリ内 %d）" % (len(good), len(pages))))
seen = set()
for rnd in range(3):                # 1 周目は各カテゴリから 1 枚ずつ（偏らせない）。足りなければ 2 周目
    for c in cats:
        if len(slots) >= SRC["slots"]:
            break
        for p, ii, meta in cand.get(c["cat"], []):
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

doc = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "items": items, "slots": slots,
       "note": "題・日付・リンクは各館の公式フィードから。画像は Wikimedia Commons の CC 等のみ（slots の license / artist / page）。チラシ等の画像は転載しない。"}
json.dump(doc, open(os.path.join(OUT, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
with open(os.path.join(OUT, "info.txt"), "w", encoding="utf-8", newline="\n") as f:   # Udon 用: タブ区切り。#items の行 → #slots の行
    f.write("#items\n")
    for it in items:
        f.write("\t".join([it["venue"], it["title"], it["date"], it["url"]]) + "\n")
    f.write("#slots\n")
    for s in slots:
        f.write("\t".join([s["file"], s["title"][:50], s["artist"], s["license"], s["credit"]]) + "\n")
with open(os.path.join(OUT, "info_filter.log"), "w", encoding="utf-8") as f:   # 仕分けの記録（外した物・残した物）
    for d in dropped:
        f.write("DROP\t%s\t%s\t%s\n" % d)
    for k in kept:
        f.write("KEEP\t%s\t%s\n" % k)
for r in report:
    print(*r)
print("dropped", len(dropped), "kept", len(kept))
print("items", len(items), "slots with image", sum(1 for s in slots if s["license"]))
