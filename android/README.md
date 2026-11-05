# 星河演示管理中心 Android App

本目录保留所选 GitHub 快照的 Android 原生应用源码，品牌和地址已中立化。本轮仅验证 Web 应用，没有构建、签名或发布 APK。下列构建与版本信息是源快照的开发说明。

## 当前能力

- Kotlin + Jetpack Compose、Hilt、Retrofit、Room、WorkManager。
- 加密 Token、刷新令牌、设备会话和退出失效。
- 工作台、关联客户、任务、跟进、项目申请、审批和待支持闭环。
- 客户、商品、供应商、销售、采购、库存、往来移动查询。
- 库存核验、应收校验的移动上传、预校验、提交和差异查看。
- 系统通知、扫码查询、管理看板和管理员只读 AI。
- 财务与过程数据不持久化到 Room；本地仅保留 CRM 表单草稿。
- CRM 有效项目客户和任务采用 SQLCipher 加密缓存，最长离线访问 24 小时。
- 跟进、客户基本资料和待支持事项支持幂等弱网队列、字段冲突处理与加密附件续传。
- 支持同步中心、设备会话、通知偏好、管理员移动运维台和 APK 完整性校验。
- 支持角色式首次引导、帮助中心、可追踪问题反馈和私有截图。
- 跟进表单支持系统语音识别，原始音频不保存、不上传。
- 客户基本资料支持设备端中文名片 OCR，逐字段确认后才回填。
- 管理员可生成跟进、审批意见和项目摘要草稿；AI 不执行保存、提交或审批。
- 智能提醒按业务对象和截止时间去重，支持稍后提醒；采用看板只统计匿名事件与耗时。
- 客户开发提供权限和数据范围受控的线索池、跟进、分配、产品意向与转正审批；转正后仅预填项目申请，不自动创建项目。
- 第六轮线索功能默认关闭；线索 OCR 图片只在设备端处理，离线新建仅保存加密草稿，Outbox 只提交既有服务端线索的跟进。
- 全部 Compose 页面使用 Liquid SysUI 设计系统，支持浅色、深色和跟随系统主题。
- 液态玻璃按系统版本、内存和节电状态自动分级；关闭效果后保留同一布局并切换高对比实色材质。

## 构建要求

- JDK 17
- Android SDK 36（`targetSdk` 仍为 35，`minSdk` 为 26）
- 正式包需要根目录 `signing.properties` 指向交付 keystore，该文件不进入源码包。

```bash
cd android
JAVA_HOME="$HOME/.local/share/jdks/jdk-17.0.19+10/Contents/Home" \
ANDROID_HOME="$HOME/Library/Android/sdk" \
./gradlew verifyLiquidUiBoundary testProductionDebugUnitTest \
  lintProductionDebug assembleProductionRelease
```

正式 APK 输出：`app/build/outputs/apk/production/release/app-production-release.apk`。

生产 API：`https://example.invalid/api/v1/`。移动功能由后端 bootstrap 中的 Feature Flag 灰度控制。

签名 APK 构建并完成校验后，才可把其 SHA-256 写入服务端 `MOBILE_APK_SHA256`；在此之前不得把 `1.6.3` 作为已部署更新发布。

## 迁移测试限制

`RoomMigrationTest` 使用与生产一致的 SQLCipher `SupportOpenHelperFactory` 和口令验证 v1→v2、v2→v3、v3→v4 连续迁移。1.7.0 起不再维护 API 26、31、33、35 的 Gradle Managed Device 多版本矩阵；PR 和发布门禁继续执行单元测试、Liquid 边界、Lint 与构建，Room 迁移和关键 Compose 场景在当前发布目标设备上执行 instrumentation，正式发布仍需完成覆盖升级和灰度验证。

如跨分支切换后 Hilt 聚合阶段出现无法解析已生成模块的异常，可先执行一次无缓存重编译：

```bash
./gradlew --no-build-cache --rerun-tasks :app:hiltJavaCompileProductionDebug
```
