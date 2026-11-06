# 外のデータを Udon で読む設計（R19 雨・R27 情報パネル）— A4、2026-11-06

実装は B6。ここは作り方と決まり。データを作る道具は `data\scripts\`、出来た見本は `data\sample\`（git には入れない）。

## 1. 置き場と URL

- GitHub Pages（`*.github.io`）。VRChat の公式ページで確かめた許可ドメイン（2026-11-06）:
  - String Loading（<https://creators.vrchat.com/worlds/udon/string-loading/>）: `*.disbridge.com`、`*.github.io`、`gist.githubusercontent.com`、`pastebin.com`、`*.vrcdn.cloud`
  - Image Loading（<https://creators.vrchat.com/worlds/udon/image-loading/>）: 上の `*.github.io` ほか（`i.imgur.com`、`pbs.twimg.com`、`i.ytimg.com`、`assets.vrchat.com` など）。**Pages は両方に入っている**
- リポジトリ `just-planetarium-data`（公開）。Pages は `gh-pages` ブランチのルート。**GitHub にログインできず、まだ作っていない**（`progress.md`、`publish_steps.md`）。作ったら下の `<USER>` を本当の名前に。
- URL（焼き込む物）。**ファイル名は変えない**（Udon が決め打ちで読む）:

| 物 | URL | 更新 | 大きさ |
|---|---|---|---|
| 雨（Udon 用） | `https://<USER>.github.io/just-planetarium-data/rain.txt` | 30 分ごと | 約 2.9 KB |
| 雨（人用・確かめ用） | `.../rain.json` | 同じ | 約 11 KB |
| 情報パネルの文字（Udon 用） | `.../info.txt` | 毎日 03:20 JST | 約 7 KB（30 件） |
| 情報パネルの QR（Udon 用、B14a） | `.../qr.png` | 毎日 03:20 JST | 1024×1024 の白黒 PNG |
| 同（人用、作者・ライセンスつき） | `.../info.json` | 同じ | 約 4.6 KB |
| 画像の枠 | `.../slots/slot_00.jpg` 〜 `slot_05.jpg`（6 枚。足すなら `slots` と `sources.json` の数を増やす） | 毎日 | 768×432、1 枚 15〜80 KB |

## 2. VRChat の決まり（公式、2026-11-06 に確認）

- String Loading: **5 秒に 1 本**（超えるとキューに入り順番は無作為）。1 本 100 MB まで。キュー 1000。**許可ドメイン以外は、ユーザーが「Allow Untrusted URLs」をオンにしないと読めない**（既定オフ）。API は `VRCStringDownloader.LoadUrl(VRCUrl, IUdonEventReceiver)`、イベント `OnStringLoadSuccess(IVRCStringDownload)`／`OnStringLoadError`。`Result`（UTF-8 の文字）、`Error`・`ErrorCode`。リダイレクトのことは書いていない。
- Image Loading: **5 秒に 1 枚（シーン全体）**。最大 **2048×2048**（超えるとエラー）。**リダイレクト不可**（画像のファイルを直接指す URL だけ）。入出力のバッファ 32 MB。`VRCImageDownloader` を `new` で作り**参照を持ち続ける**（捨てると全部消える）。`DownloadImage(VRCUrl, Material, IUdonEventReceiver, TextureInfo)`。TextureInfo の既定は GenerateMipMaps オフ・Trilinear・Repeat・AnisoLevel 9。イベント `OnImageLoadSuccess`／`OnImageLoadError`（エラーは InvalidURL・AccessDenied・InvalidImage・DownloadError）。**使わない画像は `Dispose`**（メモリが多く、放っておくとクラッシュの元）。
- **VRCUrl は実行時に文字から作れない**（シーンに焼き込むか、ユーザーが入力欄に打つ）。だから URL は全部インスペクターの `VRCUrl` に入れる（固定の名前が必要な理由）。U# の `[SerializeField] VRCUrl rainUrl;`。インスペクターに入れた VRCUrl は `Udon` が文字列にして持つので、`SetPositionAndRotation` のように後から変える物ではない。
- 時刻の更新が 30 分でも、読む側が 5 秒の枠を守れば足りる（下）。

