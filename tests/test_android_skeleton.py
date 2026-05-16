"""Tests for Android APK wrapper docs and skeleton."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent
ANDROID_APP = ROOT / "android_app"


APK_PLAN_PATH = ROOT / "docs" / "android" / "APK包装方案_v1.md"


def test_apk_plan_doc_exists():
    assert APK_PLAN_PATH.exists()


def test_android_app_readme_exists():
    assert (ANDROID_APP / "README.md").exists()


def test_build_doc_exists():
    assert (ANDROID_APP / "docs" / "build_android.md").exists()


def test_build_gradle_exists():
    assert (ANDROID_APP / "app" / "build.gradle").exists()


def test_android_manifest_exists():
    assert (ANDROID_APP / "app" / "src" / "main" / "AndroidManifest.xml").exists()


def test_manifest_has_internet():
    content = (ANDROID_APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert "INTERNET" in content
    assert "ACCESS_NETWORK_STATE" in content


def test_manifest_has_cleartext():
    content = (ANDROID_APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'usesCleartextTraffic="true"' in content


def test_main_activity_exists():
    assert (ANDROID_APP / "app" / "src" / "main" / "java" / "com" / "novelhub" / "app" / "MainActivity.kt").exists()


def test_main_activity_has_webview_config():
    content = (ANDROID_APP / "app" / "src" / "main" / "java" / "com" / "novelhub" / "app" / "MainActivity.kt").read_text(encoding="utf-8")
    assert "WebView" in content
    assert "javaScriptEnabled" in content
    assert "domStorageEnabled" in content
    assert "getSharedPreferences" in content


def test_resources_exist():
    for f in [
        "res/values/strings.xml", "res/values/styles.xml",
        "res/layout/activity_main.xml", "res/layout/activity_server.xml",
    ]:
        assert (ANDROID_APP / "app" / "src" / "main" / f).exists()


def test_no_file_permissions():
    content = (ANDROID_APP / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert "WRITE_EXTERNAL_STORAGE" not in content
    assert "READ_EXTERNAL_STORAGE" not in content
    assert "MANAGE_EXTERNAL_STORAGE" not in content


def test_apk_plan_has_recommendation():
    content = APK_PLAN_PATH.read_text(encoding="utf-8")
    assert "WebView" in content
    assert "TWA" in content
    assert "推荐" in content or "recommend" in content.lower()
