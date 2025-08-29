#!/bin/bash

# 电表可视化项目一键部署脚本
# 使用方法: ./deploy.sh [start|stop|restart|update|logs]

set -e

PROJECT_NAME="electricity-bill"
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# 检查环境
check_requirements() {
    log_info "检查运行环境..."
    
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi
    
    if [ ! -f "$ENV_FILE" ]; then
        log_warning "环境配置文件不存在，从模板创建..."
        cp env.example "$ENV_FILE"
        log_warning "请编辑 $ENV_FILE 文件配置数据库连接信息"
        log_warning "然后重新运行: ./deploy.sh start"
        exit 1
    fi
    
    log_success "环境检查通过"
}

# 启动服务
start_services() {
    log_info "启动 $PROJECT_NAME 服务..."
    check_requirements
    
    docker-compose -f "$COMPOSE_FILE" up -d
    
    log_success "服务启动成功！"
    log_info "应用地址: http://localhost:9136"
    log_info "查看日志: ./deploy.sh logs"
    log_info "停止服务: ./deploy.sh stop"
}

# 停止服务
stop_services() {
    log_info "停止 $PROJECT_NAME 服务..."
    docker-compose -f "$COMPOSE_FILE" down
    log_success "服务已停止"
}

# 重启服务
restart_services() {
    log_info "重启 $PROJECT_NAME 服务..."
    stop_services
    sleep 2
    start_services
}

# 更新服务
update_services() {
    log_info "更新 $PROJECT_NAME 服务..."
    
    # 拉取最新镜像
    docker-compose -f "$COMPOSE_FILE" pull
    
    # 重启服务
    docker-compose -f "$COMPOSE_FILE" up -d
    
    # 清理旧镜像
    docker image prune -f
    
    log_success "服务更新完成！"
}

# 查看日志
show_logs() {
    log_info "显示服务日志..."
    docker-compose -f "$COMPOSE_FILE" logs -f --tail=100
}

# 显示状态
show_status() {
    log_info "服务状态："
    docker-compose -f "$COMPOSE_FILE" ps
    
    echo ""
    log_info "镜像信息："
    docker images | grep -E "(electricity|watchtower)" || echo "未找到相关镜像"
    
    echo ""
    log_info "Watchtower 监控状态："
    if docker ps --format "table {{.Names}}\t{{.Status}}" | grep -q watchtower; then
        log_success "Watchtower 正在运行"
        docker exec watchtower-electricity watchtower --help > /dev/null 2>&1 && \
            log_info "自动更新功能已启用" || log_warning "Watchtower 可能有问题"
    else
        log_warning "Watchtower 未运行"
    fi
}

# 主菜单
show_help() {
    echo "电表可视化项目部署脚本"
    echo ""
    echo "使用方法:"
    echo "  $0 start     - 启动服务"
    echo "  $0 stop      - 停止服务"  
    echo "  $0 restart   - 重启服务"
    echo "  $0 update    - 更新服务到最新版本"
    echo "  $0 logs      - 查看服务日志"
    echo "  $0 status    - 查看服务状态"
    echo "  $0 help      - 显示此帮助信息"
    echo ""
    echo "首次使用请运行: $0 start"
}

# 主逻辑
case "${1:-help}" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    update)
        update_services
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "未知命令: $1"
        echo ""
        show_help
        exit 1
        ;;
esac