## 3. 呼ぶ間隔（String 5 秒枠・Image 5 秒枠は別々に数える）

世界に入ってすぐは YamaPlayer・目覚まし・PlayerData なども同じ枠を使うので、**自分の読み込みは入って 20 秒後から**、1 回に 1 本ずつ、`SendCustomEventDelayedSeconds` で 6 秒空ける。

| いつ | 何を | 回数 |
|---|---|---|
| 「今の空」を選んだとき（まだ一度も読んでいない／最後から 20 分たった） | `rain.txt` 1 本 | ふつう 1〜2 回 |
| 「今の空」のまま入っている間 | 20 分ごとに `rain.txt` | 1 時間 3 回 |
| 情報パネルを初めて開いたとき | `info.txt` → 6 秒おきに `slot_00..05.jpg` | 1 回 + 6 枚（約 40 秒で出そろう。出た枠から順に表示） |
| パネルを閉じたとき | 何も読まない。画像は 10 分見られなかったら Dispose | |
| 失敗 | 60 秒 → 120 秒 → 300 秒（そこで止め、次はユーザーが開き直したとき） | |

全員が同時に読むが、GitHub Pages は静的なので負荷は問題ない。**人数分をネットワークで同期しない**（各自が読む。雨の有無は同じデータなのでほぼ同じ）。雨の音の同期は不要。

## 4. 雨（R19）— `rain.txt`

6 行、改行は `\n`。

```
1  観測時刻（UTC、Open-Meteo の 15 分ごと）  例 2026-11-05T22:00
2  レベルの文字列（1 地点 1 文字）            例 000000100200...   0 なし 1 小雨 2 雨 3 強い雨 4 雪 5 雷雨
3  降水量 mm/h（カンマ区切り）
4  雲量 %（カンマ区切り）
5  緯度（カンマ区切り）
6  経度（カンマ区切り）
```

- 地点は 137 個: ワールドの `Map/cities.csv`（92 都市。順番は `PlanetSky.cityName` と同じ）＋ 日本の県庁所在地など 45 個（`extra_japan.csv`）。**照合は番号でなく 5・6 行目の緯度経度で**（ワールドの都市の並びが変わっても壊れない）。
- Udon: 「今の空」の `placeLat/placeLon`（地図で自由に選べる）から**一番近い地点**を線形に探す（137 回の距離比較、場所が変わったときだけ）。球面の距離は `dlat² + (dlon·cos lat)²` で足りる。**一番近い地点が 600 km より遠いなら、雨なし**（海の上・南極などで嘘の雨を降らせない）。北極・南極点（|lat| > 85）は雨なし。月・火星・カリスト（`site != 0`）は読まない。
- 1 文字: `levels[i]` を `int` に（`'0'` を引く）。強さは、小雨は音量 0.35・雨 0.6・強い雨 0.9、雪は雨音でなく静かな風（鳴らさない）、雷雨は強い雨の音（雷鳴は入れない）。雨の種類（A1 の複数の音）はユーザーが選んだ物を、「自動」のときだけレベルで選ぶ（小雨→葉に落ちる小雨、雨→しとしと、強い雨→遠くの強い雨）。細部は B6。
- **「実際の今の雨」を使うのは、時刻が実時刻のとき**だけ（日時を動かしたら自動の雨は止める）。`observed` から 2 時間以上古いデータ（GitHub が止まったとき）は「雨なし」。
- 読めなかったとき: 前に読めた値を 2 時間まで使い続ける。一度も読めていなければ雨なし。画面の小さな字「雨のデータにつながっていません」をタブレットの雨のページにだけ（空には出さない）。
- 雨が降り始める・止むときは音を 4 秒でフェード（急に鳴らさない）。

