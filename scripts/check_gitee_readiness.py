"""匿名检查镜像公开入口；入口缺失时明确跳过同步，服务故障仍返回失败。"""

import json
import os
import re
import sys
from pathlib import Path

import httpx

from jobradar import __version__

MESSAGES = {
    "credentials_not_configured":"尚未配置镜像发布凭据",
    "repository_not_public_or_missing":"公开仓库入口返回404，仓库可能不存在或未公开",
    "repository_private":"仓库不是公开仓库",
    "public_repository_reachable":"公开仓库入口可读取",
}


def validate_repo(repo):
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("非法镜像仓库地址")
    if any(part in {".", ".."} for part in repo.split("/")):
        raise ValueError("非法镜像仓库地址")
    return repo


def probe_public_repository(repo, client):
    repo = validate_repo(repo)
    response = client.get(f"https://gitee.com/api/v5/repos/{repo}",
                          headers={"User-Agent":f"jobradar/{__version__}"})
    if response.status_code == 404:
        return {"repo":repo, "ready":False, "state":"repository_not_public_or_missing"}
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or type(payload.get("private")) is not bool:
        raise ValueError("镜像仓库元数据无效")
    private = payload["private"]
    return {"repo":repo, "ready":not private,
            "state":"repository_private" if private else "public_repository_reachable"}


def report(result):
    print(json.dumps(result, ensure_ascii=False))
    message = MESSAGES[result["state"]]
    if not result["ready"]:
        print(f"::warning::Gitee镜像未执行同步：{message}。此状态不计为同步成功。")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"ready={str(result['ready']).lower()}\nstate={result['state']}\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        text = ("仅确认公开入口可读取；快照同步及匿名SHA256验证仍需后续作业完成。"
                if result["ready"] else "**未执行同步**；国内镜像仍未恢复，不计为镜像发布成功。")
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(f"## Gitee入口检查\n\n仓库：`{result['repo']}`。{message}。\n\n{text}\n")


def main():
    try:
        repo = validate_repo(os.environ.get("GITEE_REPO", "qgauss/job_radar"))
        if not os.environ.get("GITEE_TOKEN", "").strip():
            result = {"repo":repo, "ready":False, "state":"credentials_not_configured"}
        else:
            # 不把发布凭据发送给公开入口探测；上传使用独立作业。
            with httpx.Client(timeout=httpx.Timeout(12, connect=8), follow_redirects=True) as client:
                result = probe_public_repository(repo, client)
        report(result)
    except (httpx.HTTPError, ValueError, OSError) as error:
        print(f"Gitee入口检测失败（{type(error).__name__}）；本轮未执行同步，请检查网络或仓库配置", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
