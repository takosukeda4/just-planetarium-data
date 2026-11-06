# just-planetarium-data

VRChat ワールド「Just プラネタリウム」が読む、外のデータを作る道具と出来たデータです（ワールドのファイルは入っていません）。

- `scripts/build_rain.py` — 今の降水を地点ごとに作る道具（2026-11-06 にやめました。いまは動かさず、ワールドも読みません）。
- `scripts/build_info.py` — 全国のプラネタリウム・美術館などの公式フィードの題・日付・リンク（`info.json` / `info.txt`。受付が終わった物・過ぎた物は出さない）と、件ごとの元のページの QR を並べた `qr.png`と、Wikimedia Commons の CC 画像の枠（`slots/slot_00.jpg` ...）。画像の作者・ライセンスは `info.json` の slots に書いています。チラシなどの画像は転載しません。
- `.github/workflows/update.yml` — 毎日 1 回（03:20 JST）情報パネルのデータを更新して `gh-pages` に置きます。

非商用の趣味のワールド用です。各館の文章・画像の権利はそれぞれの館にあります。