## 5. 情報パネル（R27）— `info.txt`、画像の枠

`info.txt` は `#qr` の 1 行と 2 つの節。タブ区切り（`\t`）、行は `\n`。（2026-11-06 B14a で `#qr` と item の 5〜9 列目を足した。前の PlanetInfoPanel は `#items` より前の行と 5 列目からを読み飛ばすので壊れない）

```
#qr<TAB>qr.png<TAB>画像の一辺 px(1024)<TAB>列(6)<TAB>行(6)<TAB>マスの一辺 px(170)<TAB>QR のある件の数
#items
会場<TAB>題<TAB>日付(YYYY-MM-DD)<TAB>元のページの URL<TAB>QR のマス(0〜35、-1=なし)<TAB>種類(event/until/news)<TAB>終わりの日<TAB>〆切<TAB>発表日
...（最大 36 行。ふだんは 30 行くらい。前の PlanetInfoPanel は 24 行まで読む）
#slots
slots/slot_00.jpg<TAB>写真の題<TAB>作者<TAB>ライセンス<TAB>クレジット
...（6 行。取れなかった枠は無地の画像で、題・作者・ライセンスが空）
```

- 日付（3 列目）: イベントは**次の開催日**（今日より前の日は使わない）、「〜まで」の開催中の物は終わりの日、知らせは発表日。種類（6 列目）が `until` なら「〜11/30」、`event` なら「11/22」、`news` なら「11/4 のお知らせ」のように出し分けられる。
- 出す物・並べ方（R65）: `build_info.py` の頭と `sources.json` の `rules`。イベント（次の開催日が近い順）→ 知らせ（30 日以内、新しい順）。受付終了・〆切が過ぎた・開催日が過ぎた・中止・開催報告などは出さない（`info_filter.log` に理由）。
- QR（R67）: `qr.png`（1024×1024、白黒の PNG。2048 だと Quest で RGBA32 16 MB になるので 1024 = 4 MB にした）。マス i が件 i（左上から右へ、6 列ずつ下の行へ）。誤り訂正 M 以上（入るなら Q に上げる）、周りの白 4 マス。1 マスに 1 つの QR を、整数倍の大きさで真ん中に置く（1 モジュール 2 px 以上）。マスごとに、そのまま・70 % に縮めて・ぼかして JPEG にして、の 3 つで読み直し、読めない物は QR を付けない（-1）。Udon は `RawImage.uvRect = new Rect(col*cell/size, 1-(row+1)*cell/size, cell/size, cell/size)`（col = i % 列、row = i / 列）。WordPress の館は短い URL（`?p=番号`、元のページへ飛ぶ）を QR に入れる（`info.json` の `qr_url`）。読み込むと RGBA32 で約 4 MB。、パネルを開いたときだけ読み、写真の枠と同じく 10 分見られなければ Dispose。画像の枠（5 秒に 1 枚）を 1 枚ぶん使う。焼き込む `VRCUrl` は `.../qr.png` を 1 つ足す。
- PC で URL を選んでコピーできる入力欄に出すのは、4 列目の URL（Udon の側）。
- 表示: 「題」と「会場」と日付をパネルに。URL は VRChat では開けないので、入力欄（PC でコピー）と QR（携帯で読む）で渡す。写真の下に**必ず「作者・ライセンス」と「Wikimedia Commons」**を小さく（CC BY・BY-SA の条件）。題が空の無地の枠は出さない。
- 文字: 公式サイトの題は難しい漢字が混ざる。パネルの TMP の字（`PlanetLabels SDF`）に無い字は四角になる。**B6 は、表示前に字が足りるか確かめる**（足りない字が多い題は飛ばす）か、日本語全体の字を持つフォントにする（Quest のメモリが増える。相談）。
- 画像: **768×432 の JPEG**。ダウンロードした画像は圧縮されない RGBA32 で載るので、1 枚 約 1.3 MB、6 枚で約 8 MB（Quest でもよい大きさ）。2048 の上限には余裕。ミップマップはオフ（既定）、`FilterMode.Bilinear`。`TextureInfo` を使って `AnisoLevel` は既定のまま。
- 読み込みの順は 1 枚ずつ 6 秒おき。**枠の URL は固定**なので、中身の入れ替わりは毎日 1 回（03:20 JST）。世界に長くいる人は、パネルを開くたびに 10 分以上たっていたら読み直す。
- 画像を `Dispose` する: パネルを閉じて 10 分、またはワールドを出るとき。`VRCImageDownloader` は 1 つだけ作って使い回し、メンバー変数で持つ。

