# NovelHub Android APK

WebView wrapper for NovelHub Web/PWA. Loads the local-network server address.

## Prerequisites

- Android Studio Hedgehog+ or Android SDK CLI
- Android SDK API 24+ (Android 7.0)
- Kotlin 1.9+
- Server running: `python server.py --repo ... --host 0.0.0.0 --port 8765`

## Project layout

```
android_app/
  app/
    build.gradle
    src/main/
      AndroidManifest.xml
      java/com/novelhub/app/MainActivity.kt
      res/...
```

## Build

Open `android_app/` in Android Studio → Build → Build APK.

Or CLI:

```bash
cd android_app
./gradlew assembleDebug
```

APK at `app/build/outputs/apk/debug/`.

## Usage

1. Install APK on phone
2. First launch: enter server address e.g. `http://192.168.1.100:8765`
3. Connects and loads NovelHub
4. Subsequent launches auto-connect to last address
5. Menu: clear cache or change server

## Network

- Phone and PC must be on same LAN
- PC firewall must allow port 8765 inbound
- Use LAN IP (not localhost) from phone

## Permissions

- INTERNET — connect to LAN server
- ACCESS_NETWORK_STATE — detect connectivity
