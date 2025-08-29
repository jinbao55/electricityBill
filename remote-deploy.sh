#!/bin/bash

# 电表可视化项目远程部署脚本
# 使用方法: curl -fsSL https://raw.githubusercontent.com/jinbao55/electricityBill/main/remote-deploy.sh | bash

set -e

# 配置
REPO_URL="https://github.com/jinbao55/electricityBill.git"
PROJECT_DIR="electricityBill"
DEFAULT_PORT="9136"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查依赖
check_dependencies() {
    log_info "检查系统依赖..."
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装！"
        log_info "请先安装 Docker: https://docs.docker.com/engine/install/"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose 未安装！"
        log_info "请先安装 Docker Compose: https://docs.docker.com/compose/install/"
        exit 1
    fi
    
    if ! command -v git &> /dev/null; then
        log_error "Git 未安装！请先安装 Git"
        exit 1
    fi
    
    log_success "系统依赖检查通过"
}

# 获取用户输入
get_user_config() {
    log_info "配置部署参数..."
    
    # 数据库配置
    read -p "数据库主机地址 [111.119.253.196]: " DB_HOST
    DB_HOST=${DB_HOST:-111.119.253.196}
    
    read -p "数据库端口 [8806]: " DB_PORT
    DB_PORT=${DB_PORT:-8806}
    
    read -p "数据库用户名 [root]: " DB_USER
    DB_USER=${DB_USER:-root}
    
    read -s -p "数据库密码 [123456]: " DB_PASSWORD
    echo
    DB_PASSWORD=${DB_PASSWORD:-123456}
    
    read -p "数据库名称 [dev]: " DB_NAME
    DB_NAME=${DB_NAME:-dev}
    
    # 应用配置
    read -p "服务端口 [$DEFAULT_PORT]: " APP_PORT
    APP_PORT=${APP_PORT:-$DEFAULT_PORT}
    
    read -p "数据抓取间隔秒数 [300]: " FETCH_INTERVAL
    FETCH_INTERVAL=${FETCH_INTERVAL:-300}
}

# 部署项目
deploy_project() {
    log_info "开始部署电表可视化项目..."
    
    # 克隆或更新项目
    if [ -d "$PROJECT_DIR" ]; then
        log_info "项目目录已存在，更新代码..."
        cd "$PROJECT_DIR"
        git pull
    else
        log_info "克隆项目代码..."
        git clone "$REPO_URL" "$PROJECT_DIR"
        cd "$PROJECT_DIR"
    fi
    
    # 创建环境配置文件
    log_info "创建环境配置..."
    cat > .env << EOF
GITHUB_REPOSITORY=jinbao55/electricitybill
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
DB_CHARSET=utf8mb4
FETCH_INTERVAL_SECONDS=$FETCH_INTERVAL
FLASK_DEBUG=false
EOF
    
    # 修改端口映射（如果不是默认端口）
    if [ "$APP_PORT" != "$DEFAULT_PORT" ]; then
        log_info "修改服务端口为 $APP_PORT..."
        sed -i "s|9136:5000|$APP_PORT:5000|g" docker-compose.local.yml
    fi
    
    # 停止现有服务
    log_info "停止现有服务..."
    docker-compose -f docker-compose.local.yml down 2>/dev/null || true
    
    # 启动服务
    log_info "构建并启动服务..."
    docker-compose -f docker-compose.local.yml up -d --build
    
    # 等待服务启动
    log_info "等待服务启动..."
    sleep 10
    
    # 验证服务
    if curl -f http://localhost:$APP_PORT >/dev/null 2>&1; then
        log_success "服务启动成功！"
        log_success "访问地址: http://$(hostname -I | awk '{print $1}'):$APP_PORT"
    else
        log_warning "服务可能还在启动中，请稍等片刻"
        log_info "查看日志: docker logs electricity-bill"
    fi
    
    # 显示管理命令
    echo ""
    log_info "管理命令:"
    echo "  查看状态: docker-compose -f docker-compose.local.yml ps"
    echo "  查看日志: docker-compose -f docker-compose.local.yml logs -f"
    echo "  重启服务: docker-compose -f docker-compose.local.yml restart"
    echo "  停止服务: docker-compose -f docker-compose.local.yml down"
}

# 主流程
main() {
    echo "========================================"
    echo "   电表可视化项目 - 远程部署脚本"
    echo "========================================"
    echo ""
    
    check_dependencies
    get_user_config
    deploy_project
    
    log_success "部署完成！"
}

# 如果直接运行脚本
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi