![job_radar](docs/assets/hero-en.svg)

[![PyPI](https://img.shields.io/pypi/v/jobsearchradar?color=58bfa5)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · 한국어

**중국 신입·인턴·경력 채용 정보를 내 컴퓨터의 데이터베이스로.**

공개 채용 공고와 채용 일정을 SQLite로 정리합니다. 기업·도시·졸업 연도로 필터링하고, 공고 본문을 검색한 뒤 원본 지원 페이지로 이동하세요. CLI와 MCP를 지원하며 검색용 API 키나 서버 배포가 필요하지 않습니다.

## 빠른 시작

PyPI 패키지 이름은 `jobsearchradar`, 설치 후 명령은 `jobradar`입니다. Python 3.11+가 필요하며 Windows / macOS / Linux를 지원합니다.

```bash
pip install jobsearchradar
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

![job_radar demo](docs/assets/demo-en.gif)

<sub>애니메이션은 실제 조회 결과의 일부입니다. 재생 시간은 검색 속도를 나타내지 않습니다. 최신 상태와 마감일은 원본 채용 페이지에서 확인하세요.</sub>

## 검색 예시

```bash
jobradar search --text "PyTorch 大模型" --type campus --limit 3 --table
jobradar search --city 上海 --category 算法 --type intern --dedupe --table
jobradar calendar --group 阿里巴巴 --grad-year 2027 --table
jobradar diff --days 7 --types open --table
jobradar doctor
```

`--table` → table · default → JSON · `JOBRADAR_HOME` → data directory

## 데이터와 커버리지

2026-10-31 · [Methodology / 统计口径](docs/COVERAGE.md)

| 지표 | 값 |
| :--- | ---: |
| 활성 소스 | 2,242 |
| 설정된 기업 | 2,201 |
| 어댑터 | 27 |
| 고정 대상 기업의 설정 커버리지 | 931 / 1,655 · 56.25% |

2026-10-29 검증 스냅샷에는 총 294,483건, 모집 중 276,008건의 기록이 있습니다. 모집 중 기록의 JD 본문 커버리지는 97.3%입니다. 소스 설정이 있다고 오늘 채용 중이라는 뜻은 아닙니다. 집계 사이트의 채용 안내 하나에 여러 직무가 포함될 수 있습니다.

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## MCP 연결

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

stdio 서비스로 `jobradar-mcp`를 등록하세요. 검색, 상세, 변경, 비교, 추이, 일정 등 9개 도구를 제공합니다. 데이터 경로를 바꿨다면 서비스의 `env`에 `JOBRADAR_HOME`을 전달하세요.

## 문서와 기여

공개 소스 추가, 날짜 수정, 재현 가능한 오류 보고, 번역을 환영합니다. 도움이 되었다면 Star와 공유로 다른 구직자에게 알려주세요.

[English guide](README.en.md) · [文档 / Docs](docs/README.md) · [FAQ](docs/FAQ.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

코드는 MIT 라이선스입니다. 제3자 채용 콘텐츠의 권리는 원 권리자에게 있으며, 코드 라이선스가 해당 콘텐츠에 추가 권한을 부여하지는 않습니다.
