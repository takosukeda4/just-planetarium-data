# 共通: 取得（urllib、証明書で失敗したら curl）・場所の一覧
import csv, os, subprocess, urllib.request, urllib.error, json
HERE = os.path.dirname(os.path.abspath(__file__))
UA = "just-planetarium-data/1.0 (VRChat world data; non-commercial)"

def fetch(url, timeout=30, binary=False):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
    except urllib.error.URLError as e:
        if "CERTIFICATE" not in str(e): raise
        b = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", UA, url], capture_output=True, check=True).stdout
    return b if binary else b.decode("utf-8", "replace")

def places():
    """cities.csv（ワールドの「今の空」の都市。順番はワールドの cityName と同じ）→ extra_japan.csv"""
    out = []
    for fn in ("cities.csv", "extra_japan.csv"):
        with open(os.path.join(HERE, fn), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.append({"name": r["name"], "short": r["short"], "lat": float(r["lat"]), "lon": float(r["lon"])})
    return out
