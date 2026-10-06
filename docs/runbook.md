# Runbook — Mac（M4 Pro）で動かす

## 0. 用意するもの

| もの | 入れ方 |
|---|---|
| OrbStack | https://orbstack.dev からインストールし、設定の **Start at login** をオン |
| uv | `brew install uv` |
| Tailscale | Mac App Store 版か公式サイト版。設定の **CLI integration** で `tailscale` コマンドを入れる |
| iPhone の Tailscale | 同じ tailnet にログイン |

## 1. はじめて動かす

```sh
make setup        # 依存関係のインストールと .env の作成
make infra        # OrbStack で Postgres と Redis を起動（127.0.0.1 だけで待ち受け）
make migrate      # テーブルを作る
make dev          # API とワーカー 2 台を前面で起動。Ctrl-C で全部止まる
```

ブラウザで http://127.0.0.1:8260/ を開くと、Phase 1 の確認ページ（`/smoke`）が出ます。**DUMMY JOB** を押すと 10 段のダミーステージが流れ、進捗バーが SSE で動きます。

## 2. iPhone から見る（tailnet の中だけに公開）

```sh
make serve        # tailscale serve --help で書式を確かめてから、実行するコマンドを表示して y/N を聞く
```

`tailscale serve status` に出る `https://<Mac の名前>.<tailnet>.ts.net/` を iPhone の Safari で開きます。

- tailnet の外からは届きません。`tailscale funnel` は使いません（スクリプトは funnel がオンなら警告します）。
- アプリ自体は `127.0.0.1:8260` だけで待ち受けます。公開の入口は `tailscale serve` だけです。
- tailnet のユーザーから開くと、`Tailscale-User-Login` ヘッダがジョブの `created_by` に記録されます（タグ付きの端末からはヘッダが付かず、空になります）。
- やめるときは `make unserve`。

## 3. 常駐させる

```sh
make up           # LaunchAgent：API 1 本とワーカー WORKERS 本（既定 2）。落ちても 10 秒以内に再起動、ログイン時に自動起動
make status
make down         # 外す
```

ログは `~/Library/Logs/1260/` にあります。Postgres と Redis は compose の `restart: unless-stopped` で、OrbStack の起動と一緒に戻ります。

## 4. 壊れたときの振る舞い（テスト済み：`make test`）

| 起きたこと | どうなるか |
|---|---|
| ワーカーが落ちた（kill -9、クラッシュ） | ハートビート（5 秒ごと、15 秒で期限切れ）が途切れたワーカーのジョブを、reaper が再キューする。`MAX_ATTEMPTS`（3）回目で failed。running のまま宙に浮くことはない |
| ワーカーを止めた（SIGTERM、`make down`） | 次のステージの境目で手を止め、ジョブをキューに返す。試行回数は増えない |
| Redis が消えた・再起動した | 画面の状態は Postgres から組み立て直す。キューに居たジョブは reconcile が Postgres からストリームに積み直す |
| ブラウザが途中から開いた・別の端末で開いた | SSE は接続時に Postgres（＋Redis の途中経過）のスナップショットを送ってから差分を流すので、全員が同じ状態を見る |

reaper と reconcile は、API とすべてのワーカーの中で回っています（行ロックの `SKIP LOCKED` で重複しない）。

## 5. 将来：別のマシンでワーカーを動かす（今は有効にしない）

ワーカーを別の Mac で動かす日が来たら、Postgres と Redis を **tailnet の IP（100.64.0.0/10）からだけ** 受け付けるようにします。

1. `compose.yaml` の公開ポートを、この Mac の tailnet IP（`tailscale ip -4`）に向ける。`127.0.0.1` の行はそのまま残す。
   ```yaml
   ports:
     - "127.0.0.1:55432:5432"
     - "100.x.y.z:55432:5432"
   ```
2. Postgres：`pg_hba.conf` に `host 1260 1260 100.64.0.0/10 scram-sha-256` を足し、強いパスワードに変える（コンテナの環境変数 `POSTGRES_PASSWORD`、`.env` の `DATABASE_URL`）。
3. Redis：`--requirepass`（または ACL ユーザー）を設定し、`REDIS_URL` に認証情報を入れる。`protected-mode` はオンのまま。
4. Tailscale の ACL で、ワーカー用の Mac（タグ `tag:1260-worker` など）から、この Mac の 55432 と 56379 だけを許可する。
5. ワーカー用の Mac では、`.env` の `DATABASE_URL` と `REDIS_URL` を `100.x.y.z` に向けて、`uv run python -m worker` を動かす。

インターネットには一切開けません。
