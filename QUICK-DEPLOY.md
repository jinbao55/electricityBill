# 🚀 快速部署指南

在其他机器上部署电表可视化项目的简单方法。

## 📋 前提条件

确保目标机器已安装：
- Docker
- Docker Compose  
- Git

## 🎯 部署方法

### 方法一：一键部署脚本（推荐）

```bash
# 下载并运行部署脚本
curl -fsSL https://raw.githubusercontent.com/jinbao55/electricityBill/main/remote-deploy.sh | bash
```

脚本会自动：
- 检查系统依赖
- 克隆项目代码
- 配置数据库连接
- 构建并启动服务

### 方法二：手动部署

```bash
# 1. 克隆项目
git clone https://github.com/jinbao55/electricityBill.git
cd electricityBill

# 2. 配置环境变量
cp env.example .env
nano .env  # 修改数据库配置

# 3. 启动服务
docker-compose -f docker-compose.local.yml up -d --build
```

### 方法三：使用部署脚本

```bash
# 1. 克隆项目
git clone https://github.com/jinbao55/electricityBill.git
cd electricityBill

# 2. 运行部署脚本
./deploy.sh start
```

## ⚙️ 环境配置

需要配置的主要参数：

```bash
# 数据库连接
DB_HOST=your-database-host
DB_PORT=3306
DB_USER=your-username
DB_PASSWORD=your-password
DB_NAME=your-database

# 应用配置
FETCH_INTERVAL_SECONDS=300  # 数据抓取间隔
```

## 🔧 常用管理命令

```bash
cd electricityBill

# 查看服务状态
docker-compose -f docker-compose.local.yml ps

# 查看日志
docker-compose -f docker-compose.local.yml logs -f

# 重启服务
docker-compose -f docker-compose.local.yml restart

# 停止服务
docker-compose -f docker-compose.local.yml down

# 更新代码并重启
git pull
docker-compose -f docker-compose.local.yml up -d --build
```

## 🌐 访问服务

部署完成后，通过以下地址访问：

```
http://机器IP:9136
```

## 🔍 故障排查

### 服务无法启动
```bash
# 查看详细日志
docker logs electricity-bill

# 检查端口占用
netstat -tlnp | grep 9136

# 检查数据库连接
docker exec electricity-bill python -c "import pymysql; print('数据库连接测试')"
```

### 数据库连接问题
```bash
# 测试数据库连接
docker run --rm -it mysql:8.0 mysql -h你的数据库IP -P端口 -u用户名 -p

# 检查防火墙
telnet 数据库IP 数据库端口
```

## 📦 多环境部署

### 开发环境
```bash
# 使用开发数据库
cp env.example .env.dev
# 修改 .env.dev 中的数据库配置为开发库
docker-compose -f docker-compose.local.yml --env-file .env.dev up -d --build
```

### 生产环境
```bash
# 使用生产数据库
cp env.example .env.prod  
# 修改 .env.prod 中的数据库配置为生产库
docker-compose -f docker-compose.local.yml --env-file .env.prod up -d --build
```

## 🔄 批量部署

如果要在多台机器上部署，可以使用脚本：

```bash
#!/bin/bash
# 批量部署到多台服务器

SERVERS=("192.168.1.10" "192.168.1.11" "192.168.1.12")

for server in "${SERVERS[@]}"; do
    echo "部署到 $server..."
    ssh root@$server 'curl -fsSL https://raw.githubusercontent.com/jinbao55/electricityBill/main/remote-deploy.sh | bash'
done
```

## 🎯 最简单的方法

**在新机器上运行一条命令**：

```bash
curl -fsSL https://raw.githubusercontent.com/jinbao55/electricityBill/main/remote-deploy.sh | bash
```

这个脚本会引导你完成整个部署过程！