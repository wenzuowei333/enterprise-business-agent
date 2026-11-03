# 招聘展示发布

发布版本：`v0.1.0-showcase`；发布日期：2026-11-04。阶段六基线：`e60baf14bd8db3f86fd8025986e4ccca53578017`。

- 仓库：https://github.com/wenzuowei333/enterprise-business-agent
- 发布与录屏：https://github.com/wenzuowei333/enterprise-business-agent/releases/tag/v0.1.0-showcase
- 自动验收：https://github.com/wenzuowei333/enterprise-business-agent/actions/workflows/ci.yml
- 作者主页：https://github.com/wenzuowei333

本版保留经过脱敏验收的业务切片、合成数据、Mock Provider、截图和实际录屏。发布整理仅修改文档及 CI 执行环境报告，未增加业务能力；完整文件增量见 `source-provenance-phase7.json`。旧阶段五/六验收与来源清单为历史快照，不能将其时间和范围当成新执行记录。

GitHub Actions 从检出开始安装锁定依赖、构建演示容器、检查隔离网络、执行新卷初始化/重复种子/重建、后端回归及浏览器场景；商品项目另执行前端测试及类型检查。每次结果以对应运行的结论与 `acceptance-summary` 附件为准，未使用固定成功徽章或提前宣称通过。只上传过滤 JSON 摘要，不上传原始日志文件、业务附件或运行数据库。

默认启动方式见 README；完整离线验收入口见 `evaluation.md`。无外部模型密钥也可运行，不提供公共在线业务服务。功能测试与录屏证明工作流机制，不证明真实模型质量、生产成功率或严格一次的外部模型收费。

此仓库公开可读，未附新的开源授权；来源、素材和第三方依赖说明继续适用，见 `licensing.md`。原私有业务仓库、真实数据、本机证据和简历联系方式均不在发布范围。
