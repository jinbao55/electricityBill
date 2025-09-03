## 辰域电表用电可视化（Flask）

[![Docker Build](https://github.com/jinbao55/electricitybill/actions/workflows/docker-build.yml/badge.svg)](https://github.com/jinbao55/electricitybill/actions/workflows/docker-build.yml)

### 项目目的
本项目通过定时抓取余额、入库，并计算"当日/近7天/近30天"的用电趋势，让手机端直观查看用电量与余额变化。

### 主要功能
- **H5 页面**（移动端优先）：
  - 顶部 KPI：当日用电、当前余额、较昨日/较上周期、预计可用天数
  - 两张图表：用电量（折线图）+ 余额（柱状图）
  - 支持选择日期或切换"今日/近7天/近30天"模式
  - 数值统一保留两位小数，横向可滑动
- **后端 API**：`/data`、`/kpi`、`/period_kpi`、`/fetch`
- **定时抓取**：APScheduler 后台任务，默认每 300 秒抓取一次

### 系统依赖
- Python 3.9+
- Docker + Docker Compose
- MySQL 数据库

### 数据库表结构
```sql
CREATE TABLE IF NOT EXISTS electricity_balance (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  meter_no VARCHAR(64) NOT NULL,
  remain DECIMAL(10,2) NOT NULL,
  collected_at DATETIME NOT NULL,
  KEY idx_meter_time (meter_no, collected_at),
  UNIQUE KEY uk_meter_collected (meter_no, collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 🚀 快速部署

### 方法一：一键部署（推荐）
```bash
# 1. 克隆项目
git clone https://github.com/jinbao55/electricitybill.git
cd electricitybill

# 2. 配置环境变量
cp env.example .env
nano .env  # 修改数据库配置

# 3. 启动服务
./deploy.sh start
```

### 方法二：手动 Docker 部署
```bash
# 1. 克隆项目
git clone https://github.com/jinbao55/electricitybill.git
cd electricitybill

# 2. 配置环境
cp env.example .env
nano .env

# 3. 启动服务
docker-compose up -d --build
```

### 方法三：本地开发
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python mian.py
```

## ⚙️ 环境配置

编辑 `.env` 文件：
```bash
# 数据库配置
DB_HOST=your-database-host
DB_PORT=3306
DB_USER=your-username
DB_PASSWORD=your-password
DB_NAME=your-database

# 应用配置
FETCH_INTERVAL_SECONDS=300  # 数据抓取间隔（秒）
```

## 🔧 服务管理

### 首次部署
```bash
./deploy.sh start
```

### 日常更新
```bash
./update.sh  # 拉取最新代码并重新构建
```

### 服务管理
```bash
./deploy.sh status    # 查看服务状态
./deploy.sh logs      # 查看服务日志
./deploy.sh restart   # 重启服务
./deploy.sh stop      # 停止服务
```

### 手动 Docker 命令
```bash
docker-compose ps           # 查看容器状态
docker-compose logs -f      # 查看实时日志
docker-compose restart      # 重启服务
docker-compose down         # 停止服务
```

## 🌐 访问服务

部署完成后访问：`http://your-server-ip:9136`

## 📊 功能特性

### 智能数据处理
- **00点余额显示**：显示当日第一条余额记录
- **其他时间余额**：显示该时间段最后一条余额记录
- **用电量计算**：准确计算各时间段的用电消耗
- **充值识别**：自动识别并排除充值对用电统计的影响

### 响应式设计
- **移动端优先**：针对手机浏览器优化
- **图表交互**：支持缩放、滑动查看历史数据
- **实时更新**：后台定时抓取，前端可手动刷新

### 时间维度支持
- **日视图**：24小时趋势，支持选择任意历史日期
- **周视图**：近7天趋势对比
- **月视图**：近30天趋势分析

## 📈 计算逻辑

### 当日用电（KPI）
- **今日选择**：当日第一条余额 − 当日最后一条余额
- **历史日期**：该日期首尾余额差值

### 小时趋势（今天视图）
- **每小时余额**：00点取第一条，其他小时取最后一条
- **每小时用电**：上一小时余额 − 当前小时余额

### 天趋势（近7天/近30天）
- **每天余额**：当天最后一条余额
- **每天用电**：同一天内相邻读数的下降量累加

### 周期对比
- **今日vs昨日**：使用 `/kpi` 接口，支持充值识别
- **本周期vs上周期**：使用 `/period_kpi` 接口对比总用电量

## 🔄 自动化特性

### CI/CD 流程
- **代码推送** → GitHub Actions 自动构建镜像
- **服务更新** → 运行 `./update.sh` 更新部署
- **容器监控** → Watchtower 监控容器状态

### 定时任务
- **数据抓取**：每5分钟自动抓取电表数据
- **启动保护**：服务启动时立即抓取一次数据

## 📋 设备配置

在 `mian.py` 中配置监控设备：
```python
DEVICE_LIST = [
    {"id": "19101109825", "name": "设备1"},
    {"id": "19104791678", "name": "设备2"},
]
```

## 🔍 故障排查

### 服务无法启动
```bash
./deploy.sh logs  # 查看详细日志
docker ps         # 检查容器状态
```

### 数据库连接问题
```bash
# 测试数据库连接
docker exec electricity-bill python -c "import pymysql; print('数据库连接测试')"
```

### 端口冲突
```bash
netstat -tlnp | grep 9136  # 检查端口占用
```

## 📁 项目结构

```
electricityBill/
├── mian.py              # 主应用程序
├── requirements.txt     # Python 依赖
├── Dockerfile          # Docker 镜像构建
├── docker-compose.yml  # Docker 编排配置
├── deploy.sh           # 部署管理脚本
├── update.sh           # 更新脚本
├── env.example         # 环境配置模板
├── .env               # 环境配置文件（需创建）
├── templates/         # 前端模板
│   └── index.html     # 主页面
└── .github/workflows/ # GitHub Actions
    └── docker-build.yml
```

## 🚀 在其他机器部署

```bash
# 方法一：Git 克隆
git clone https://github.com/jinbao55/electricitybill.git
cd electricitybill
cp env.example .env && nano .env
./deploy.sh start

# 方法二：更新现有部署
./update.sh
```

## 🛠️ 开发指南

### 本地开发环境
```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp env.example .env && nano .env

# 运行开发服务器
python mian.py
```


## 📝 API 接口

- `GET /` - 前端页面
- `GET /data?period=day|week|month&device_id=ID&date=YYYY-MM-DD` - 获取趋势数据
- `GET /kpi?device_id=ID` - 获取KPI数据（余额、当日/昨日用电）
- `GET /period_kpi?period=week|month&device_id=ID` - 获取周期对比数据
- `GET /fetch?device_id=ID` - 手动触发数据抓取

## 🔒 安全建议

- 通过环境变量配置敏感信息，避免硬编码
- 定期备份数据库数据
- 设置适当的抓取频率，避免对数据源造成压力
- 生产环境建议使用反向代理（Nginx）

## 📞 技术支持

- 查看日志：`./deploy.sh logs`
- 检查状态：`./deploy.sh status`
- 重启服务：`./deploy.sh restart`

---

## 许可证

仅用于个人学习与使用场景。