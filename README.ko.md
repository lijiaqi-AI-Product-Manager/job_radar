![job_radar](docs/assets/hero-en.svg)

[![Release](https://img.shields.io/github/v/release/lijiaqi-AI-Product-Manager/job_radar?color=58bfa5)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest) [![PyPI](https://img.shields.io/pypi/v/jobsearchradar?color=58bfa5)](https://pypi.org/project/jobsearchradar/) [![CI](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/lijiaqi-AI-Product-Manager/job_radar/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/python-3.11%2B-7bb7ff)](pyproject.toml) [![MIT](https://img.shields.io/badge/license-MIT-7bb7ff)](LICENSE)

[简体中文](README.md) · [English](README.en.md) · 한국어

**평소 쓰는 AI 도우미에 구직 검색 스킬을 더하세요.**

원하는 도시, 직무와 조건을 말하면 중국 신입·인턴·경력 채용과 채용 일정을 조회하고 요구 사항과 원문 링크를 정리합니다. 스킬이나 로컬 도구를 사용할 수 있는 Agent 모드를 권장합니다.

## 빠른 시작

호환되는 도우미에게 아래 요청을 보내세요. 처음에는 플랫폼 안내에 따라 연결하고, 이후에는 대화로 검색합니다.

```text
이 저장소의 jobradar 구직 검색 스킬을 연결해 주세요. 현재 환경이 지원
하는지 먼저 확인하고, 연결 후 상하이의 제품 관련 인턴을 찾아 요구 사항
, 원문 링크와 명시된 마감일을 알려 주세요. 알 수 없는 정보는 따로 표시
해 주세요.
https://github.com/lijiaqi-AI-Product-Manager/job_radar
```

파일이 필요하면 Release의 jobradar-skill.zip을 스킬 화면에서 가져오세요. 가져온 뒤에도 검색 도구와 데이터 준비가 필요합니다. 일반 웹 채팅이 로컬 도구를 실행할 수 있다고 가정하지 마세요.

[Platform routes / 平台接入](docs/PLATFORMS.md) · [Skill download](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/latest)

<details>
<summary><strong>수동 설정 (설정 담당자 또는 도우미용)</strong></summary>

PyPI 패키지 이름은 `jobsearchradar`, 설치 후 명령은 `jobradar`입니다. Python 3.11+가 필요하며 Windows / macOS / Linux를 지원합니다.

```bash
pip install --upgrade "jobsearchradar"
jobradar update
jobradar search --company 复星医药 --type campus --grad-year 2027 --table
```

</details>

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

2026-11-05 · [Methodology / 统计口径](docs/COVERAGE.md)

| 지표 | 값 |
| :--- | ---: |
| 활성 소스 | 2,230 |
| 설정된 기업 | 2,199 |
| 어댑터 | 27 |
| 고정 대상 기업의 설정 커버리지 | 944 / 1,655 · 57.04% |

2026-11-05 UTC 검증 스냅샷에는 총 346,273건, 모집 중 320,353건의 기록이 있습니다. 모집 중 기록의 JD 본문 커버리지는 97.6%입니다. 소스 설정이 있다고 오늘 채용 중이라는 뜻은 아닙니다. 집계 사이트의 채용 안내 하나에 여러 직무가 포함될 수 있습니다.

[Latest data release](https://github.com/lijiaqi-AI-Product-Manager/job_radar/releases/tag/data-latest) · `jobradar stats`

## MCP 연결

```bash
pip install --upgrade "jobsearchradar[mcp]"
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

<!-- project-growth:start -->

## 프로젝트 성장

Star 기록은 매일 갱신됩니다. 갱신 날짜는 UTC이며 Star 날짜는 GitHub의 집계 기준을 따릅니다. PyPI의 일별 다운로드 요청 수도 표시합니다.

<a href="https://github.com/lijiaqi-AI-Product-Manager/job_radar/stargazers">
<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-dark.svg">
  <img src="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/stars-light.svg" width="960" alt="job_radar · GitHub Star 기록">
</picture>
</a>

<a href="https://pypistats.org/packages/jobsearchradar">
<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-dark.svg">
  <img src="https://raw.githubusercontent.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/main/assets/growth/job_radar/downloads-light.svg" width="960" alt="job_radar · 일별 다운로드 요청">
</picture>
</a>

요청에는 반복 및 자동화된 접근이 포함되며 순 사용자 수나 활성 사용자 수를 의미하지 않습니다.

[데이터 출처 및 지표 정의](https://github.com/lijiaqi-AI-Product-Manager/lijiaqi-AI-Product-Manager/blob/main/docs/growth.md)

<!-- project-growth:end -->