### 読めなかったとき（共通）

| 失敗 | 画面 |
|---|---|
| `AccessDenied`（許可ドメインでない）・`InvalidURL` | 開発の間違い。ログに出す。ユーザーには「読み込めません」 |
| `DownloadError`・タイムアウト | 再試行（上の表）。その間は前の値 |
| 404（Pages が止まった・まだ作っていない） | 同上。パネルに「いまは情報を取れません」と、前に読めた分があればそれを |
| `InvalidImage` | その枠だけ無地 |
| 5 秒の枠を超えた（`RateLimited` は動画。文字・画像は順番待ちになるだけ） | 自分で 6 秒おきに呼ぶので起きない |

## 6. 更新（GitHub Actions）

`data\.github\workflows\update.yml`:

- 30 分ごと（`7,37 * * * *`）: `build_rain.py` → `gh-pages` の `rain.*` を上書き。毎日 18:20 UTC（= 03:20 JST）: `build_info.py` も。手動（`workflow_dispatch`、`rain`/`info`/`both`）。
- `gh-pages` は**いつも 1 コミット**（`--amend` して強制 push。履歴が増えない）。ほかのファイルは残す（雨の更新で画像が消えない）。
- GitHub の定時実行は混むと数分〜十数分遅れる。30 分より短くしても保証されない。**公開リポジトリは 60 日間リポジトリに動きがないと定時実行が自動で止まる**（GitHub の決まり）。`main` に何か 1 コミットすると再開する。→ `publish_steps.md`。
- 失敗しても前のデータが残るので、世界側は「古い」と判断（観測から 2 時間）して雨を止める。

## 7. 守ること（権利・礼儀）

- 雨: Open-Meteo.com（<https://open-meteo.com/en/terms>）。データは **CC BY 4.0**、無料の API は**非商用だけ**（1 日 1 万回未満・1 時間 5000 回・1 分 600 回まで）。このワールドは非商用の趣味。**30 分ごと 3 回の呼び出し × 48 = 1 日 約 150 回**で、限りの 1.5 %。**クレジット「Weather data by Open-Meteo.com」**を、`rain.json` の `credit` と、アセットリスト（`assetlist_rows.csv`）と、タブレットの雨のページの小さな字に。ワールドで広告・課金をしたら使えない（その場合は有料プラン）。Actions の実行元 IP は共有なので、制限に当たるなら遅れて再試行（スクリプトは失敗しても前のデータを残す）。
- 情報パネルの文字: 題・日付・元のリンクだけ。**各館の公式フィード（RSS/Atom）**で、**robots.txt を見て、1 日 1 回、名乗る User-Agent**。本文・フィードの画像は載せない。館ごとの規約は `sources.md`（確かめられなかった所は「未確認」）。
- 画像: **Wikimedia Commons の、スクリプトが許可リストのライセンス（CC0・PD・CC BY・CC BY-SA）と確かめた物だけ**。NonFree は外す。作者・ライセンス・ページを `info.json` に残す。**チラシ・ポスターの画像は載せない**（どの館も転載を許していないか、確かめられなかった。2026-11-06 B14a で足した館も、規約が読めた所はどれも「無断の複製・転載はお断り」。チラシは QR から開く館のページで見てもらう）。
- 個人情報は入れない（`git` のメールは noreply）。
