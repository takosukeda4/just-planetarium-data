# 共通: 取得（urllib、証明書で失敗したら curl）・場所の一覧
import csv, os, subprocess, time, urllib.request, urllib.error, json
HERE = os.path.dirname(os.path.abspath(__file__))
UA = "just-planetarium-data/1.0 (VRChat world data; non-commercial)"

def fetch(url, timeout=30, binary=False, retries=1):
    """retries 回まで試す。時間切れ・接続の切断・429・5xx のときだけ、少し待ってやり直す"""
    for n in range(retries):
        last = n == retries - 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
            break
        except urllib.error.HTTPError as e:
            if (e.code != 429 and e.code < 500) or last: raise
        except urllib.error.URLError as e:
            if "CERTIFICATE" in str(e):
                b = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", UA, url], capture_output=True, check=True).stdout
                break
            if last: raise
        except (TimeoutError, ConnectionError):
            if last: raise
        time.sleep(5 * (n + 1))
    return b if binary else b.decode("utf-8", "replace")

def places():
    """cities.csv（ワールドの「今の空」の都市。順番はワールドの cityName と同じ）→ extra_japan.csv"""
    out = []
    for fn in ("cities.csv", "extra_japan.csv"):
        with open(os.path.join(HERE, fn), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.append({"name": r["name"], "short": r["short"], "lat": float(r["lat"]), "lon": float(r["lon"])})
    return out
