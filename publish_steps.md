# 公開の手順（雨と情報パネルのデータ）— 2026-11-06

状況: ユーザーが「つくっていいよ」と言ってくれたが、**Chrome の GitHub がログインしていなかった**（`github.com/new` がサインインに飛んだ）。ほかにログインの手段（`gh`・SSH 鍵・保存した資格情報）が無いので、**リポジトリは作っていない**。手元の `data\` は動く所まで出来ていて、`git` のコミットも 1 つ入っている（`data\.git`、メールは noreply）。

## ユーザーがすること（これだけ）

1. Chrome で <https://github.com/login> にログインしておく（アカウント名を教えてください。URL に入る）。ログインしたら「ログインした」と言ってくれれば、続きは Claude がやる。
2. （自分でやるなら下の 3〜7）

## Claude がやる続き（ログイン後）

3. <https://github.com/new>: 名前 `just-planetarium-data`、Public、README は作らない。
4. `data\` の中身を push（`git remote add origin https://github.com/<USER>/just-planetarium-data.git`、`git push -u origin main`。Git Credential Manager が入っている。初回はブラウザで承認）。入る物: `scripts\`、`.github\workflows\update.yml`、`README.md`、`.gitignore`。入らない物: `sample\`（`.gitignore`）、ワールドのファイル、購入素材。
5. Settings → Actions → General → **Workflow permissions = Read and write permissions**。
6. Actions → `update-data` → Run workflow → `both`。終わると `gh-pages` ブランチができる。
7. Settings → Pages → Source = **Deploy from a branch**、Branch = `gh-pages` / `/ (root)`。数分で <https://USER.github.io/just-planetarium-data/rain.txt> が開く。
8. 確かめる: `rain.txt` が 6 行、`info.txt` に `#items` `#slots`、`slots/slot_00.jpg` が開く。30 分後に `rain.txt` の 1 行目が進む。
9. URL を `design.md`・`progress.md` に書く。B6 がシーンに焼き込む（`VRCUrl` 7 個: rain.txt、info.txt、slot_00〜05）。

## 何を置くか・URL の形

`https://<USER>.github.io/just-planetarium-data/` の下に `rain.txt` `rain.json` `info.txt` `info.json` `slots/slot_00.jpg`〜（`design.md` 1 節の表）。

## 気をつけること

- **許可ドメイン**は `*.github.io`（String・Image どちらも）。独自ドメインは許可外。
- 公開リポジトリは**60 日 `main` に動きが無いと定時実行が止まる**。止まったら Actions の画面で「Enable workflow」。気づくために、世界側で「観測が 2 時間以上古い」ときタブレットに小さな字を出す（`design.md` 4 節）。
- 定時実行は遅れることがある（数分〜十数分）。
- 情報パネルを公開する前に、`sources.md` の「未確認」の館の規約を見て OK を出すか、気になる館は `sources.json` から外す。
- Open-Meteo は非商用。ワールドで広告・課金・有料の特典をするなら有料プランが要る。
- ワールドをアップロードするときは、シーンに焼き込む URL に誤字が無いか、実機（ClientSim では `VRCStringDownloader` が動くが許可ドメインの確認は実機）。
- リポジトリを消す・非公開にするとワールドの雨と情報パネルが止まる。
