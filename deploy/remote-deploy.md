# 远端部署说明

目标服务器：

```text
192.0.2.1
```

目标目录：

```text
/opt/enterprise-business-agent
```

当前启动方式：

```bash
cd /opt/enterprise-business-agent
sudo systemctl status enterprise-business-agent --no-pager
curl http://127.0.0.1/api/v1/health
curl http://127.0.0.1/api/v1/health/db
```

如果切换到 Docker Compose：

```bash
cd /opt/enterprise-business-agent
sudo systemctl stop enterprise-business-agent
sudo docker compose up -d --build
```

注意：

- 上线前备份代码目录和数据库。
- 不覆盖其他业务系统配置。
- 服务异常时先查看 systemd 状态、应用日志和数据库健康状态。
