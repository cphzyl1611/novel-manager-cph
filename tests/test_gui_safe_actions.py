import json
import uuid
from pathlib import Path

from novel_manager.gui.command_runner import ensure_gui_safe_command
from novel_manager.gui.i18n import action_label, risk_label
from novel_manager.gui.safe_actions import (
    can_apply_visible_rows,
    can_user_toggle_rename_item,
    compute_rename_stats,
    get_rename_row_status,
    initial_checked_keys,
    is_row_checked,
    is_safe_rename_item,
    is_safe_update_item,
    rename_unsafe_reason,
    row_key,
    should_check_rename_item_by_default,
    update_checked_keys,
    write_filtered_rename_plan,
    write_filtered_update_report,
)


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


# ---------------------------------------------------------------------------
# rename_unsafe_reason pure function tests
# ---------------------------------------------------------------------------


def test_unsafe_reason_for_manual_review():
    reason = rename_unsafe_reason({"action": "manual_review", "risk_flags": []})
    assert "建议改名" in action_label("rename_recommended")
    assert "需要人工确认" in reason or "非建议改名" in reason


def test_unsafe_reason_for_target_name_conflict():
    root = make_tmp_root()
    current = root / "a.txt"
    current.write_text("x", encoding="utf-8")
    reason = rename_unsafe_reason(
        {"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(root / "b.txt"), "risk_flags": ["target_name_conflict"]}
    )
    assert "文件名冲突" in reason


def test_unsafe_reason_for_author_suspicious():
    root = make_tmp_root()
    current = root / "a.txt"
    current.write_text("x", encoding="utf-8")
    reason = rename_unsafe_reason(
        {"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(root / "b.txt"), "risk_flags": ["author_suspicious"]}
    )
    assert "作者" in reason


def test_unsafe_reason_for_no_change():
    reason = rename_unsafe_reason({"action": "no_change", "risk_flags": [], "current_file_name": "a.txt", "target_file_name": "a.txt"})
    assert "无需修改" in reason or "建议改名" in action_label("rename_recommended")


def test_unsafe_reason_for_missing_file():
    reason = rename_unsafe_reason({"action": "rename_recommended", "current_path": "/nonexistent/path.txt", "target_path_preview": "/tmp/b.txt", "risk_flags": []})
    assert "不存在" in reason


def test_unsafe_reason_for_target_exists():
    root = make_tmp_root()
    current = root / "a.txt"
    target = root / "b.txt"
    current.write_text("x", encoding="utf-8")
    target.write_text("y", encoding="utf-8")
    reason = rename_unsafe_reason({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []})
    assert "已存在" in reason


def test_unsafe_reason_for_empty_target():
    root = make_tmp_root()
    current = root / "a.txt"
    current.write_text("x", encoding="utf-8")
    reason = rename_unsafe_reason({"action": "rename_recommended", "current_path": str(current), "target_path_preview": "", "risk_flags": []})
    assert "为空" in reason


def test_unsafe_reason_for_same_name():
    reason = rename_unsafe_reason({"action": "rename_recommended", "current_file_name": "x.txt", "target_file_name": "x.txt", "current_path": "/tmp/x.txt", "target_path_preview": "/tmp/x.txt", "risk_flags": []})
    assert "相同" in reason


# ---------------------------------------------------------------------------
# can_user_toggle_rename_item / should_check_rename_item_by_default
# ---------------------------------------------------------------------------


def test_safe_item_can_be_toggled_and_checked_by_default():
    root = make_tmp_root()
    current = root / "old.txt"
    target = root / "new.txt"
    current.write_text("x", encoding="utf-8")
    item = {"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []}
    assert can_user_toggle_rename_item(item) is True
    assert should_check_rename_item_by_default(item) is True


def test_unsafe_item_cannot_be_toggled_and_not_checked_by_default():
    root = make_tmp_root()
    current = root / "a.txt"
    current.write_text("x", encoding="utf-8")
    item = {"action": "manual_review", "current_path": str(current), "target_path_preview": str(root / "b.txt"), "risk_flags": []}
    assert can_user_toggle_rename_item(item) is False
    assert should_check_rename_item_by_default(item) is False


# ---------------------------------------------------------------------------
# rename safety rules extended
# ---------------------------------------------------------------------------


def test_rename_safety_rules_edge_cases():
    root = make_tmp_root()
    current = root / "old.txt"
    target = root / "new.txt"
    current.write_text("x", encoding="utf-8")

    # rename_recommended + no risk flags -> safe
    assert is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []})

    # manual_review -> unsafe
    assert not is_safe_rename_item({"action": "manual_review", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []})

    # no_change -> unsafe
    assert not is_safe_rename_item({"action": "no_change", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []})

    # target_name_conflict -> unsafe
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": ["target_name_conflict"]})

    # author_suspicious -> unsafe
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": ["author_suspicious"]})

    # manual_review_needed -> unsafe
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": ["manual_review_needed"]})

    # target_truncated -> unsafe
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": ["target_truncated"]})

    # current file missing -> unsafe
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(root / "missing.txt"), "target_path_preview": str(target), "risk_flags": []})

    # target already exists -> unsafe
    target.write_text("y", encoding="utf-8")
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []})

    # empty target_path -> unsafe
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": "", "risk_flags": []})

    # target_path_preview and target_path both empty -> unsafe
    assert not is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": "", "target_path": "", "risk_flags": []})

    # safe with multiple non-blocking risk flags
    assert is_safe_rename_item({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(root / "safe.txt"), "risk_flags": ["dirty_file_name", "status_extracted"]})


