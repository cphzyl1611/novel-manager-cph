# 双端小说仓库 App 架构文档

## 版本

v0.1.0 — 阶段 1：FastAPI 服务骨架 + Web 书架原型

## 1. 产品目标

打造一个"电脑端 + 手机端双端互联"的本地 TXT 小说管理系统：

- **电脑端**：主仓库服务器，负责存储小说文件、扫描、去重、更新检测、版本判断、文件整理。
- **手机端**：阅读和轻量管理客户端，通过局域网连接电脑端，浏览书架、阅读小说、上传新书、确认轻量操作。

## 2. 为什么采用"电脑端主仓库 + 手机端客户端"

| 考量 | 决策 |
|------|------|
| 数据一致性 | 文件仓库应有唯一主数据源，电脑端作为 authoritative source |
| 计算能力 | 去重、更新检测、章节解析等重计算由电脑端承担 |
| 存储容量 | 电脑端有更大的存储空间 |
| 网络依赖 | 手机端仅在局域网内访问，不需要公网部署 |
| 冲突避免 | 两端不同时修改文件，避免双向同步冲突 |

**不做 P2P 双主同步**。双主同步在文件级别极易产生冲突，且 TXT 文件的合并没有意义。

## 3. 为什么第一阶段用 Web/PWA，而不是直接 Android 原生

| 方案 | 优点 | 缺点 |
|------|------|------|
| Web/PWA | 零安装、跨平台、开发快、与电脑端共享技术栈 | 本地文件访问受限、后台能力弱 |
| Android 原生 | 性能好、文件访问强、通知系统完善 | 开发周期长、需维护两套代码 |
| Flutter | 跨平台、性能接近原生 | 增加技术栈复杂度 |

**第一阶段选择 Web/PWA**，原因：
- 验证双端互联的产品逻辑，无需投入移动端开发；
- 手机浏览器即可访问，用户无需安装任何 App；
- PWA 可添加到主屏幕，接近原生体验；
- 后续可封装为 TWA (Trusted Web Activity) 或 Flutter WebView 容器。

## 4. 双端同步原则

### 4.1 设备模型

```
server_device_id: str    # 电脑端唯一标识（基于 MAC 地址或机器名）
client_device_id: str    # 手机端唯一标识（浏览器 localStorage 生成）
repo_revision: int       # 仓库操作递增序号
operation_id: int        # 每条操作日志的 ID
last_sync_time: str      # ISO 8601
```

### 4.2 同步方向

| 数据类型 | 方向 | 说明 |
|---------|------|------|
| 小说文件 | 手机 → 电脑 | 手机端上传新书到 incoming |
| 阅读进度 | 双向 | 以最后修改时间为准 |
| 标签 | 双向 | 合并，冲突时电脑端优先 |
| 阅读状态 | 双向 | 以最后修改时间为准 |
| 分组 | 电脑 → 手机 | 分组结构由电脑端管理 |
| 操作日志 | 电脑 → 手机 | 手机端拉取变更 |

### 4.3 冲突处理

- 文件内容冲突：不覆盖，新文件进入版本候选（update_candidates）；
- 标签冲突：合并，电脑端优先；
- 删除：使用 tombstone 标记，不做物理删除；
- 所有真实操作写 operation log。

### 4.4 后续 API 预留

```
POST /api/sync/register        # 注册客户端
GET  /api/sync/changes?since=  # 拉取变更
POST /api/sync/progress        # 上传阅读进度
POST /api/books/upload         # 上传新书
```

## 5. 数据流

```
新书 → incoming/ → 扫描引擎(scanner) → SQLite(books表) → 分析引擎(去重/更新)
                                                             ↓
                                                       报告 JSON 文件
                                                             ↓
手机浏览器 ← HTTP :8765 ← FastAPI Server ← 报告 + 数据库
```

## 6. 文件流

