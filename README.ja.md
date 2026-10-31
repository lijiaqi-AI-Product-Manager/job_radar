![job_radar](docs/assets/hero-en.svg)

[![Release](https://img.shields.io/badge/release-v2.0.0-58bfa5)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/v2.0.0) [![PyPI](https://img.shields.io/pypi/v/jobsearchradar?color=58bfa5)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · 日本語

**中国の新卒・インターン・中途採用情報を、ローカルのデータベースへ。**

公開されている求人と採用カレンダーを SQLite に整理。企業・都市・卒業年度で絞り込み、求人本文を検索し、元の応募ページを確認できます。CLI と MCP に対応し、検索用の API キーやサーバーは不要です。

## クイックスタート

PyPI のパッケージ名は `jobsearchradar`、コマンドは `jobradar` です。Python 3.11+ が必要です。Windows / macOS / Linux に対応。

```bash
pip install jobsearchradar
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

![job_radar demo](docs/assets/demo-en.gif)

<sub>図は実際の検索結果の抜粋です。アニメーションの時間は検索速度を示しません。最新の状態と締切は元の求人ページで確認してください。</sub>

## 検索例

```bash
jobradar search --text "PyTorch 大模型" --type campus --limit 3 --table
jobradar search --city 上海 --category 算法 --type intern --dedupe --table
jobradar calendar --group 阿里巴巴 --grad-year 2027 --table
jobradar diff --days 7 --types open --table
jobradar doctor
```

`--table` → table · default → JSON · `JOBRADAR_HOME` → data directory

## データとカバレッジ

2026-10-31 · [Methodology / 统计口径](docs/COVERAGE.md)

| 指標 | 値 |
| :--- | ---: |
| 有効なデータソース | 2,242 |
| 設定済み企業 | 2,201 |
| アダプター | 27 |
| 固定対象企業の設定カバレッジ | 931 / 1,655 · 56.25% |

2026-10-29 の検証済みスナップショットには 294,483 件の求人レコード（募集中 276,008 件）があり、募集中レコードの JD 本文カバー率は 97.3% です。設定の有無は当日の募集状況を示しません。集約サイトの採用告知は複数職種を含む場合があります。

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## MCP 接続

```bash
pip install "jobsearchradar[mcp]"
jobradar update
```

```json
{
  "mcpServers": {
    "jobradar": {
      "command": "jobradar-mcp"
    }
  }
}
```

stdio サービスとして `jobradar-mcp` を登録します。検索・詳細・変更履歴・比較・傾向・カレンダーなど 9 ツールを提供。独自のデータ保存先はサービスの `env` に `JOBRADAR_HOME` を指定します。

## ドキュメントと貢献

公開ソースの追加、日付の修正、再現可能な不具合報告、翻訳を歓迎します。役に立ったら Star や共有で応援してください。

[English guide](README.en.md) · [文档 / Docs](docs/README.md) · [FAQ](docs/FAQ.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

コードは MIT ライセンスです。第三者の求人本文の権利は元の権利者に帰属し、コードのライセンスが追加の利用権を与えるものではありません。
