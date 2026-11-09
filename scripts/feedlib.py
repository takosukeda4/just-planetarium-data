# フィードの読み取りと日付の判定（build_info.py と build_board.py で共通）
# 2026-11-09: build_info.py から移した（中身は同じ。build_info.py の出力は変わらない）
import re, datetime, unicodedata, urllib.parse, html, xml.etree.ElementTree as ET

JST = datetime.timezone(datetime.timedelta(hours=9))


def strip(s):
    s = re.sub(r"&(nbsp|#160);", " ", s or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


IMG_SRC = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def _items(root, base_url=""):
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
        if tag == "entry" and base_url:                   # Atom: rel="alternate" の link を優先（build_board だけ。build_info は前のまま）
            for c in it:
                if c.tag.split("}")[-1] == "link" and c.get("rel", "alternate") == "alternate" and c.get("href"):
                    link = c.get("href")
                    break
        d = ""
        for k in ("pubDate", "updated", "published", "date"):
            if k in g and g[k].text:
                d = g[k].text.strip()
                break
        desc, raw = "", ""
        for k in ("description", "summary", "encoded", "content"):
            if k in g and (g[k].text or "").strip():
                raw = g[k].text
                desc = strip(raw)
                break
        # QR は短い方の URL に（WordPress の guid「?p=番号」は元のページへ飛ぶ。長い日本語の URL だと QR が細かくなる）
        link = link.strip()
        guid = (g["guid"].text or "").strip() if "guid" in g else ""
        short = guid if (re.match(r"https?://[^?#\s]+/\?(?:p|page_id)=\d+$", guid) and urllib.parse.urlparse(guid).netloc == urllib.parse.urlparse(link).netloc
                         and len(guid) < len(link)) else link
        # 画像（build_board 用）: enclosure / media:content / media:thumbnail / 本文の最初の <img>
        img = ""
        for c in it.iter():
            t = c.tag.split("}")[-1]
            if t == "enclosure" and (c.get("type") or "").startswith("image") and c.get("url"):
                img = c.get("url"); break
            if t in ("content", "thumbnail") and c.get("url") and (c.get("medium") in (None, "image")) and \
                    (t == "thumbnail" or (c.get("type") or "image").startswith("image")):
                img = c.get("url"); break
        if not img:
            for k in ("encoded", "content", "description", "summary"):
                if k in g and g[k].text:
                    m = IMG_SRC.search(g[k].text)
                    if m:
                        img = html.unescape(m.group(1)); break
        if base_url:
            link = urllib.parse.urljoin(base_url, link) if link else link
            img = urllib.parse.urljoin(link or base_url, img) if img else img
        out.append({"title": title, "link": link, "date": d, "desc": desc[:1500], "short": short, "img": img})
    return out


def parse_feed(txt):
    """build_info 用: [(題, リンク, 日付の字, 要約, 短いリンク)]"""
    root = ET.fromstring(txt.encode("utf-8"))
    return [(x["title"], x["link"], x["date"], x["desc"], x["short"]) for x in _items(root)]


CTRL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
BAD_AMP = re.compile(rb"&(?!(?:[A-Za-z][A-Za-z0-9]{0,30}|#\d{1,7}|#x[0-9A-Fa-f]{1,6});)")


def parse_feed_bytes(raw, base_url=""):
    """build_board 用: バイトのまま読む（Shift_JIS などの宣言に従う）。壊れた XML は制御文字・裸の & を直してもう 1 回"""
    raw = raw.lstrip(b"\xef\xbb\xbf \t\r\n")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        root = ET.fromstring(BAD_AMP.sub(b"&amp;", CTRL.sub(b"", raw)))
    if root.tag.split("}")[-1] not in ("rss", "feed", "RDF", "channel"):
        raise ValueError("フィードでない: " + root.tag[:40])
    return _items(root, base_url)


def norm_date(s):
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).astimezone(JST).date()
    except Exception:
        m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", (s or "").strip())
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
        except ValueError:
            return None


# --- 題・要約から日付を読む ---
DATE_RE = re.compile(r"(20\d\d)年(\d{1,2})月(\d{1,2})日"            # 2026年11月21日
                     r"|(?<![\d/.])(20\d\d)[./](\d{1,2})[./](\d{1,2})(?![\d])"   # 2026.10.30 / 2026/11/28
                     r"|(?<![\d])(\d{1,2})月(\d{1,2})日"            # 11月14日
                     r"|(?<![\d/.:])(\d{1,2})/(\d{1,2})(?![\d/])")  # 11/13
