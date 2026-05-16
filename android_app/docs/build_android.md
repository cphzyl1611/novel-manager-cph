# Android Build Guide

## Prerequisites

- Android Studio Hedgehog (2024.1+) or Android SDK CLI
- Android SDK Platform 34
- JDK 17
- Kotlin 1.9+

## Current status

This is a WebView wrapper shell. It loads the NovelHub Web/PWA in a WebView.
No native UI beyond the server address input page.

## Option A: Android Studio (recommended)

1. Open Android Studio
2. File → Open → select `android_app/` directory
3. Wait for Gradle sync to complete
4. Build → Build APK(s)
5. APK at `app/build/outputs/apk/debug/app-debug.apk`

If Gradle wrapper is missing, Android Studio auto-generates it on first sync.

## Option B: Command line (if Gradle installed)

```bash
cd android_app
gradle wrapper --gradle-version 8.5
./gradlew assembleDebug
```

## Option C: Generate wrapper first

If you have Gradle installed:

```bash
cd android_app
gradle wrapper
./gradlew assembleDebug
```

If neither Gradle nor Android Studio is available, install Android Studio first.

## Install on phone

```bash
adb install app/build/outputs/apk/debug/app-debug.apk
```

Or transfer the APK to your phone and open it.

## Server setup

Start the NovelHub server on the PC:

```bash
cd novel_repo_manager
python server.py --repo "D:/NovelRepo_Test" --host 0.0.0.0 --port 8765
```

Find the PC's LAN IP:

- Windows: `ipconfig` → look for IPv4 under Wi-Fi/Ethernet
- macOS/Linux: `ifconfig` → inet address

## Connect phone

1. Open the APK on your phone
2. First launch: enter `http://<PC-LAN-IP>:8765` (e.g. `http://192.168.1.100:8765`)
3. Tap Connect
4. Subsequent launches auto-connect

## Firewall

Windows Defender Firewall must allow inbound port 8765:

1. Control Panel → Windows Defender Firewall → Advanced Settings
2. Inbound Rules → New Rule → Port → TCP 8765 → Allow

## Debug

Connect phone via USB with USB debugging enabled.
Run from Android Studio or view logs via logcat tag `NovelHub`.

## Release

```bash
./gradlew assembleRelease
```

Requires signing configuration in `app/build.gradle`.

## v1 limitations

- No native file import (uses Web/PWA upload via server)
- No Service Worker (not supported in Android WebView)
- No background sync (app must be open for sync)
- No push notifications

Offline reading works via IndexedDB-based caching (built into the Web/PWA).
