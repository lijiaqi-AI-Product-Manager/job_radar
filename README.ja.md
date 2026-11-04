![job_radar](docs/assets/hero-en.svg)

[![Release](https://img.shields.io/badge/release-v2.3.1-58bfa5)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/v2.3.1) [![PyPI](https://img.shields.io/pypi/v/jobsearchradar?color=58bfa5)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · 日本語

**いつもの AI アシスタントに、仕事探しのスキルを。**

希望する都市・職種・条件を伝えると、中国の新卒採用・インターン・中途採用・採用カレンダーを調べ、募集要件と出典リンクを整理します。スキルやローカルツールを使える Agent モードでの利用を推奨します。

## クイックスタート

次の依頼を対応するアシスタントに送ってください。初回は案内に従って接続し、その後は会話で検索できます。

```text
このリポジトリの jobradar 求職検索スキルを接続してください。まず現在の
環境が対応しているか確認し、接続後に上海のプロダクト関連インターンを探
して、募集要件・出典リンク・明記された締切を示してください。不明な情報
は分けてください。
https://github.com/lijiaqi-AI-Product-Manager/job_radar
```

必要なら Release の jobradar-skill.zip をスキル画面から取り込んでください。取り込み後も検索ツールとデータの準備が必要です。通常のウェブチャットだけでローカルツールが使えるとは限りません。

[Platform routes / 平台接入](docs/PLATFORMS.md) · [Skill download](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest)

<details>
<summary><strong>手動セットアップ（設定する人・アシスタント向け）</strong></summary>

PyPI のパッケージ名は `jobsearchradar`、コマンドは `jobradar` です。Python 3.11+ が必要です。Windows / macOS / Linux に対応。

```bash
pip install --upgrade "jobsearchradar==2.3.1"
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

</details>

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

2026-11-04 · [Methodology / 统计口径](docs/COVERAGE.md)

| 指標 | 値 |
| :--- | ---: |
| 有効なデータソース | 2,230 |
| 設定済み企業 | 2,199 |
| アダプター | 27 |
| 固定対象企業の設定カバレッジ | 944 / 1,655 · 57.04% |

2026-11-04 UTC の検証済みスナップショットには 331,440 件の求人レコード（募集中 306,924 件）があり、募集中レコードの JD 本文カバー率は 97.5% です。設定の有無は当日の募集状況を示しません。集約サイトの採用告知は複数職種を含む場合があります。

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## MCP 接続

```bash
pip install --upgrade "jobsearchradar[mcp]==2.3.1"
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

<!-- project-growth:start -->

## プロジェクトの推移

Star 履歴は毎日自動更新されます。更新日は UTC、Star の日付は GitHub の集計基準です。 PyPI の日別ダウンロードリクエスト数も表示します。

<a href="https://github.com/lijiaqi-AI-Product-Manager/job_radar/stargazers">
<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-dark.svg">
  <img src="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-light.svg" width="960" alt="job_radar · GitHub Star 履歴">
</picture>
</a>

<a href="https://pypistats.org/packages/jobsearchradar">
<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-dark.svg">
  <img src="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-light.svg" width="960" alt="job_radar · 日別ダウンロードリクエスト数">
</picture>
</a>

リクエストには重複や自動アクセスが含まれ、ユニークユーザー数やアクティブユーザー数ではありません。

[データソースと指標の定義](https://github.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/blob/main/docs/growth.md)

<!-- project-growth:end -->
