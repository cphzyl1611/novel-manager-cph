import json
import uuid
from pathlib import Path

from novel_manager.gui.command_runner import ensure_gui_safe_command
from novel_manager.gui.safe_actions import is_safe_rename_item, is_safe_update_item, write_filtered_rename_plan, write_filtered_update_report


def make_tmp_root() -> Path:
    root = Path(".tmp") / "gui_safe_actions_tests" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_command_runner_safe_action_whitelist():
    assert ensure_gui_safe_command("apply-renames", ["--report", "r.json", "--confirm", "--yes-i-understand"])[0] is False
    assert ensure_gui_safe_command("apply-renames", ["--report", "r.json", "--confirm", "--yes-i-understand"], safe_action="apply_selected_renames")[0] is True
    assert ensure_gui_safe_command("apply-updates", ["--report", "r.json", "--confirm", "--yes-i-understand"], safe_action="apply_recommended_updates")[0] is True
    assert ensure_gui_safe_command("move-to-trash", ["--book-id", "1", "--confirm", "--yes-i-understand"], safe_action="move_single_book_to_trash")[0] is True
    assert ensure_gui_safe_command("auto-tag", ["--apply"])[0] is False
    assert ensure_gui_safe_command("auto-tag", ["--apply"], safe_action="apply_auto_tags")[0] is True
    assert ensure_gui_safe_command("refresh-metadata", ["--apply"], safe_action="refresh_metadata")[0] is True
    assert ensure_gui_safe_command("stage-duplicates", ["--confirm"], safe_action="apply_selected_renames")[0] is False


def test_filtered_rename_report_contains_only_safe_selected_items():
    repo = make_tmp_root()
    (repo / "library").mkdir()
    (repo / "reports" / "rename").mkdir(parents=True)
    source = repo / "library" / "old.txt"
    target = repo / "library" / "new.txt"
    source.write_text("x", encoding="utf-8")
    report = repo / "reports" / "rename" / "rename_plan_test.json"
    safe = {"action": "rename_recommended", "current_path": str(source), "target_path_preview": str(target), "risk_flags": []}
    manual = {"action": "manual_review", "current_path": str(source), "target_path_preview": str(repo / "library" / "manual.txt"), "risk_flags": []}
    conflict = {"action": "rename_recommended", "current_path": str(source), "target_path_preview": str(repo / "library" / "conflict.txt"), "risk_flags": ["target_name_conflict"]}
    report.write_text(json.dumps({"suggestions": [safe, manual, conflict]}, ensure_ascii=False), encoding="utf-8")
    path = write_filtered_rename_plan(repo, report, [safe, manual, conflict])
    data = json.loads(path.read_text(encoding="utf-8"))
    original = json.loads(report.read_text(encoding="utf-8"))
    assert len(data["suggestions"]) == 1
    assert data["suggestions"][0]["target_path_preview"] == str(target)
    assert len(original["suggestions"]) == 3


def test_rename_safety_rules_skip_risky_items():
    root = make_tmp_root()
    current = root / "old.txt"
    target = root / "new.txt"
    current.write_text("x", encoding="utf-8")
    assert is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []})
    assert not is_safe_rename_item({"action": "manual_review", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []})
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": ["target_name_conflict"]})
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": ["author_suspicious"]})


def test_filtered_update_report_contains_only_safe_recommended_items():
    repo = make_tmp_root()
    (repo / "reports" / "update").mkdir(parents=True)
    report = repo / "reports" / "update" / "update_report_test.json"
    safe = {"recommendation": "replace_recommended", "same_work_score": 0.95, "coverage_score": 0.9, "quality_delta": 0, "risk_flags": []}
    reject = {"recommendation": "reject", "same_work_score": 0.95, "coverage_score": 0.9, "quality_delta": 0, "risk_flags": []}
    review = {"recommendation": "review", "same_work_score": 0.95, "coverage_score": 0.9, "quality_delta": 0, "risk_flags": []}
    risky = {"recommendation": "replace_recommended", "same_work_score": 0.95, "coverage_score": 0.9, "quality_delta": 0, "risk_flags": ["author_conflict"]}
    report.write_text(json.dumps({"candidates": [safe, reject, review, risky]}, ensure_ascii=False), encoding="utf-8")
    path = write_filtered_update_report(repo, report, [safe, reject, review, risky])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["recommendation"] == "replace_recommended"
    assert is_safe_update_item(safe)
    assert not is_safe_update_item(reject)
    assert not is_safe_update_item(review)
    assert not is_safe_update_item(risky)


def test_gui_does_not_offer_permanent_delete_text_or_delete_calls():
    gui_source = "\n".join(path.read_text(encoding="utf-8") for path in Path("novel_manager/gui").rglob("*.py"))
    assert 'QPushButton("永久删除' not in gui_source
    assert "QPushButton('永久删除" not in gui_source
    assert "os.remove" not in gui_source
    assert ".unlink(" not in gui_source
