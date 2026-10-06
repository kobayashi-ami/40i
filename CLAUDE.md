# CLAUDE.md — 1260（仮称）

SP-1200 のドラム × MPC60II のサンプル、という組み合わせでしか出ない音の成分を、段ごとに分解してソフトウェアで組み直す。WAV を投げると、機械を通した音色にして書き出して返す**オフライン処理ツール**。プラグインではない。

オーナーはビートメイカー／アーティスト（Mac・FL Studio）。仕様の核は実機での手順そのもの：
SP-1200 でサンプリング（キックは low、スネアは Hi を EQ で強く持ち上げ、少し歪ませて入れる）→ TUNE を -1／-2 → 上ネタは MPC60II の質感。

---

## 承認ゲート（最優先ルール）

フェーズの境界ではオーナーの承認を待つ。**ゲートを飛ばして先へ進まない。**

| Phase | 内容 | ゲート |
|---|---|---|
| 0 | 画面モック PNG（＋iPhone 試聴画面）（`design/render_mockups.py` → `design/mockups/`） | **PNG を提示して停止** → 承認後 `design.md` を書く → **再び停止** |
| 1 | 骨組み：Postgres/Redis、Alembic、FastAPI health、ダミーワーカー、SSE、`tailscale serve` 経由の iPhone 表示 | 冒頭で Postgres/Redis を **brew services か Docker(OrbStack) か一度だけ確認** |
| 2 | DSP エンジン：ステージ関数＋単体テスト＋CLI | 終了時に報告 |
| 3 | UI 実装：`design.md` に厳密に従う。無い要素は足さない（足すなら先に design.md を更新して承認） | 終了時に報告 |
| 4 | 較正：参照音源との差分比較で HYPOTHESIS を詰める | 終了時に報告 |

各フェーズの終わりに「何をしたか／何が未確定か／次に何をするか」を短く報告する。

**現在地：Phase 1（骨組み）。Phase 0 は完了（モックと design.md を 2026-10-06 に承認）。Postgres/Redis は OrbStack（Docker Compose）で動かす。**

---

## 不変ルール

- **VERIFIED / HYPOTHESIS を区別する。** 一次資料で確定できない値（非線形12-bitの変換曲線、SP入力AAフィルタ、SSM2044段の実効カットオフ、MPCのプリエンファシス等）は仮説パラメータとして実装し、複数候補を切替可能にする。断定的なハードコード禁止。コード・docs・UI のすべてでラベルを付ける。詳細は `docs/research.md`。
- **ステージは純関数**（numpy 配列 in / out）。ステージ単位で ON/OFF とパラメータを持つ。
- **決定論的**：同じ入力＋同じパラメータ → 同じ出力ハッシュ。乱数を使うなら seed をパラメータに含める。
- **drop-sample の TUNE は補間しない。** 出力レート固定、位相アキュムレータを比率表の値で進め、小数部切り捨て。比率表は `equal_tempered`（2^(n/12)）と `measured`（実機測定値、HYP）を切替可能にする。ここを「改善」しないこと——この粗さが目的の成分。
- 書き出しレート変換でゼロ次ホールドの成分を消さない（変換方式を選択可能にする）。
- **状態の正本は PostgreSQL。** Redis はキュー・ライブ進捗・pub/sub・ハートビート。Redis が消えても Postgres から復元できること。ワーカーが死んでもジョブを宙に浮かせない（failed か再キュー）。
- アプリは `127.0.0.1` にのみバインド。公開は `tailscale serve`（tailnet 内のみ）。**`tailscale funnel` は使わない。** CLI 書式は実行前に `tailscale serve --help` で確認。
- 対象マシン：MacBook Pro M4 Pro（Apple Silicon）。目安：1秒のドラム1本の処理が1秒未満。

## スコープ外

リアルタイム AU/VST 化、シーケンサ、SSM2044 の回路レベル完全再現、インターネット公開、ユーザー管理。

---

## 信号チェーン（要約）

**A. ドラム経路（SP-1200）**：ロール → プリEQ（ロール別、kick 60–100 Hz / snare 5–8 kHz を +9〜+12 dB）→ ドライブ（tanh＋入力ゲイン、次段12-bitの壁と相互作用）→ 取り込み速度（45回転相当など）→ ADC（AA[HYP] → 26041.67 Hz → 12-bit リニア、ディザ無し、フルスケールでハードクリップ）→ TUNE（drop-sample）→ 音量エンベロープ（8-bit、任意）→ DAC（ZOH、再構成フィルタ無し／弱め）→ アナログ段（ch1–2 ラダーLPF＋レベル追従、ch3–6 固定LPF、ch7–8 スルー）→ 書き出しレートへ。

