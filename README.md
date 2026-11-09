# just-planetarium-data

VRChat ワールド「Just プラネタリウム」が読む、外のデータを作る道具と出来たデータです（ワールドのファイルは入っていません）。

- `scripts/build_rain.py` — 今の降水を地点ごとに作る道具（2026-11-06 にやめました。いまは動かさず、ワールドも読みません）。
- `scripts/build_info.py` — 全国のプラネタリウム・美術館などの公式フィードの題・日付・リンク（`info.json` / `info.txt`。受付が終わった物・過ぎた物は出さない）と、件ごとの元のページの QR を並べた `qr.png`と、Wikimedia Commons の CC 画像の枠（`slots/slot_00.jpg` ...）。画像の作者・ライセンスは `info.json` の slots に書いています。チラシなどの画像は転載しません。
- `scripts/build_board.py` — 情報ボード v2（2026-11-09）: 全国のプラネタリウム・科学館・美術館・博物館・水族館・動物園・植物園の公式フィード（`scripts/feeds_auto.json`）と、BODIK の自治体のイベント一覧（CC BY）から、これからの催し・会期中の展示・30 日以内のお知らせを最大 300 件（`board.txt`・`board.json`）。分野（5 つ）と地域（9 つ）で偏らないように選びます。件の画像（`cards/c_NNN.jpg`、長い辺 1024 px 以下）は、フィードの中の画像 → ページの og:image → その館の Wikimedia Commons の CC 写真の順で、出典（館名・URL、Commons は作者とライセンス）を付けます。館から言われたら `scripts/board_config.json` の `blocklist` に足すと外れます。
- `scripts/build_venues.py` — 館の一覧 `scripts/venues.json`（Wikidata、CC0。1 回だけ流す）。
- `scripts/find_feeds.py` — 各館の公式サイトのトップを 1 回読んでフィードを探し、`scripts/feeds_auto.json` を作る（1 回だけ流す。robots.txt に従い、同じホストへは 1 秒以上あけます）。
- 取り方の決まり（どの道具も）: `User-Agent: just-planetarium-data/1.0`、robots.txt に従う、同じホストへは 1 秒以上あける、ログイン不要の公開の物だけ。使わない所（規約で止めている所・まとめサイト・SNS）は `scripts/board_config.json` の `banned_hosts`。
- `.github/workflows/update.yml` — 毎日 1 回（03:20 JST）情報パネルと情報ボードのデータを更新して `gh-pages` に置きます。

非商用の趣味のワールド用です。各館の文章・画像の権利はそれぞれの館にあります。
