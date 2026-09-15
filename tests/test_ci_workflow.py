"""CI workflow 自身的守门测试（不是设计文档要求的，但守着 P1-4-5 的真实故障）。

2026-09-15 的真实事故：给 backend job 加 `INCIDENT_DATABASE_URL` 时漏了引号，
值以冒号结尾 → YAML `ScannerError: mapping values are not allowed here` →
整个 workflow 解析失败。GitHub 的表现是**一个 0 job 的失败运行**，工作流名退化成
`.github/workflows/ci.yml`（这个信号不明显，很容易被当成"测试挂了"）。

所以这里用已经在 `requirements-lock.txt` 里的 PyYAML 把 workflow 解析一遍，并断言
两个 job 的关键步骤仍在——CI 是唯一能证明"干净环境可跑"的地方，不能让它的定义文件
在无人察觉的情况下失效。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_workflow_file_is_valid_yaml_with_its_name(workflow):
    assert workflow["name"] == "CI"


def test_workflow_runs_on_push_to_main_and_manual_dispatch(workflow):
    # YAML 把裸 `on` 解析成布尔 True，所以两种写法都要能取到。
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) >= {"push", "pull_request", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]


def test_both_jobs_still_exist(workflow):
    assert set(workflow["jobs"]) == {"backend", "frontend"}
    for job in workflow["jobs"].values():
        assert job["runs-on"] == "ubuntu-latest"


def test_backend_job_provides_the_database_url(workflow):
    """没有这一条，`import app.main` 在无 .env 的检出里直接抛 RuntimeError。"""

    env = workflow["jobs"]["backend"]["env"]
    assert env["INCIDENT_DATABASE_URL"].startswith("sqlite+pysqlite")


def step_runs(job: dict) -> list[str]:
    return [step.get("run", "") for step in job["steps"] if "run" in step]


def test_backend_job_still_runs_the_four_verification_commands(workflow):
    commands = " \n".join(step_runs(workflow["jobs"]["backend"]))

    assert "ruff check ." in commands
    assert "pytest tests -q" in commands
    assert "compileall" in commands
    assert "alembic heads" in commands


def test_frontend_job_still_installs_from_the_lockfile_and_builds(workflow):
    frontend = workflow["jobs"]["frontend"]
    commands = " \n".join(step_runs(frontend))

    assert "npm ci" in commands
    assert "npm run build" in commands
    assert frontend["defaults"]["run"]["working-directory"] == "web"
