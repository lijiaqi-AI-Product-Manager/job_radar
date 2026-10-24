# job_radar · 中国の校招／インターン／中途採用のオープン求人データセット

[简体中文](README.md) | [English](README.en.md) | 日本語 | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.1.0-blue)](CHANGELOG.md)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**毎日自動更新される中国の求人データセット**。各社の公式採用ページを毎日クロールし、すぐに検索できる SQLite として公開します。
CLI・MCP・Skill を同梱しているので、AI エージェントは API キーもサーバーもなしで
「どこが・何を・いつまで・どこに出願するか」を答えられます。

![demo](docs/assets/demo-en.gif)

> **データ（2026-10-24 時点）**：**279 ソース** · **約 88,600 件の募集中求人** ·
> **JD 全文 99.8%** · 目標 500 社のうち **494 社**がカレンダーまたは求人データを保有（求人レベルは **161 社**）。

## 特長

- ✅ 各社**公式**採用ページの求人と JD 原文（第三者の集約サイトは使いません）
- ✅ 毎日フルクロール、履歴保持（新規・クローズ・変更を追跡）
- ✅ 採用カレンダー：卒業年度・プログラム種別・職種方向・応募期間・都市・応募 URL・出典
- ❌ 全社ではありません（500 社中 161 社のみ求人レベル）
- ❌ 応募代行・リファラル・面接情報・給与は扱いません。CAPTCHA／ログイン／署名の回避も行いません

## クイックスタート

```bash
# PyPI 未公開（公開手順は docs/PUBLISHING.md）。今はソースからインストール：
pip install "jobradar[mcp] @ git+https://github.com/lijiaqimun-coder/job_radar"

jobradar update     # 約 20 MB + 35 MB。既に最新ならダウンロードなし
jobradar search --company 腾讯 --city 深圳 --category 算法 --table
```

中国国内では Gitee ミラーを使用（失敗時は GitHub に自動フォールバック）：

```bash
jobradar update --mirror gitee
```

## できること

```bash
jobradar search --text "PyTorch 大模型" --type campus   # タイトル＋JD の全文検索
jobradar search --company 喜茶 --exclude-store          # 店舗系の求人を除外（約 8,000 件）
jobradar search --company 星巴克中国 --dedupe           # 重複 requisition を集約（variants 付き）
jobradar diff --days 7 --by category --company 腾讯     # 会社単位の新着を職種別に
jobradar calendar --group 阿里巴巴 --type 秋招 --table   # 読みやすいカレンダー表示
```

求人が無いがカレンダーには載っている会社（字節跳動・華為・小米など）では、`search` は
「データなし」ではなく `jobradar calendar --group <社名> --table` を案内します。

## AI エージェント連携

- **Claude Code**：`skill/jobradar/` を `~/.claude/skills/jobradar/` にコピー
- **MCP クライアント**（Claude Desktop / Cursor など）：コマンドは `jobradar-mcp`（stdio、9 ツール）。
  データ置き場が既定（`~/.cache/jobradar`）でない場合は MCP 設定の `env` に `JOBRADAR_HOME` を渡してください
- ライブラリとしても利用可：`from jobradar.core import queries`

## 既知の制限

| 項目 | 現状 |
|---|---|
| カレンダー網羅 | 494/500（残り 6 社は robots／ログイン／DNS で不可） |
| 求人レベル | 161/500（残りは独自サイトか暗号化プラットフォーム） |
| 大手 | 阿里・騰訊・美団・網易などは求人あり。字節跳動・京東・華為はカレンダーのみ |
| 応募期間 | 1,372 件中 8 件（0.6%）だけが開始・締切の両方を記載 |
| 重複 | 9.2% が同一会社・同一タイトル・同一都市（`--dedupe` で集約） |
| 履歴 | 2026-10-19 以降。トレンド分析はまだ 5〜7 日分 |

詳細は [CLAUDE.md](CLAUDE.md)、社内プロセス文書は [docs/internal/](docs/internal/)。

## ライセンスとコンプライアンス

コードは MIT。求人内容の権利は各発表者に帰属し、本リポジトリはインデックスのみ提供します。
公開ページのみを 1 リクエスト/秒以下で取得し、CAPTCHA・ログイン・署名の回避は行いません
（[COMPLIANCE.md](COMPLIANCE.md)）。