**B. サンプル経路（MPC60II）**：入力ゲイン → プリエンファシス[HYP] → 40 kHz（帯域 ~18 kHz）→ 16-bit → 非線形12-bit エンコード／デコード（候補を最低3つ、全部 HYP）→ チューン（-12〜+6、補間 なし／線形）→ デエンファシス → 16-bit DAC 相当 → 書き出しレートへ。

**出力**：WAV 24-bit / 48 kHz（既定）、ネイティブレートも可。ファイル名 `元名__chain-preset__tune-2.wav`。スペクトログラム PNG とパラメータ JSON を添付。

## システム構成（Phase 1 以降）

Browser/iPhone →（tailnet HTTPS: `tailscale serve`）→ FastAPI（REST＋SSE、ビルド済みフロントを同一オリジン配信）→ PostgreSQL（正本）／Redis（Streams キュー・進捗ハッシュ・pub/sub・TTL ハートビート）→ ワーカー（API とは別プロセス、複数台前提）。音声ファイルは Mac 上のデータディレクトリ、メタデータと sha256 は Postgres。

**iPhone で試聴できること**（オーナー要望）：モバイルに LISTEN タブ（`design/mockups/05b_mobile_listen.png`）。処理前後を A/B で瞬時に切替（再生位置は保持）、同じサンプルの別 TUNE／別プリセットの書き出しを並べて聴き比べる。実装上の注意：API は音声を HTTP Range リクエスト対応で配信する（iOS Safari の `<audio>` は Range 必須）。A/B の切替は Web Audio で両方をデコードして同期再生する（`<audio>` の付け替えだと位置がずれる）。iOS では再生開始にユーザー操作が必要。配信は書き出した WAV そのままで、試聴のために再エンコードしない（ZOH の成分を残すため）。マイグレーションは Alembic。起動は `make dev` / `make up`（launchd plist）。

## リポジトリ構成

```
CLAUDE.md                 このファイル
design.md                 UI の規則（トークン・部品・状態・画面）。Phase 3 はこれに厳密に従う
README.md
pyproject.toml            uv 管理（dev / design グループ）
Makefile                  setup / infra / migrate / dev / up / serve / test
compose.yaml              Postgres 16 + Redis 7（OrbStack、127.0.0.1 のみ）
alembic.ini, migrations/  Alembic（0001 initial schema）
core/                     settings, db, models（正本スキーマ）, bus（Redis）, jobs（ライフサイクル・reaper・reconcile・snapshot）
api/                      FastAPI（REST + SSE）, smoke.html（Phase 1 の確認ページ。Phase 3 で本 UI に置き換え）
worker/                   python -m worker（Phase 1 はダミーステージ）
scripts/                  dev.sh, launchd.sh, tailscale_serve.sh
deploy/launchd/           LaunchAgent テンプレート
tests/                    結合テスト（実 Postgres/Redis、API とワーカーを子プロセスで起動）
design/
  render_mockups.py       Phase 0：手続き的モック生成（Pillow + numpy）
  fonts/                  OFL フォント（Saira Stencil One / Barlow Condensed / IBM Plex Mono / Share Tech Mono）
  mockups/                生成 PNG（1x をコミット、@2x は --hires で生成・gitignore）
docs/
  research.md             音響的事実と未確定事項（VERIFIED / HYPOTHESIS）
  runbook.md              Mac での起動・常駐・tailnet 公開・障害時の振る舞い
# Phase 2 以降に追加予定
engine/   web/
```

## コマンド

```
make setup && make infra && make migrate
make dev                  # API + ワーカー（前面）。http://127.0.0.1:8260/
make test                 # 結合テスト（make infra が前提）
make up / make down       # launchd 常駐
make serve / unserve      # tailscale serve（tailnet 内のみ、funnel は使わない）
make lint
make mockups              # design/mockups/*.png を再生成
```

## デザイン指針（詳細は design.md）

世界観：90年代後半〜2000年代初頭ヒップホップ、インダストリアル、サイバーパンク、欧州ディストピア。重厚、筐体感、チェーン。温度は「青い炎」——高密度・低温・高強度。黒鉄／ガンメタルの地に、**冷たい青を唯一のアクセント**として低彩度で。発光は抑制的。ヘアライン金属、ビス、刻印風ラベル、スライダー、7セグ、チェーンリンクの区切り。実在機のロゴ・パネル配置・配色を写さない。禁止：角丸の親しげなカード、紫グラデ、絵文字、過剰な説明テキスト。数値は等幅、見出しはコンデンス／ステンシル、日本語ラベルは最小限。
