# Android APK 包装方案 v1

## 1. 项目目标

把现有 NovelHub Web/PWA 包装为可安装 APK。手机端只连接局域网电脑端、加载 WebView、同步缓存、阅读。电脑端仍是唯一权威仓库。

## 2. 职责边界

| 职责 | 电脑端 | 手机端 APK |
|------|--------|-----------|
| TXT 存储/扫描/去重 | ✅ | ❌ |
| SQLite 数据库 | ✅ | ❌ |
| 上传新书/版本替换 | ✅ | ❌ |
| 阅读小说 | ✅ Web UI | ✅ WebView |
| 离线缓存 | ❌ | ✅ IndexedDB |
| 配对授权 | ✅ | ✅ token 存储 |
| 同步进度 | ✅ 接收 | ✅ 上传 |

## 3. 技术路线评估

### Capacitor — 不推荐当前阶段

依赖 npm/Node 生态，与本项目纯 Python 技术栈不符。功能强大但现阶段过重。

### TWA (Trusted Web Activity) — 不推荐

**必须 HTTPS 和 Digital Asset Links 验证**。本项目的核心场景是 `http://192.168.x.x:8765` 局域网 HTTP，TWA 无法满足。

### 原生 Android WebView — 推荐

- 局域网 HTTP 无限制（`usesCleartextTraffic="true"`）
- 零外部依赖，纯 Android SDK（API 24+）
- 完全控制 WebView 配置：JavaScript、DOM Storage、IndexedDB 均可用
- APK < 3MB
- SharedPreferences 存储 token 和服务器地址
- 后续可逐步增加扫码、局域网发现

## 4. Service Worker 兼容性

Android WebView **不支持** Service Worker。但 SW 在本项目中仅用于静态资源缓存和离线 PWA 入口，离线阅读的核心逻辑已由 IndexedDB 数据层接管，SW 非必需。

## 5. APK v1 功能范围

| # | 功能 | 描述 |
|---|------|------|
| 1 | 启动页 | 图标 + 名称 |
| 2 | 地址输入 | 输入 `http://192.168.x.x:8765` |
| 3 | 地址记忆 | SharedPreferences 保存 |
| 4 | WebView | 加载 NovelHub 完整 UI |
| 5 | 返回键 | 阅读页→书架；根页面→退出确认 |
| 6 | 清除缓存 | 清除 WebView 缓存和 IDB |
| 7 | 更换服务器 | 重新输入地址 |
| 8 | 连接失败 | 显示重试/更改地址页 |

## 6. APK v1 不做什么

不访问文件系统、不做原生书架/阅读器、不做后台同步、不做公网穿透、不做自动扫描局域网、不做账号系统

## 7. WebView 兼容风险表

| 项目 | 状态 | 风险 | 处理 |
|------|------|------|------|
| JavaScript | ✅ | 无 | setJavaScriptEnabled(true) |
| DOM Storage | ✅ | 无 | setDomStorageEnabled(true) |
| IndexedDB | ✅ API 21+ | 低 | 默认启用 |
| Service Worker | ❌ | 中 | IDB 接管离线，SW 非必需 |
| file input | ✅ | 低 | 需 WebChromeClient |
| fetch | ✅ | 无 | — |
| http 局域网 | ✅ | 低 | cleartextTraffic="true" |
| CSS backdrop-filter | ⚠ API 28+ | 低 | 低版本降级纯色 |
| Notification | ❌ | 低 | 本阶段不依赖 |
| PWA manifest | ❌ | 低 | APK 不需要 |

## 8. 权限

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
<!-- 不申请文件存储权限 -->
```

## 9. 后续路线

| 阶段 | 内容 |
|------|------|
| v1 (本轮) | 文档 + 项目骨架 |
| v1.1 | 可编译 APK + WebView 加载 |
| v1.2 | 返回键 + 菜单 + 地址记忆 |
| v1.3 | 连接失败处理 + 缓存管理 |
| v2 | 扫码连接 + 局域网发现 |
