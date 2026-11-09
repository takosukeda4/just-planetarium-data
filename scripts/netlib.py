# 通信の共通部分（find_feeds.py・build_board.py）: 名乗る User-Agent・ホストごとに 1 秒以上空ける・robots.txt に従う
#   並列にするのは別のホストどうしだけ（同じホストへはロックで 1 本ずつ、前の読み込みから min_gap 秒あける。Crawl-delay があればそれに従う、10 秒まで）
#   証明書で失敗したら curl でもう 1 回（common.fetch と同じ）
import json, os, re, ssl, subprocess, threading, time, urllib.parse, urllib.request, urllib.error, urllib.robotparser
from common import UA

ROBOT_NAME = "just-planetarium-data"


class Resp:
    def __init__(self, status, url, body=b"", ctype="", err=""):
        self.status, self.url, self.body, self.ctype, self.err = status, url, body, ctype, err

    @property
    def ok(self):
        return self.status == 200 and not self.err


class Net:
    def __init__(self, min_gap=1.1, banned_hosts=(), log=None, cache_dir=""):
        self.min_gap = min_gap
        self.cache_dir = cache_dir   # 手元で何度も試すとき: 1 回読んだ物を取っておいて使い回す（館のサイトを何度も読まない）
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        self.banned = [h.lower() for h in banned_hosts]
        self._lock = threading.Lock()
        self._host = {}          # host -> [Lock, 次に読んでよい時刻, 間隔]
        self._robots = {}        # scheme://host -> RobotFileParser か None（制限なし）か False（全部不可）
        self._rlock = {}
        self.count = 0
        self.slow = []          # 10 秒より長くかかった読み込み (秒, URL, 結果)
        self._tmo = {}
        self.dead = set()        # 名前が引けない・つながらないホスト（2 回目からは読まない）
        self.log = log

    def banned_url(self, url):
        h = (urllib.parse.urlparse(url).hostname or "").lower()
        return any(h == b or h.endswith("." + b) for b in self.banned)

    def _slot(self, host):
        with self._lock:
            s = self._host.get(host)
            if s is None:
                s = self._host[host] = [threading.Lock(), 0.0, self.min_gap]
            return s

    def _raw(self, url, timeout, maxbytes):
        url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")     # 日本語の入った URL（画像のファイル名など）
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "ja,en;q=0.5"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(maxbytes + 1)
                if len(body) > maxbytes:
                    return Resp(200, r.geturl(), b"", r.headers.get("Content-Type", ""), "大きすぎる")
                return Resp(r.status, r.geturl(), body, r.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as e:
            return Resp(e.code, url, b"", "", "HTTP %d" % e.code)
        except urllib.error.URLError as e:
            if "CERTIFICATE" in str(e):
                return self._curl(url, timeout, maxbytes)
            return Resp(0, url, b"", "", "URL " + str(e.reason)[:60])
        except ssl.SSLError as e:
            return self._curl(url, timeout, maxbytes)
        except Exception as e:
            return Resp(0, url, b"", "", type(e).__name__ + " " + str(e)[:60])

    def _curl(self, url, timeout, maxbytes):
        try:
            p = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "--max-filesize", str(maxbytes), "-A", UA,
                                "-w", "\n@@%{http_code}@@%{url_effective}@@%{content_type}", url], capture_output=True, timeout=timeout + 10)
        except Exception as e:
            return Resp(0, url, b"", "", "curl " + str(e)[:40])
        b = p.stdout
        i = b.rfind(b"\n@@")
        if i < 0:
            return Resp(0, url, b"", "", "curl の失敗 %d" % p.returncode)
        meta = b[i + 3:].decode("utf-8", "replace").split("@@")
        code = int(meta[0] or 0)
        return Resp(code, meta[1] if len(meta) > 1 else url, b[:i] if code == 200 else b"", meta[2] if len(meta) > 2 else "",
                    "" if code == 200 else ("HTTP %d" % code if code else "curl の失敗 %d" % p.returncode))

    def _get_throttled(self, url, timeout, maxbytes):
        cfn = ""
        if self.cache_dir:
            import hashlib
            cfn = os.path.join(self.cache_dir, hashlib.md5(url.encode()).hexdigest())
            if os.path.exists(cfn + ".json"):
                m = json.load(open(cfn + ".json", encoding="utf-8"))
                body = open(cfn + ".bin", "rb").read() if os.path.exists(cfn + ".bin") else b""
                return Resp(m["status"], m["url"], body, m["ctype"], m["err"])
        r = self._get_live(url, timeout, maxbytes)
        if cfn and r.status != 0:
            json.dump({"status": r.status, "url": r.url, "ctype": r.ctype, "err": r.err}, open(cfn + ".json", "w", encoding="utf-8"))
            if r.body:
                open(cfn + ".bin", "wb").write(r.body)
        return r

    def _get_live(self, url, timeout, maxbytes):
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host in self.dead:
            return Resp(0, url, b"", "", "つながらないホスト")
        s = self._slot(host)
        with s[0]:
            w = s[1] - time.time()
            if w > 0:
                time.sleep(w)
            t = time.time()
            r = self._raw(url, timeout, maxbytes)
            if time.time() - t > 10:
                self.slow.append((round(time.time() - t), url[:100], r.err or str(r.status)))
            s[1] = time.time() + s[2]
        with self._lock:
            self.count += 1
        # 名前が引けない・断られた = すぐ止める。時間切れは 3 回で止める（大きな CDN が 1 回遅いだけで止めない）
        if r.status == 0 and re.search(r"getaddrinfo|Name or service|nodename|No address|Connection refused|unreachable", r.err or ""):
            self.dead.add(host)
        elif r.status == 0 and "timed out" in (r.err or ""):
            with self._lock:
                self._tmo[host] = self._tmo.get(host, 0) + 1
                if self._tmo[host] >= 3:
                    self.dead.add(host)
        return r

    def robots(self, url):
        p = urllib.parse.urlparse(url)
        key = "%s://%s" % (p.scheme, p.netloc)
        with self._lock:
            lk = self._rlock.setdefault(key, threading.Lock())
        with lk:
            if key in self._robots:
                return self._robots[key]
            r = self._get_throttled(key + "/robots.txt", 15, 500000)
            if r.status in (401, 403):
                rp = False
            elif r.ok and r.body:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(r.body.decode("utf-8", "replace").splitlines())
                cd = rp.crawl_delay(ROBOT_NAME)
                if cd:
                    try:
                        self._slot(p.hostname.lower())[2] = max(self.min_gap, min(10.0, float(cd)))
                    except (TypeError, ValueError):
                        pass
            else:
                rp = None   # robots.txt が無い・読めない = 制限なし
            self._robots[key] = rp
            return rp

    def allowed(self, url):
        rp = self.robots(url)
        if rp is False:
            return False
        return True if rp is None else rp.can_fetch(ROBOT_NAME, url)

    def get(self, url, timeout=20, maxbytes=3_000_000, robots=True):
        """robots.txt を見てから読む。不可なら status=-1。robots=False は公開の API（Wikimedia・BODIK）だけ"""
        if self.banned_url(url):
            return Resp(-2, url, b"", "", "使わない所")
        if not url.startswith("http"):
            return Resp(-3, url, b"", "", "http でない")
        if robots and not self.allowed(url):
            return Resp(-1, url, b"", "", "robots.txt で不可")
        return self._get_throttled(url, timeout, maxbytes)


def decode_html(b, ctype=""):
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I) or re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", b[:4000], re.I)
    enc = m.group(1) if m else "utf-8"
    enc = enc.decode() if isinstance(enc, bytes) else enc
    try:
        return b.decode(enc, "replace")
    except LookupError:
        return b.decode("utf-8", "replace")


def og_image(html_text, base):
    for pat in (r"<meta[^>]+property=[\"']og:image(?::url)?[\"'][^>]*content=[\"']([^\"']+)",
                r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*property=[\"']og:image(?::url)?[\"']",
                r"<meta[^>]+name=[\"']twitter:image[\"'][^>]*content=[\"']([^\"']+)"):
        m = re.search(pat, html_text, re.I)
        if m:
            import html as H
            return urllib.parse.urljoin(base, H.unescape(m.group(1).strip()))
    return ""
