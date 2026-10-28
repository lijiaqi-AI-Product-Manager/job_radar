# job_radar · 중국 캠퍼스·인턴·경력 채용 공개 데이터셋

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | 한국어 | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Русский](README.ru.md)

[![version](https://img.shields.io/badge/version-1.5.0-blue)](CHANGELOG.md)
[![pypi](https://img.shields.io/pypi/v/jobsearchradar)](https://pypi.org/project/jobsearchradar/)
[![tests](https://img.shields.io/badge/tests-504%20passed-brightgreen)](tests/)
[![data](https://img.shields.io/badge/data-daily-success)](https://github.com/lijiaqimun-coder/job_radar/releases/tag/data-latest)
[![license](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**매일 자동 갱신되는 중국 채용 데이터셋**. 각 기업의 공식 채용 페이지를 매일 수집해
바로 조회할 수 있는 SQLite 로 배포합니다. CLI·MCP·Skill 을 함께 제공하므로
AI 에이전트가 API 키나 서버 없이 "누가, 무엇을, 언제까지, 어디로 지원"을 답할 수 있습니다.

![demo](docs/assets/demo-en.gif)

> **커버리지(2026-10-28)**: **1,490개 소스**(베이센 1,168 / 다이이 108 / Feishu ATSX 138 / Tupu360 32 / Workday 25 등) ·
> **1,461개 기업** · **23개 어댑터**. 목표 **1,655개**(20개 업종 1,117 + 31개 성급 행정구 808) 중 **564개(33%)** 확보.
> 공고 수와 JD 커버리지는 매일 크롤링 후 갱신됩니다(최신 Release 기준).

## 특징

- ✅ 각 기업 **공식** 채용 페이지의 공고와 JD 원문(제3자 집계 사이트 제외)
- ✅ 매일 전체 재수집, 이력 보존(신규·마감·변경 추적)
- ✅ 채용 캘린더: 졸업 연도, 프로그램 유형, 직무 방향, 지원 기간, 도시, 지원 URL, 출처
- ❌ 1,014개 중 264개만 공고 단위 데이터 제공
- ❌ 지원 대행·추천·면접 후기·연봉은 다루지 않으며, 캡차/로그인/서명 우회도 하지 않습니다

## 빠른 시작

```bash
pip install "jobsearchradar[mcp]"

jobradar update     # 약 20 MB + 35 MB, 최신이면 다운로드 없음
jobradar search --company 腾讯 --city 深圳 --category 算法 --table
```

중국 내 네트워크에서는 Gitee 미러 사용(실패 시 GitHub 로 자동 전환):

```bash
jobradar update --mirror gitee
```

## 할 수 있는 질문

```bash
jobradar search --text "PyTorch 大模型" --type campus   # 제목+JD 전문 검색
jobradar search --company 喜茶 --exclude-store          # 매장/리테일 공고 제외(약 8천 건)
jobradar search --company 星巴克中国 --dedupe           # 중복 requisition 통합(variants 제공)
jobradar diff --days 7 --by category --company 腾讯     # 기업 단위 신규 공고를 직무별로
jobradar calendar --group 阿里巴巴 --type 秋招 --table   # 읽기 쉬운 캘린더 출력
```

공고는 없지만 캘린더에는 있는 기업(바이트댄스·화웨이·샤오미 등)의 경우 `search` 는
"데이터 없음" 대신 `jobradar calendar --group <기업> --table` 을 안내합니다.

## AI 에이전트 연동

- **Claude Code**: `skill/jobradar/` 를 `~/.claude/skills/jobradar/` 에 복사
- **MCP 클라이언트**(Claude Desktop, Cursor 등): 명령은 `jobradar-mcp`(stdio, 9개 도구).
  데이터 경로가 기본값(`~/.cache/jobradar`)이 아니면 MCP 설정 `env` 에 `JOBRADAR_HOME` 전달
- 라이브러리로도 사용: `from jobradar.core import queries`

## 알려진 한계

| 항목 | 현황 |
|---|---|
| 목표 커버리지 | **564/1,655(33%)** (나머지 12개는 robots/로그인/암호화로 불가) |
| 소스 | **1,490개 소스 / 1,461개 기업** (베이센 1,140, 다이이 96, Feishu ATSX 138, Tupu360 32, 구 베이센 28, Workday 25, 구 다이이 12, 자체 사이트 19) |
| 성별 커버리지 | 광둥 18/49(37%), 저장 13/44(30%), 장쑤 9/34(26%), 쓰촨 9/30(30%), 산둥 7/26(27%). 전체 표는 `scripts/coverage_report.py` |
| 대형 테크 | 알리바바·텐센트·메이투안·넷이즈·바이두·징둥·바이트댄스·vivo·체리·CICC·BOE·하이센스·PICC 는 공고 있음. 화웨이는 캘린더만(WAF 403) |
| 캘린더 항목 | 2026-10-26 전체 크롤 기준 74.9% 가 11개 항목 중 7개 이상 보유 |
| 지원 기간 | 가장 약한 항목(2026-10-26 기준 완전한 기간은 0.6%). `apply_end` 는 공고의 최빈 날짜 |
| 중복 | 2026-10-26 기준 9.2% 가 동일 기업·제목·도시(`--dedupe` 로 통합) |
| 이력 | 2026-10-19 부터 누적, 추세 분석은 아직 5~7일 |

내부 프로세스 문서는 [docs/internal/](docs/internal/) 에 있습니다.

## 라이선스·컴플라이언스

코드는 MIT. 채용 내용의 권리는 각 게시자에게 있으며 본 저장소는 색인만 제공합니다.
공개 페이지만 초당 1회 이하로 접근하고 캡차·로그인·서명 우회는 하지 않습니다
([COMPLIANCE.md](COMPLIANCE.md)).