```
incoming/  →  library/（主书库，按分组子文件夹组织）
            →  archive/duplicates/（精确/近似重复归档）
            →  archive/replaced/（旧版被新版替代归档）
            →  review_duplicates/（待人工复核）
            →  trash/（软删除）
```

## 7. API 设计

### 7.1 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 健康检查 |
| GET | /api/repo/status | 仓库状态 |
| GET | /api/books | 小说列表（分页、搜索、筛选） |
| GET | /api/books/{book_id} | 小说详情 |
| GET | /api/books/{book_id}/content | 小说正文 |
| GET | /api/groups | 分组列表 |
| POST | /api/groups | 创建分组 |
| GET | /api/issues | 待处理事项聚合 |
| GET | /api/updates/summary | 更新检测概览 |
| GET | /api/sync/status | 同步状态 |

### 7.2 通用响应格式

```json
{ "ok": true, "data": {...}, "error": null }
```

## 8. 数据库扩展建议

当前 SQLite 单表已包含大部分所需字段。后续可扩展：`user_book_state`（阅读进度/书签）、`devices`（设备管理）、`sync_log`（同步日志）。现阶段不修改 schema。

## 9. 重复检测与更新判断逻辑

### 9.1 核心指标

| 指标 | 说明 |
|------|------|
| raw_sha256 | 原始文件 SHA-256 → 精确重复 |
| clean_sha256 | 去广告后 SHA-256 → 内容级重复 |
| title_norm / author_norm | 标准化书名/作者 → 同书识别 |
| simhash | 文本 SimHash → 近似重复快速筛选 |
| block_jaccard | 文本块 Jaccard → 内容重叠度 |
| chapter_title_jaccard | 章节标题 Jaccard → 章节结构相似度 |
| char_count_ratio | 字数比 → 版本长度比较 |
| old_coverage | 旧版在新版中的覆盖率 → 包含关系 |
| new_content_ratio | 新版独有内容比例 → 是否真有新增 |
| chapter_growth | 章节增长数 → 版本更新判断 |
| quality_delta | 质量分变化 → 新版质量是否提升 |

### 9.2 分类规则

**简单重复**：clean_sha256 相同，或 block_overlap >= 0.98 且 char_count_delta <= 0.02 且 chapter_count_delta <= 1。

**更新版本**：same_work_score >= 0.90，old_coverage >= 0.90，new_content_ratio >= 0.05，chapter_growth >= 1，quality_delta >= -10。

**需要人工确认**：作者冲突、覆盖率不足、新版质量下降、新版字数更少、章节顺序异常、疑似缺章、同书分不足。

## 10. 首页书架设计

- 响应式卡片网格：手机 2 列、平板 3 列、桌面 4-5 列
- 卡片内容：书名、作者、阅读进度条、标签、章节数/质量分
- 交互：点击卡片 → 阅读视图、搜索框实时过滤、顶部分组筛选标签、无限滚动加载

## 11. 分组与本地文件夹的关系

- 分组 = library/ 下的一级子文件夹
- 创建分组 = 在 library/ 下创建子文件夹
- library/ 根目录文件属于"默认分组"

## 12. 安全操作原则

1. 默认监听 127.0.0.1，开放 0.0.0.0 时打印安全提示
2. 第一版不做账号系统
3. 所有文件路径限制在 repo 目录下
4. 不提供永久删除 API
5. 不提供直接覆盖文件 API
6. 创建分组只能在 library 下创建子目录

## 13. 阶段路线图

| 阶段 | 内容 | 状态 |
|------|------|------|
| 阶段 0 | CLI 后端 + PySide6 GUI | 完成 |
| 阶段 1 | FastAPI 服务 + Web 书架原型 | 当前 |
| 阶段 2 | 阅读器增强（分章、书签、字体） | 计划中 |
| 阶段 3 | 双端同步（阅读进度、标签） | 计划中 |
| 阶段 4 | PWA 封装（离线缓存、推送通知） | 计划中 |
| 阶段 5 | 移动端原生 App（Flutter/TWA） | 计划中 |
