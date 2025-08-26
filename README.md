## 辰域电表用电可视化（Flask）

### 项目目的
- 本项目通过定时抓取余额、入库，并计算“当日/近7天/近30天”的用电趋势，让手机端直观查看用电量与余额变化。

### 主要功能
- H5 页面（移动端优先）：
  - 顶部 KPI：当日用电、当前余额、较昨日/较上周期、预计可用天数
  - 两张图：
    - 用电量（折线，波浪填充，上方）
    - 余额（柱状，下方）
  - 支持选择日期（默认今天）或切换“今日/近7天 / 近30天”并显示当前时间范围
  - 数值统一保留两位小数，横向可滑动
- 后端 API：`/data`、`/kpi`、`/period_kpi`、`/fetch`
- 定时抓取：APScheduler 后台任务，默认每 300 秒抓取一次；启动时自动触发一次抓取避免空白

### 依赖
- Python 3.9+
- Flask, requests, PyMySQL, APScheduler, python-dotenv（已在 `requirements.txt`）

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

### 运行方式
#### 本地
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python mian.py
```

#### Docker（推荐）
```bash
docker build -t electricity-bill:latest .
docker run -d --name electricity-bill \
  --restart unless-stopped \
  -p 9136:5000 \
  -e TZ=Asia/Shanghai \
  # 可选：覆盖默认数据库连接
  -e DB_HOST=111.119.253.196 -e DB_PORT=8806 \
  -e DB_USER=root -e DB_PASSWORD=123456 -e DB_NAME=dev \
  -e FETCH_INTERVAL_SECONDS=300 \
  electricity-bill:latest
```

### 配置（环境变量，均有默认值）
- `DB_HOST` `DB_PORT` `DB_USER` `DB_PASSWORD` `DB_NAME` `DB_CHARSET`
- `FETCH_INTERVAL_SECONDS`：抓取间隔（秒），默认 300
- `HOST` `PORT` `FLASK_DEBUG`：Flask 运行参数

### 使用说明（前端）
- 顶部“日期”按钮：打开系统日期选择器（默认今天）。
- “今日/近7天/近30天”按钮：切换周期；再次点击“日期”可回到按天模式。
- 标题下方显示当前选择的日期或时间段。

### 计算口径（核心逻辑）
- 当日用电（KPI）
  - 当日第一条余额 − 当日最后一条余额（若为负取 0）
- 今天视图（小时趋势）
  - 每小时余额：该小时“最后一条余额”
  - 每小时用电：上一小时“最后一条余额” − 当前小时“最后一条余额”（负取 0）
- 近7天/近30天视图（天趋势）
  - 每天余额：当天“最后一条余额”
  - 每天用电：同一天内相邻读数的“下降量之和”（上涨视为充值忽略）
- 较昨日/较上周期
  - 今日与昨日：使用 `/kpi`，充值感知（上涨记为充值，不计入用电）
  - 周/月：使用 `/period_kpi` 比较“本周期总用电 − 上周期总用电”

### API 摘要
- `GET /`：前端页面
- `GET /data?period=day|week|month&device_id=ID&date=YYYY-MM-DD`：趋势数据
- `GET /kpi?device_id=ID`：余额与当日/昨日用电、充值估计
- `GET /period_kpi?period=week|month&device_id=ID`：本周期/上周期用电
- `GET /fetch?device_id=ID`：立即抓取并入库（用于手动刷新）

### 设备配置
在 `mian.py` 的 `DEVICE_LIST` 中维护：
```python
DEVICE_LIST = [
    {"id": "19101109825", "name": "设备1"},
    {"id": "19104791678", "name": "设备2"},
]
```

### 常见问题
- 页面空白/无数据：首次启动已自动抓取一次；也可点击“抓取”按钮；确认数据库连通性。
- 时区偏差：应用已使用北京时间；如需，数据库会话可执行 `SET time_zone = '+08:00'`。
- 端口：Docker 默认 5000，示例将宿主机 9136 映射到容器 5000。

### 安全提示
- 生产环境请通过环境变量传递数据库凭据，避免提交到仓库。

### 许可
仅用于个人学习与使用场景；抓取频率请合理设置，避免对第三方服务造成压力。