WEEK = re.compile(r"\s*\([^()]{1,6}\)")                              # (土) (月・祝)
CONT = re.compile(r"\s*(?:[、,・&]|~|-|から)\s*(?:(\d{1,2})月)?(\d{1,2})日?(?![\d/月年.])")   # 、15日 ・14 ~23日
STAMP_AFTER = re.compile(r"\s*\)?\s*(?:更新|現在|時点|発行|公開|掲載|追記|発表)")
DL_AFTER = re.compile(r"\s*\)?\s*(?:〆切|〆|締切|締め切|必着|まで受付|までに申|申込締)")
DL_BEFORE = re.compile(r"(?:〆切|締切|締め切り|申込期限|応募締切|申込締切|受付期間|申込期間)[^\d]{0,4}$")
UNTIL_AFTER = re.compile(r"\s*\)?\s*まで")
LABEL_EV = re.compile(r"(?:日時|開催日時?|日程|期間|会期|実施日|上映期間|投影期間|開催期間|とき)\s*[:：]?")
LABEL_DL = re.compile(r"(?:〆切|締切|締め切り|申込期限|応募締切|申込締切)\s*[:：]?")


def norm_text(s):
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("〜", "~").replace("～", "~")
    return re.sub(r"\s*([年月日])\s*", r"\1", s)


def mkdate(y, m, d, base):
    """年が無いときは、元の日（発表日）から 45 日前より後で一番近い年に"""
    try:
        if y:
            return datetime.date(int(y), int(m), int(d))
        for yy in (base.year - 1, base.year, base.year + 1):
            dt = datetime.date(yy, int(m), int(d))
            if dt >= base - datetime.timedelta(days=45):
                return dt
    except ValueError:
        return None
    return None


def find_dates(s, base):
    """[(日付, 役目)]。役目は event（開催の日）・until（〜まで）・deadline（〆切）。更新日などの判は除く"""
    s = norm_text(s)
    out = []
    for m in DATE_RE.finditer(s):
        g = m.groups()
        if g[0]:
            y, mo, d = g[0], g[1], g[2]
        elif g[3]:
            y, mo, d = g[3], g[4], g[5]
        elif g[6]:
            y, mo, d = None, g[6], g[7]
        else:
            y, mo, d = None, g[8], g[9]
        dt = mkdate(y, mo, d, base)
        if not dt:
            continue
        ds = [dt]
        j = m.end()
        w = WEEK.match(s, j)
        j = w.end() if w else j
        while True:                                   # 11月14日（土）、15日（日） / 11/7(土)・14(土)
            c = CONT.match(s, j)
            if not c:
                break
            d2 = mkdate(None, c.group(1) or dt.month, c.group(2), dt)
            if not d2 or (d2 - dt).days > 120:
                break
            ds.append(d2)
            j = c.end()
            w = WEEK.match(s, j)
            j = w.end() if w else j
        before, after = s[max(0, m.start() - 8):m.start()], s[j:j + 12]
        if STAMP_AFTER.match(after) or before.endswith("更新"):
            continue
        if DL_AFTER.match(after) or DL_BEFORE.search(before):
            role = "deadline"
        elif UNTIL_AFTER.match(after):
            role = "until"
        else:
            role = "event"
        out += [(x, role) for x in ds]
    return out


def labelled_dates(desc, base):
    """要約は「日時：」「締切：」などの見出しのすぐ後だけを読む（本文の昔の日付を拾わない）"""
    s = norm_text(desc)
    out = []
    for m in LABEL_DL.finditer(s):
        out += [(d, "deadline") for d, r in find_dates(s[m.end():m.end() + 30], base)][:1]
    for m in LABEL_EV.finditer(s):
        out += [(d, r) for d, r in find_dates(s[m.end():m.end() + 45], base)][:3]
    return out


def judge_dates(title, desc, pub, today, R, future_pub_is_event=False):
    """日付で決める: (残すか, 理由, 情報)。情報は kind（event/until/news）・date・end・deadline。
    〆切や開催日が過ぎた物・先すぎる物・古い知らせ・日付の無い物は外す（build_info の judge の後半と同じ）"""
    base = pub or today
    ds = find_dates(title, base)
    if not [d for d, r in ds if r != "deadline"]:
        ds += labelled_dates(desc, base)
    ev = [d for d, r in ds if r in ("event", "until")]
    dl = [d for d, r in ds if r == "deadline"]
    if pub and pub > today and not ev and future_pub_is_event:
        ev = [pub]                             # 発表日が先の日付になっている館（る・く・る）は、それを開催日とみる
    if dl and max(dl) < today:
        return False, "〆切が過ぎた(%s)" % max(dl).isoformat(), None
    if ev:
        end = max(ev)
        if end < today:
            return False, "開催日が過ぎた(%s)" % end.isoformat(), None
        nxt = min(d for d in ev if d >= today)
        if (nxt - today).days > R["future_days"]:
            return False, "先すぎる(%s)" % nxt.isoformat(), None
        until = any(r == "until" for d, r in ds) and min(ev) <= today
        return True, "", {"kind": "until" if until else "event", "date": nxt, "end": end, "deadline": max(dl) if dl else None, "start": min(ev)}
    if not pub:
        return False, "日付なし", None
    if pub > today + datetime.timedelta(days=1):
        return False, "日付が読めない（発表日が先の日付 %s）" % pub.isoformat(), None
    age = (today - pub).days
    if age > R["news_days"]:
        return False, "古い知らせ(%s)" % pub.isoformat(), None
    return True, "", {"kind": "news", "date": pub, "end": None, "deadline": max(dl) if dl else None, "start": None}
