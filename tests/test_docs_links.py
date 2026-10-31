import importlib.util
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
