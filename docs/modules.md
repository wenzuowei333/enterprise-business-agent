# 功能与源码导航

本版本以完整应用组织内容，功能模块、入口和代码位置见 [项目首页](../README.md)。

完整 Web 后端与前端保留：所有原有 API 路由、服务、数据模型、Schema 与 Alembic 迁移均在对应目录。Android 应用及其测试源码保留在 `android/`，品牌、包名和主机已中立化，本次没有构建或发布 Android 安装包。

演示适配集中在 `backend/app/demo_seed.py`、`demo/mock_provider.py`、`demo/full_smoke.py`、`docker-compose.demo.yml` 和 `Dockerfile.demo`；合成数据没有从生产文件抽样。

[逐文件覆盖记录](source-coverage-full.json) · [页面截图](screenshots.md) · [验证结果](validation.md)

完整项目指所选 GitHub 源快照的应用模块，排除的是原品牌媒体、运行数据、生产环境与内部规划/运维记录；尚未同步到 GitHub 的后续本地代码不在本版中。
