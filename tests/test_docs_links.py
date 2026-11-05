import importlib.util
import json
from pathlib import Path


def test_doc_checks_ignore_temporary_installs_but_find_real_broken_links(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "check_docs_links", Path(__file__).resolve().parents[1] / "scripts/check_docs_links.py",
    )
    docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docs)
    monkeypatch.setattr(docs, "ROOT", tmp_path)
    guide = tmp_path / "docs/guide.md"
    guide.parent.mkdir()
    guide.write_text("[real broken link](missing.md)", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("[guide](docs/guide.md)", encoding="utf-8")
    dependency = tmp_path / ".tmp/wheel-smoke/Lib/site-packages/package/NOTICE.md"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("[dependency license](missing-license.txt)", encoding="utf-8")

    files = docs.md_files()
    assert set(files) == {readme, guide}
    assert docs.broken_links(files) == [f"{guide.relative_to(tmp_path)} -> missing.md"]


def test_homepage_checks_detect_shadowing_and_invalid_svg(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "check_docs_links", Path(__file__).resolve().parents[1] / "scripts/check_docs_links.py",
    )
    docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docs)
    monkeypatch.setattr(docs, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text("# Public homepage", encoding="utf-8")
    hidden = tmp_path / ".github/README.md"
    hidden.parent.mkdir()
    hidden.write_text("# Automation", encoding="utf-8")
    asset = tmp_path / "docs/assets/hero-en.svg"
    asset.parent.mkdir(parents=True)
    asset.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>jobs & calendars</text></svg>',
                     encoding="utf-8")
    errors = docs.homepage_problems()
    assert any(".github/README.md" in error for error in errors)
    assert any("hero-en.svg" in error for error in errors)
    hidden.rename(hidden.with_name("AUTOMATION.md"))
    asset.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>jobs &amp; calendars</text></svg>',
                     encoding="utf-8")
    assert docs.homepage_problems() == []


def test_current_install_guides_reject_old_pypi_or_unpinned_source(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "check_docs_links", Path(__file__).resolve().parents[1] / "scripts/check_docs_links.py")
    docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docs)
    monkeypatch.setattr(docs, "ROOT", tmp_path)
    config = tmp_path / "docs/install-target.json"
    config.parent.mkdir()
    target = {"distribution": "jobsearchradar", "repository": "owner/repo", "revision": "a" * 40}
    config.write_text(json.dumps(target), encoding="utf-8")
    guide = tmp_path / "README.md"
    guide.write_text('pip install "jobsearchradar[mcp]"', encoding="utf-8")
    assert docs.installation_problems([guide])
    guide.write_text('pip install "jobsearchradar[mcp] @ https://github.com/owner/repo/archive/main.zip"',
                     encoding="utf-8")
    assert docs.installation_problems([guide])
    url = f"https://github.com/owner/repo/archive/{target['revision']}.zip"
    guide.write_text(f'pip install --upgrade "jobsearchradar[mcp] @ {url}"', encoding="utf-8")
    assert docs.installation_problems([guide]) == []
    target.update(version="2.0.1", revision="v2.0.1")
    config.write_text(json.dumps(target), encoding="utf-8")
    guide.write_text('pip install --upgrade "jobsearchradar[mcp]==2.0.1"', encoding="utf-8")
    assert docs.installation_problems([guide]) == []
    guide.write_text(guide.read_text(encoding="utf-8") + '\npip install jobsearchradar', encoding="utf-8")
    assert docs.installation_problems([guide])


def test_homepage_media_rejects_relative_urls_that_break_on_package_index(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "check_docs_links", Path(__file__).resolve().parents[1] / "scripts/check_docs_links.py",
    )
    docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docs)
    monkeypatch.setattr(docs, "ROOT", tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(
        '![Cover](docs/assets/hero.svg)\n<img src="docs/assets/demo.gif" alt="demo">',
        encoding="utf-8",
    )
    errors = docs.homepage_problems()
    assert any("hero.svg" in error for error in errors)
    assert any("demo.gif" in error for error in errors)
    readme.write_text(
        '![Cover](https://raw.githubusercontent.com/owner/repo/main/docs/assets/hero.svg)\n'
        '<img src="https://raw.githubusercontent.com/owner/repo/main/docs/assets/demo.gif" alt="demo">',
        encoding="utf-8",
    )
    assert docs.homepage_problems() == []


def test_release_badges_and_install_target_follow_current_code_version(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_docs_links", Path(__file__).resolve().parents[1] / "scripts/check_docs_links.py")
    docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(docs)
    monkeypatch.setattr(docs, "ROOT", tmp_path)
    init = tmp_path / "src/jobradar/__init__.py"
    init.parent.mkdir(parents=True)
    init.write_text('__version__ = "2.3.2"', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('name = "jobsearchradar"\ndynamic = ["version"]\n[tool.hatch.version]\npath = "src/jobradar/__init__.py"\n', encoding="utf-8")
    target = tmp_path / "docs/install-target.json"
    target.parent.mkdir()
    target.write_text(json.dumps({"version": "2.3.2"}), encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("https://img.shields.io/badge/release-v2.3.1-58bfa5", encoding="utf-8")
    assert docs.versions()
    readme.write_text("https://img.shields.io/badge/release-v2.3.2-58bfa5", encoding="utf-8")
    target.write_text(json.dumps({"version": "2.3.1"}), encoding="utf-8")
    assert docs.versions()
    target.write_text(json.dumps({"version": "2.3.2"}), encoding="utf-8")
    english = tmp_path / "README.en.md"
    english.write_text("https://img.shields.io/badge/release-v2.3.1-58bfa5", encoding="utf-8")
    assert docs.versions()
    english.write_text(readme.read_text(encoding="utf-8"), encoding="utf-8")
    assert docs.versions() == []
