# just-planetarium-data

VRChat ワールド「Just プラネタリウム」が読む、外のデータを作る道具と出来たデータです（ワールドのファイルは入っていません）。

- `scripts/build_rain.py` — 今の降水を地点ごとに（`rain.json` / `rain.txt`）。データ: Weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0)
- `scripts/build_info.py` — 全国のプラネタリウム・美術館などの公式フィードの題・日付・リンク（`info.json` / `info.txt`）と、Wikimedia Commons の CC 画像の枠（`slots/slot_00.jpg` ...）。画像の作者・ライセンスは `info.json` の slots に書いています。チラシなどの画像は転載しません。
- `.github/workflows/update.yml` — 30 分ごと（雨）・毎日 1 回（情報パネル）に更新して `gh-pages` に置きます。

非商用の趣味のワールド用です。各館の文章・画像の権利はそれぞれの館にあります。