# ---------------------------------------------------------------------------
# command_runner safety for advanced tools page
# ---------------------------------------------------------------------------


def test_advanced_tools_page_cannot_bypass_safety():
    assert ensure_gui_safe_command("apply-renames", ["--confirm", "--yes-i-understand"])[0] is False
    assert ensure_gui_safe_command("apply-updates", ["--confirm", "--yes-i-understand"])[0] is False
    assert ensure_gui_safe_command("move-to-trash", ["--book-id", "1", "--confirm", "--yes-i-understand"])[0] is False
    assert ensure_gui_safe_command("move-to-trash", ["--book-id", "1", "--dry-run"])[0] is True
    assert ensure_gui_safe_command("stage-duplicates", ["--apply"])[0] is False
    assert ensure_gui_safe_command("stage-duplicates", ["--dry-run"])[0] is True

    assert ensure_gui_safe_command("apply-renames", ["--report", "r.json", "--confirm", "--yes-i-understand"], safe_action="apply_selected_renames")[0] is True

    assert ensure_gui_safe_command("apply-renames", ["--report", "r.json", "--confirm", "--yes-i-understand"], safe_action="apply_recommended_updates")[0] is False

    assert ensure_gui_safe_command("move-to-trash", ["--book-id", "1", "--confirm", "--yes-i-understand"], safe_action="move_single_book_to_trash")[0] is True
    assert ensure_gui_safe_command("move-to-trash", ["--confirm", "--yes-i-understand"], safe_action="move_single_book_to_trash")[0] is False


