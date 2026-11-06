# 今の降水 → out/rain.json（人が読む用）と out/rain.txt（Udon が読む用の短い文字）
# データ: Open-Meteo.com（CC BY 4.0、非商用）。クレジット「Weather data by Open-Meteo.com」を json の credit に入れる
import json, os, sys, datetime, urllib.parse
from common import fetch, places

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out")
os.makedirs(OUT, exist_ok=True)

def level(code, precip, snow):
    """0 なし 1 小雨 2 雨 3 強い雨 4 雪 5 雷雨"""
    if code in (95, 96, 99): return 5
    if snow > 0 or code in (71, 73, 75, 77, 85, 86): return 4
    if code in (65, 67, 82) or precip >= 4.0: return 3
    if precip >= 0.5 or code in (63, 81, 55, 57): return 2
    if precip > 0 or code in (51, 53, 56, 61, 80): return 1
    return 0

P = places()
lv, mm, cloud = [], [], []
stamp = None
for i in range(0, len(P), 25):                      # 1 回に 25 地点（URL が長くなりすぎず、1 回の返事が重くならないように）
    ch = P[i:i + 25]
    q = {"latitude": ",".join(str(p["lat"]) for p in ch), "longitude": ",".join(str(p["lon"]) for p in ch),
         "current": "precipitation,snowfall,weather_code,cloud_cover", "timezone": "GMT"}
    # GitHub Actions からは時間切れになることがあるので、60 秒待ちで 4 回まで試す（2026-11-06 の 1 回目の実行で時間切れ）
    d = json.loads(fetch("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q, safe=","), timeout=60, retries=4))
    d = d if isinstance(d, list) else [d]
    for x in d:
        c = x["current"]; stamp = stamp or c["time"]
        lv.append(level(c["weather_code"], c["precipitation"], c["snowfall"]))
        mm.append(round(c["precipitation"], 1)); cloud.append(c["cloud_cover"])
assert len(lv) == len(P)
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
doc = {"updated": now, "observed": stamp + "Z", "credit": "Weather data by Open-Meteo.com (CC BY 4.0)", "legend": "0 none 1 light 2 rain 3 heavy 4 snow 5 thunder",
       "n": len(P), "levels": "".join(map(str, lv)), "mm": mm, "cloud": cloud,
       "places": [{"i": i, "name": p["name"], "lat": p["lat"], "lon": p["lon"], "lv": lv[i], "mm": mm[i]} for i, p in enumerate(P)]}
with open(os.path.join(OUT, "rain.json"), "w", encoding="utf-8") as f: json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
# Udon 用: 1 観測時刻 / 2 レベルの文字列 / 3 mm / 4 雲量(%) / 5 緯度 / 6 経度（3〜6 はカンマ区切り。5・6 で一番近い地点を Udon が選ぶ）
with open(os.path.join(OUT, "rain.txt"), "w", encoding="utf-8", newline="\n") as f:
    f.write(f"{stamp}\n{doc['levels']}\n{','.join(map(str, mm))}\n{','.join(map(str, cloud))}\n")
    f.write(",".join("%g" % p["lat"] for p in P) + "\n" + ",".join("%g" % p["lon"] for p in P) + "\n")   # 5・6 行目: 緯度・経度
print("rain: %d places, raining %d" % (len(P), sum(1 for v in lv if v)))
