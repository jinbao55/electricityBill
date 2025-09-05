# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Chinese electricity meter monitoring application that provides real-time visualization of electricity usage and balance. The application scrapes electricity meter data, stores it in MySQL, and presents it through a responsive web interface optimized for mobile devices.

## Architecture

- **Backend**: Flask web server (mian.py) with APScheduler for periodic data collection
- **Frontend**: Single HTML template with Chart.js for data visualization
- **Database**: MySQL with `electricity_balance` table storing meter readings
- **Deployment**: Docker + Docker Compose with Watchtower for auto-updates
- **Data Collection**: Web scraping from `http://www.wap.cnyiot.com/nat/pay.aspx`

## Key Components

### Main Application (mian.py:1)
- Flask routes for API endpoints and web interface
- Scheduled data collection using APScheduler
- Time zone handling for China Standard Time (UTC+8)
- Device configuration in `DEVICE_LIST` (mian.py:26-29)

### Database Schema
```sql
CREATE TABLE electricity_balance (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  meter_no VARCHAR(64) NOT NULL,
  remain DECIMAL(10,2) NOT NULL,
  collected_at DATETIME NOT NULL,
  KEY idx_meter_time (meter_no, collected_at),
  UNIQUE KEY uk_meter_collected (meter_no, collected_at)
)
```

### API Endpoints
- `/data` - Time series data (day/week/month periods)
- `/kpi` - Current KPI metrics with recharge detection
- `/period_kpi` - Period comparison statistics
- `/fetch` - Manual data collection trigger

## Development Commands

### Local Development
```bash
# Create virtual environment and install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp env.example .env
# Edit .env with database credentials

# Run development server
python mian.py
```

### Docker Development
```bash
# Start all services
./deploy.sh start

# View logs
./deploy.sh logs

# Restart services
./deploy.sh restart

# Stop services
./deploy.sh stop

# Check status
./deploy.sh status
```

### Manual Docker Commands
```bash
# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f

# Check container status
docker-compose ps
```

## Environment Configuration

Key environment variables in `.env`:
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` - Database connection
- `FETCH_INTERVAL_SECONDS` - Data collection interval (default: 300)
- `FLASK_DEBUG` - Debug mode toggle

## Deployment

The application uses a sophisticated deployment setup:
- **deploy.sh**: Main deployment script with colored output and error handling
- **update.sh**: Automated update script that pulls latest code and rebuilds
- **Watchtower**: Automatic container monitoring and updates
- **GitHub Actions**: CI/CD pipeline for Docker image building

Access the application at `http://localhost:9136` after deployment.

## Data Processing Logic

### Usage Calculations
- **Daily usage**: Handles 00:00 hour specially (uses first reading), other hours use last reading
- **Recharge detection**: Automatically identifies electricity top-ups by detecting balance increases
- **Cross-midnight handling**: Properly calculates usage across day boundaries
- **Period comparisons**: Supports day/week/month period comparisons

### Time Series Data
- **Day view**: 24-hour trend with hourly granularity
- **Week view**: 7-day trend with daily granularity  
- **Month view**: 30-day trend with daily granularity

## Device Configuration

Update monitored devices in mian.py:26-29:
```python
DEVICE_LIST = [
    {"id": "19101109825", "name": "设备名称1"},
    {"id": "19104791678", "name": "设备名称2"},
]
```

## Testing and Debugging

No formal test framework is configured. For debugging:
- Check application logs: `./deploy.sh logs`
- Test database connection: `docker exec electricity-bill python -c "import pymysql; print('数据库连接测试')"`
- Manual data fetch: Access `/fetch?device_id=DEVICE_ID`
- Port conflicts: `netstat -tlnp | grep 9136`