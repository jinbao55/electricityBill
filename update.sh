#!/bin/bash

# 电表可视化项目一键更新脚本
# 使用方法: ./update.sh

set -e

# 颜色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}[INFO]${NC} 开始更新电表可视化项目..."

# 1. 拉取最新代码
echo -e "${BLUE}[INFO]${NC} 拉取最新代码..."
git pull

# 2. 停止现有服务并清理
echo -e "${BLUE}[INFO]${NC} 停止现有服务..."
docker-compose -f docker-compose.local.yml down 2>/dev/null || true

# 3. 重新构建并启动服务
echo -e "${BLUE}[INFO]${NC} 重新构建并启动服务..."
docker-compose -f docker-compose.local.yml up -d --build

# 3. 显示服务状态
echo -e "${BLUE}[INFO]${NC} 服务状态："
docker-compose -f docker-compose.local.yml ps

# 4. 测试服务
echo -e "${BLUE}[INFO]${NC} 测试服务..."
if curl -f http://localhost:9136 >/dev/null 2>&1; then
    echo -e "${GREEN}[SUCCESS]${NC} 服务更新成功！访问地址: http://localhost:9136"
else
    echo -e "${BLUE}[INFO]${NC} 服务可能还在启动中，请稍等片刻"
fi

echo ""
echo "管理命令："
echo "  查看日志: docker-compose -f docker-compose.local.yml logs -f"
echo "  重启服务: docker-compose -f docker-compose.local.yml restart"
echo "  停止服务: docker-compose -f docker-compose.local.yml down"