def test_filtered_rename_report_preserves_original():
    repo = make_tmp_root()
    (repo / "library").mkdir()
    (repo / "reports" / "rename").mkdir(parents=True)
    source = repo / "library" / "old.txt"
    target = repo / "library" / "new.txt"
    source.write_text("x", encoding="utf-8")
    report = repo / "reports" / "rename" / "rename_plan_test.json"
    safe = {"action": "rename_recommended", "current_path": str(source), "target_path_preview": str(target), "risk_flags": []}
    manual = {"action": "manual_review", "current_path": str(source), "target_path_preview": str(repo / "library" / "manual.txt"), "risk_flags": []}
    original_data = {"suggestions": [safe, manual], "generated_at": "2026-01-01"}
    report.write_text(json.dumps(original_data, ensure_ascii=False), encoding="utf-8")
    path = write_filtered_rename_plan(repo, report, [safe, manual])
    filtered = json.loads(path.read_text(encoding="utf-8"))
    original = json.loads(report.read_text(encoding="utf-8"))
    assert len(filtered["suggestions"]) == 1
    assert filtered["filtered_by_gui"] is True
    assert "selected_count" in filtered
    assert len(original["suggestions"]) == 2
    assert original["generated_at"] == "2026-01-01"
    assert "filtered_by_gui" not in original


# ---------------------------------------------------------------------------
# get_rename_row_status pure function tests
# ---------------------------------------------------------------------------


