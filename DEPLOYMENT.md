# 🚀 CI/CD 部署指南

本文档详细说明如何为电表可视化项目设置 GitHub Actions + Watchtower 的自动化部署流程。

## 📋 目录

- [快速开始](#快速开始)
- [GitHub Actions 配置](#github-actions-配置)
- [Watchtower 配置](#watchtower-配置)
- [部署方式](#部署方式)
- [环境变量配置](#环境变量配置)
- [故障排查](#故障排查)

## 🚀 快速开始

### 1. 启用 GitHub Container Registry

1. 进入 GitHub 仓库 → Settings → Actions → General
2. 确保 "Read and write permissions" 已启用
3. 推送代码到 `main` 分支，GitHub Actions 会自动构建镜像

### 2. 部署应用 + Watchtower

```bash
# 克隆项目
git clone https://github.com/yourusername/electricitybill.git
cd electricitybill

# 配置环境变量
cp env.example .env
# 编辑 .env 文件，修改数据库连接等配置

# 启动完整服务（应用 + Watchtower）
docker-compose up -d

# 或者只启动 Watchtower（如果应用已经在运行）
docker-compose -f watchtower-compose.yml up -d
```

## 🔧 GitHub Actions 配置

### 工作流特性

- **触发条件**: 推送到 `main`/`master` 分支或创建 PR
- **多架构构建**: 支持 `linux/amd64` 和 `linux/arm64`
- **缓存优化**: 使用 GitHub Actions 缓存加速构建
- **自动标签**: 生成 `latest`、分支名、SHA 等多种标签
- **权限最小化**: 只需要 `contents:read` 和 `packages:write`

### 镜像命名规则

| 分支/事件 | 镜像标签 | 示例 |
|-----------|----------|------|
| main 分支 | `latest` | `ghcr.io/user/repo:latest` |
| 功能分支 | 分支名 | `ghcr.io/user/repo:feature-branch` |
| PR | `pr-数字` | `ghcr.io/user/repo:pr-123` |
| 提交 SHA | `分支-sha` | `ghcr.io/user/repo:main-abc1234` |

## 🐳 Watchtower 配置

### 核心特性

- **智能监控**: 只监控带有 `com.centurylinklabs.watchtower.enable=true` 标签的容器
- **定时检查**: 每5分钟检查一次镜像更新
- **自动清理**: 更新后自动删除旧镜像
- **通知支持**: 支持 Slack、邮件等多种通知方式
- **资源限制**: 限制内存使用，避免影响主服务

### 监控标签

在应用容器中添加以下标签以启用 Watchtower 监控：

```yaml
labels:
  - "com.centurylinklabs.watchtower.enable=true"
  - "com.centurylinklabs.watchtower.monitor-only=false"
```

## 📦 部署方式

### 方式一：完整部署（推荐）

使用 `docker-compose.yml` 一次性部署应用和 Watchtower：

```bash
# 配置环境变量
cp env.example .env
nano .env  # 修改数据库配置等

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 方式二：独立部署 Watchtower

如果应用已经在运行，只需要添加 Watchtower：

```bash
# 首先为现有容器添加标签
docker update --label-add com.centurylinklabs.watchtower.enable=true electricity-bill

# 启动 Watchtower
docker-compose -f watchtower-compose.yml up -d
```

### 方式三：手动部署应用

```bash
# 拉取最新镜像
docker pull ghcr.io/yourusername/electricitybill:latest

# 停止旧容器
docker stop electricity-bill
docker rm electricity-bill

# 启动新容器
docker run -d \
  --name electricity-bill \
  --restart unless-stopped \
  -p 9136:5000 \
  -e TZ=Asia/Shanghai \
  -e DB_HOST=111.119.253.196 \
  -e DB_PORT=8806 \
  -e DB_USER=root \
  -e DB_PASSWORD=123456 \
  -e DB_NAME=dev \
  -e FETCH_INTERVAL_SECONDS=300 \
  --label com.centurylinklabs.watchtower.enable=true \
  ghcr.io/yourusername/electricitybill:latest
```

## 🔐 环境变量配置

### 必需配置

```bash
# GitHub 仓库（替换为你的实际仓库）
GITHUB_REPOSITORY=yourusername/electricitybill

# 数据库连接
DB_HOST=your-db-host
DB_PORT=3306
DB_USER=your-username  
DB_PASSWORD=your-password
DB_NAME=your-database
```

### 可选配置

```bash
# 应用配置
FETCH_INTERVAL_SECONDS=300  # 数据抓取间隔
FLASK_DEBUG=false          # Flask 调试模式

# Slack 通知（可选）
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK
```

## 🔄 工作流程

### 开发流程

1. **本地开发** → 修改代码
2. **提交推送** → `git push origin main`
3. **自动构建** → GitHub Actions 构建新镜像
4. **自动部署** → Watchtower 检测并更新容器
5. **服务可用** → 新版本自动上线

### 时间线示例

```
10:00 - 开发者推送代码
10:02 - GitHub Actions 开始构建
10:05 - 镜像构建完成并推送到 GHCR
10:10 - Watchtower 检测到新镜像
10:11 - Watchtower 停止旧容器，启动新容器
10:12 - 新版本服务可用
```

## 📊 监控和日志

### 查看 GitHub Actions 状态

```bash
# 在 GitHub 仓库页面查看
https://github.com/yourusername/electricitybill/actions
```

### 查看 Watchtower 日志

```bash
# 实时查看 Watchtower 日志
docker logs -f watchtower

# 查看应用日志
docker logs -f electricity-bill

# 查看所有服务日志
docker-compose logs -f
```

### 常用监控命令

```bash
# 查看容器状态
docker ps

# 查看镜像信息
docker images | grep electricity

# 查看 Watchtower 监控的容器
docker inspect electricity-bill | grep -A5 Labels

# 手动触发更新检查
docker exec watchtower watchtower --run-once
```

## 🛠️ 故障排查

### 常见问题

#### 1. GitHub Actions 构建失败

```bash
# 检查 Dockerfile 语法
docker build -t test .

# 检查权限设置
# GitHub → Settings → Actions → General → Workflow permissions
```

#### 2. Watchtower 不更新容器

```bash
# 检查容器标签
docker inspect electricity-bill | grep watchtower

# 添加标签
docker update --label-add com.centurylinklabs.watchtower.enable=true electricity-bill

# 重启 Watchtower
docker restart watchtower
```

#### 3. 镜像拉取失败

```bash
# 检查镜像是否存在
docker pull ghcr.io/yourusername/electricitybill:latest

# 检查网络连接
curl -I https://ghcr.io

# 手动登录 GHCR（如果是私有仓库）
echo $GITHUB_TOKEN | docker login ghcr.io -u yourusername --password-stdin
```

### 调试技巧

```bash
# Watchtower 调试模式
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -e WATCHTOWER_DEBUG=true \
  -e WATCHTOWER_LOG_LEVEL=debug \
  containrrr/watchtower --run-once

# 查看详细的容器更新过程
docker exec watchtower watchtower --debug --run-once
```

## 🔒 安全建议

### GitHub Actions 安全

1. **使用 GITHUB_TOKEN**: 自动提供，无需手动配置
2. **权限最小化**: 只启用必要的权限
3. **分支保护**: 设置 main 分支保护规则

### Watchtower 安全

1. **网络隔离**: 使用专用网络
2. **资源限制**: 限制 CPU 和内存使用
3. **只读挂载**: Docker socket 以只读方式挂载（如果可能）

### 生产环境建议

```bash
# 使用专用网络
docker network create electricity-network

# 限制 Watchtower 权限
# 在 docker-compose.yml 中添加：
user: "1000:1000"  # 非 root 用户
read_only: true    # 只读文件系统
```

## 📈 高级配置

### 分阶段部署

```yaml
# 在 docker-compose.yml 中添加健康检查
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:5000/"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

### 蓝绿部署

```bash
# 使用不同的容器名称实现蓝绿部署
docker run -d --name electricity-bill-blue ...
docker run -d --name electricity-bill-green ...
# 使用 nginx 或 traefik 进行流量切换
```

## 🎯 最佳实践

1. **定期备份**: 定期备份数据库和配置文件
2. **监控告警**: 配置 Slack/邮件通知
3. **版本管理**: 使用语义化版本标签
4. **回滚准备**: 保留最近几个版本的镜像
5. **测试环境**: 在测试环境先验证更新

---

## 📞 支持

如有问题，请查看：
- GitHub Actions 日志
- Watchtower 容器日志  
- 应用容器日志

或提交 Issue 到项目仓库。