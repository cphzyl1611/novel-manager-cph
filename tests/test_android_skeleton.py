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

def test_settings_gradle_exists():
    assert (ANDROID_APP / "settings.gradle").exists()


def test_root_build_gradle_exists():
    assert (ANDROID_APP / "build.gradle").exists()


def test_gradle_properties_exists():
    assert (ANDROID_APP / "gradle.properties").exists()


def test_menu_resource_exists():
    assert (ANDROID_APP / "app" / "src" / "main" / "res" / "menu" / "menu_main.xml").exists()


def test_menu_has_change_server():
    content = (ANDROID_APP / "app" / "src" / "main" / "res" / "menu" / "menu_main.xml").read_text(encoding="utf-8")
    assert "action_change_server" in content
    assert "action_clear_cache" in content


def test_main_activity_has_change_server():
    content = (ANDROID_APP / "app" / "src" / "main" / "java" / "com" / "novelhub" / "app" / "MainActivity.kt").read_text(encoding="utf-8")
    assert "R.id.action_change_server" in content


def test_main_activity_has_clear_cache():
    content = (ANDROID_APP / "app" / "src" / "main" / "java" / "com" / "novelhub" / "app" / "MainActivity.kt").read_text(encoding="utf-8")
    assert "R.id.action_clear_cache" in content or "clearCache" in content


def test_main_activity_has_on_key_down():
    content = (ANDROID_APP / "app" / "src" / "main" / "java" / "com" / "novelhub" / "app" / "MainActivity.kt").read_text(encoding="utf-8")
    assert "onKeyDown" in content


def test_server_layout_has_error_text():
    content = (ANDROID_APP / "app" / "src" / "main" / "res" / "layout" / "activity_server.xml").read_text(encoding="utf-8")
    assert "errorText" in content


def test_server_layout_has_btn_retry():
    content = (ANDROID_APP / "app" / "src" / "main" / "res" / "layout" / "activity_server.xml").read_text(encoding="utf-8")
    assert "btnRetry" in content

def test_gradle_wrapper_properties_exists():
    assert (ANDROID_APP / "gradle" / "wrapper" / "gradle-wrapper.properties").exists()


def test_gradle_wrapper_pins_8_5():
    content = (ANDROID_APP / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text(encoding="utf-8")
    assert "gradle-8.5-bin.zip" in content


def test_root_build_gradle_has_agp_8_2_0():
    content = (ANDROID_APP / "build.gradle").read_text(encoding="utf-8")
    assert "com.android.application" in content
    assert "8.2.0" in content


def test_root_build_gradle_has_kotlin_1_9_20():
    content = (ANDROID_APP / "build.gradle").read_text(encoding="utf-8")
    assert "org.jetbrains.kotlin.android" in content
    assert "1.9.20" in content


def test_build_doc_explains_gradle_9_issue():
    content = (ANDROID_APP / "docs" / "build_android.md").read_text(encoding="utf-8")
    assert "HasConvention" in content


def test_build_doc_recommends_gradle_8_5():
    content = (ANDROID_APP / "docs" / "build_android.md").read_text(encoding="utf-8")
    assert "Gradle 8.5" in content or "gradle-8.5" in content


def test_no_gradle_9_references():
    content = (ANDROID_APP / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text(encoding="utf-8")
    assert "gradle-9" not in content