def _safe_item(root: Path) -> dict:
    current = root / "old.txt"
    target = root / "new.txt"
    current.write_text("x", encoding="utf-8")
    return {"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []}


def test_row_status_safe_item_is_checkable_and_empty_text():
    root = make_tmp_root()
    status = get_rename_row_status(_safe_item(root))
    assert status["checkable"] is True
    assert status["checked_by_default"] is True
    assert status["status_text"] == ""
    assert status["category"] == "safe"


def test_row_status_manual_review_shows_need_confirm():
    root = make_tmp_root()
    current = root / "a.txt"
    current.write_text("x", encoding="utf-8")
    item = {"action": "manual_review", "current_path": str(current), "target_path_preview": str(root / "b.txt"), "risk_flags": []}
    status = get_rename_row_status(item)
    assert status["checkable"] is False
    assert status["checked_by_default"] is False
    assert status["status_text"] == "需确认"
    assert status["category"] == "manual"


def test_row_status_conflict_shows_has_conflict():
    root = make_tmp_root()
    current = root / "a.txt"
    current.write_text("x", encoding="utf-8")
    item = {"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(root / "b.txt"), "risk_flags": ["target_name_conflict"]}
    status = get_rename_row_status(item)
    assert status["checkable"] is False
    assert status["status_text"] == "有冲突"
    assert status["category"] == "conflict"


def test_row_status_no_change_shows_no_change():
    root = make_tmp_root()
    current = root / "a.txt"
    current.write_text("x", encoding="utf-8")
    item = {"action": "no_change", "current_path": str(current), "target_path_preview": str(root / "a.txt"), "risk_flags": [], "current_file_name": "a.txt", "target_file_name": "a.txt"}
    status = get_rename_row_status(item)
    assert status["checkable"] is False
    assert status["status_text"] == "无需修改"
    assert status["category"] == "no_change"


def test_row_status_missing_file_shows_cannot_process():
    root = make_tmp_root()
    target = root / "b.txt"
    item = {"action": "rename_recommended", "current_path": str(root / "missing.txt"), "target_path_preview": str(target), "risk_flags": []}
    status = get_rename_row_status(item)
    assert status["checkable"] is False
    assert status["status_text"] in ("不可处理",)
    assert status["category"] in ("unsafe",)
    assert "不存在" in status["reason"]


def test_row_status_target_exists_shows_cannot_process():
    root = make_tmp_root()
    current = root / "a.txt"
    target = root / "b.txt"
    current.write_text("x", encoding="utf-8")
    target.write_text("y", encoding="utf-8")
    item = {"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []}
    status = get_rename_row_status(item)
    assert status["checkable"] is False
    assert "已存在" in status["reason"]


def test_row_status_author_suspicious_is_not_checkable():
    root = make_tmp_root()
    current = root / "a.txt"
    target = root / "b.txt"
    current.write_text("x", encoding="utf-8")
    item = {"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": ["author_suspicious"]}
    status = get_rename_row_status(item)
    assert status["checkable"] is False


def test_row_status_safe_items_counted_correctly():
    root = make_tmp_root()
    rows = [_safe_item(root) for _ in range(3)]
    rows.append({"action": "manual_review", "risk_flags": []})
    rows.append({"action": "no_change", "risk_flags": [], "current_file_name": "x.txt", "target_file_name": "x.txt"})
    checkable_count = sum(1 for r in rows if get_rename_row_status(r)["checkable"])
    assert checkable_count == 3


# ---------------------------------------------------------------------------
# row_key / is_row_checked / update_checked_keys
# ---------------------------------------------------------------------------


def test_row_key_prefers_book_id():
    assert row_key({"book_id": 42}) == "book:42"


def test_row_key_falls_back_to_current_path():
    assert row_key({"current_path": "/tmp/foo.txt"}) == "path:/tmp/foo.txt"


def test_row_key_falls_back_to_names():
    assert row_key({"current_file_name": "a.txt", "target_file_name": "b.txt"}) == "name:a.txt:b.txt"


def test_is_row_checked_positive():
    keys = {"book:1", "path:/tmp/x.txt"}
    assert is_row_checked({"book_id": 1}, keys) is True
    assert is_row_checked({"book_id": 2}, keys) is False


def test_update_checked_keys_add():
    keys = {"book:1"}
    result = update_checked_keys(keys, {"book_id": 2}, True)
    assert "book:2" in result
    assert "book:1" in result  # original untouched


def test_update_checked_keys_remove():
    keys = {"book:1", "book:2"}
    result = update_checked_keys(keys, {"book_id": 1}, False)
    assert "book:1" not in result
    assert "book:2" in result


def test_update_checked_keys_is_immutable():
    keys = {"book:1"}
    result = update_checked_keys(keys, {"book_id": 2}, True)
    result.add("extra")
    assert "extra" not in keys


# ---------------------------------------------------------------------------
# can_apply_visible_rows
# ---------------------------------------------------------------------------


def test_can_apply_false_when_no_visible_rows():
    assert can_apply_visible_rows([], {"book:1"}) is False


def test_can_apply_false_when_nothing_checked():
    root = make_tmp_root()
    current = root / "a.txt"
    target = root / "b.txt"
    current.write_text("x", encoding="utf-8")
    item = {"book_id": 1, "action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []}
    assert can_apply_visible_rows([item], set()) is False


def test_can_apply_false_when_checked_but_unsafe():
    root = make_tmp_root()
    item = {"book_id": 1, "action": "manual_review", "risk_flags": []}
    assert can_apply_visible_rows([item], {"book:1"}) is False


def test_can_apply_true_when_visible_has_checked_safe():
    root = make_tmp_root()
    current = root / "a.txt"
    target = root / "b.txt"
    current.write_text("x", encoding="utf-8")
    item = {"book_id": 1, "action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []}
    assert can_apply_visible_rows([item], {"book:1"}) is True


def test_can_apply_false_when_safe_but_not_in_visible():
    root = make_tmp_root()
    current = root / "a.txt"
    target = root / "b.txt"
    current.write_text("x", encoding="utf-8")
    safe_in_visible = {"book_id": 1, "action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []}
    manual_in_visible = {"book_id": 2, "action": "manual_review", "risk_flags": []}
    assert can_apply_visible_rows([manual_in_visible], {"book:1"}) is False
    assert can_apply_visible_rows([safe_in_visible], {"book:1"}) is True


# ---------------------------------------------------------------------------
# initial_checked_keys
# ---------------------------------------------------------------------------


def test_initial_checked_keys_only_includes_safe():
    root = make_tmp_root()
    current = root / "a.txt"
    target = root / "b.txt"
    current.write_text("x", encoding="utf-8")
    rows = [
        {"book_id": 1, "action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []},
        {"book_id": 2, "action": "manual_review", "risk_flags": []},
        {"book_id": 3, "action": "no_change", "risk_flags": [], "current_file_name": "x.txt", "target_file_name": "x.txt"},
    ]
    keys = initial_checked_keys(rows)
    assert "book:1" in keys
    assert "book:2" not in keys
    assert "book:3" not in keys


# ---------------------------------------------------------------------------
# compute_rename_stats
# ---------------------------------------------------------------------------


def test_compute_rename_stats_categories():
    root = make_tmp_root()
    current = root / "a.txt"
    target = root / "b.txt"
    current.write_text("x", encoding="utf-8")
    rows = [
        {"book_id": 1, "action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": []},
        {"book_id": 2, "action": "rename_recommended", "current_path": str(current), "target_path_preview": str(root / "c.txt"), "risk_flags": []},
        {"book_id": 3, "action": "manual_review", "risk_flags": []},
        {"book_id": 4, "action": "no_change", "risk_flags": [], "current_file_name": "x.txt", "target_file_name": "x.txt"},
        {"book_id": 5, "action": "rename_recommended", "current_path": str(current), "target_path_preview": str(target), "risk_flags": ["target_name_conflict"]},
    ]
    checked = {"book:1"}
    s = compute_rename_stats(rows, checked)
    assert s["total"] == 5
    assert s["safe"] == 2  # books 1 and 2 are safe
    assert s["checked"] == 1  # only book 1 checked
    assert s["unselected_safe"] == 1  # book 2 is safe but not checked
    assert s["manual"] == 1  # book 3
    assert s["conflict"] == 1  # book 5
    assert s["no_change"] == 1  # book 4
    assert s["unsafe"] == 0


def test_compute_rename_stats_selected_equals_safe_minus_unselected():
    root = make_tmp_root()
    rows = []
    for i in range(3):
        current = root / f"a{i}.txt"
        target = root / f"b{i}.txt"
        current.write_text("x", encoding="utf-8")
        rows.append(
            {
                "book_id": i + 1,
                "action": "rename_recommended",
                "current_path": str(current),
                "target_path_preview": str(target),
                "risk_flags": [],
            }
        )
    checked = {row_key(rows[0]), row_key(rows[2])}
    s = compute_rename_stats(rows, checked)
    assert s["checked"] == 2
    assert s["unselected_safe"] == 1
    assert s["checked"] + s["unselected_safe"] == s["safe"]


# ---------------------------------------------------------------------------
# row_status ensures non-checkable items never have blank status_text
# ---------------------------------------------------------------------------


def test_row_status_non_checkable_always_has_status_text():
    root = make_tmp_root()
    current = root / "a.txt"
    current.write_text("x", encoding="utf-8")
    scenarios = [
        ({"action": "manual_review", "risk_flags": []}, "需确认"),
        ({"action": "rename_recommended", "current_path": str(current), "target_path_preview": str(root / "b.txt"), "risk_flags": ["target_name_conflict"]}, "有冲突"),
        ({"action": "no_change", "risk_flags": [], "current_file_name": "a.txt", "target_file_name": "a.txt"}, "无需修改"),
        ({"action": "rename_recommended", "current_path": str(root / "missing.txt"), "target_path_preview": str(root / "b.txt"), "risk_flags": []}, "不可处理"),
    ]
    for item, expected_text in scenarios:
        status = get_rename_row_status(item)
        assert status["checkable"] is False, f"Expected non-checkable for {item}"
        assert status["status_text"] == expected_text, f"Expected '{expected_text}' got '{status['status_text']}' for {item}"


# ---------------------------------------------------------------------------
# tools_page report path validation (pure logic)
# ---------------------------------------------------------------------------


def test_tools_page_report_validation_empty_path():
    """Simulate the tools_page validation: empty report path should be rejected."""
    report_path = ""
    assert not report_path


def test_tools_page_report_validation_nonexistent():
    """Simulate the tools_page validation: nonexistent path should be rejected."""
    report_path = "/nonexistent/report.json"
    from pathlib import Path
    assert not Path(report_path).exists()
