from pathlib import Path
from unittest.mock import patch
import uuid

from novel_manager.report_index import find_latest_report, generate_report_index, list_reports, open_report


def make_repo(tmp_name="reports_repo") -> Path:
    repo = Path(".tmp") / tmp_name / uuid.uuid4().hex
    for relative in [
        "reports/duplicate",
        "reports/quality",
        "reports/errors",
        "reports/summary",
        "reports/update",
        "reports/group",
    ]:
        (repo / relative).mkdir(parents=True, exist_ok=True)
    return repo


def write_report(path: Path, text="x") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_list_reports_lists_formats_and_filters():
    repo = make_repo("reports_list")
    write_report(repo / "reports" / "duplicate" / "duplicate_report_a.html")
    write_report(repo / "reports" / "duplicate" / "duplicate_report_a.json")
    write_report(repo / "reports" / "summary" / "summary_report_a.md")
    reports = list_reports(repo, report_type="all", report_format="all")
    duplicate = list_reports(repo, report_type="duplicate", report_format="html")
    assert {item["suffix"] for item in reports} >= {"html", "json", "md"}
    assert len(duplicate) == 1
    assert duplicate[0]["report_type"] == "duplicate"


def test_list_reports_latest_only():
    repo = make_repo("reports_latest_only")
    old = write_report(repo / "reports" / "quality" / "quality_report_old.html")
    new = write_report(repo / "reports" / "quality" / "quality_report_new.html")
    old.touch()
    new.touch()
    reports = list_reports(repo, report_type="quality", latest_only=True)
    assert len(reports) == 1
    assert reports[0]["file_name"] == "quality_report_new.html"


def test_open_latest_prefers_summary_md_then_duplicate_html():
    repo = make_repo("reports_open")
    duplicate = write_report(repo / "reports" / "duplicate" / "duplicate_report_a.html")
    assert find_latest_report(repo, report_type="all") == duplicate
    summary = write_report(repo / "reports" / "summary" / "summary_report_a.md")
    assert find_latest_report(repo, report_type="all") == summary


def test_open_report_uses_mocked_system_call():
    path = Path("report.md")
    with patch("platform.system", return_value="Darwin"), patch("subprocess.run") as run:
        ok, message = open_report(path)
    assert ok is True
    assert message == str(path)
    run.assert_called_once()


def test_generate_report_index_outputs_html_and_md_with_empty_dirs():
    repo = make_repo("reports_index")
    write_report(repo / "reports" / "duplicate" / "duplicate_report_a.html")
    write_report(repo / "reports" / "quality" / "quality_report_a.json")
    write_report(repo / "reports" / "errors" / "scan_error_report_a.html")
    write_report(repo / "reports" / "summary" / "summary_report_a.md")
    html_path, md_path = generate_report_index(repo)
    html = html_path.read_text(encoding="utf-8")
    md = md_path.read_text(encoding="utf-8")
    assert html_path.exists()
    assert md_path.exists()
    for word in ["duplicate", "quality", "errors", "summary"]:
        assert word in html
        assert word in md
    assert "暂无" in html
    assert "暂无" in md
