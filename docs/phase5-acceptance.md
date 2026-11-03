# 阶段五：功能、复现与脱敏验收

本阶段从上一阶段提交建立独立候选。验收执行于新的干净检出目录、专用 Compose 项目和新数据卷；不复用开发 venv、node_modules、runtime 或原演示数据库。

统一入口为 `ci/run.py --fresh-data-check`：构建启动、初始数据校验、重复种子、删除本轮新卷后重建比对、Python 外网阻断自检、全部后端回归、前端检查及浏览器演示。新卷重建前要求该 Compose 项目没有现有容器或数据卷，避免删除已有演示。

依赖/镜像安装阶段需要网络；运行时 Compose 使用 internal 网络，应用没有公网路由。独立入口只固定转发 API/测试 PostgreSQL/Redis，解决 Docker internal 网络不接受直接宿主机端口访问的问题；入口不运行 Provider，不提供任意目标代理。Python 测试通过 `ci/network/sitecustomize.py` 限制 DNS/TCP 为 loopback，并由子 Worker 继承；配置仍限制本机演示数据库。浏览器只允许本机演示地址。HTTP Provider 的源协议测试使用 MockTransport，不产生付费调用。该 Python 守卫约束 Python socket 路径，不宣称它是对任意原生扩展的操作系统沙箱。

本地会实际执行与 GitHub Actions 相同的 `ci/run.py` 入口。远程 Actions 尚未运行，因为候选没有发布或推送；不得以本地通过冒称 GitHub CI 已变绿。Actions 仅上传过滤后的 summary.json，不上传原始日志、trace、下载 ZIP 或含本机路径的 JUnit。

数据/素材、提交历史、凭据/标识扫描与许可证检查记录保存于阶段五整理目录。公开权属边界见 `licensing.md`。最终结果、实测版本及发现项将在本阶段验收记录中列明。
