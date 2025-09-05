# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an electricity meter monitoring and visualization system built with Flask. The application monitors electricity balance data from IoT devices, stores it in MySQL, and provides a responsive H5 web interface for visualizing power consumption trends.

## Key Architecture

- **Backend**: Flask web application with RESTful APIs
- **Database**: MySQL for storing electricity balance records with timestamps  
- **Frontend**: Single-page H5 application optimized for mobile devices
- **Data Collection**: Automated scheduled fetching from IoT meter endpoints using APScheduler
- **Deployment**: Docker containerized with docker-compose orchestration

## Core Components

- `main.py`: Main Flask application with data fetching, API endpoints, and scheduling logic
- `templates/index.html`: Mobile-first frontend with Chart.js visualizations
- `docker-compose.yml`: Multi-service container setup including Watchtower for auto-updates
- Database table: `electricity_balance` with meter readings and timestamps

## Development Commands

### Local Development
```bash
# Setup virtual environment and dependencies  
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp env.example .env
# Edit .env with database credentials

# Run development server
python main.py
```

### Docker Development/Production
```bash
# One-time deployment (recommended)
./deploy.sh start

# Manual Docker deployment
docker-compose up -d --build

# Service management
./deploy.sh status    # View service status
./deploy.sh logs      # View service logs  
./deploy.sh restart   # Restart services
./deploy.sh stop      # Stop services

# Updates
./update.sh           # Pull latest code and rebuild
```

## Configuration

Environment variables in `.env`:
- Database: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- Application: `FETCH_INTERVAL_SECONDS` (default: 300)
- Device list configured in `main.py` DEVICE_LIST array

## API Endpoints

- `GET /data?period=day|week|month&device_id=ID&date=YYYY-MM-DD` - Trend data
- `GET /kpi?device_id=ID` - Current balance and daily usage KPIs
- `GET /period_kpi?period=week|month&device_id=ID` - Period comparison data
- `GET /fetch?device_id=ID` - Manual data fetch trigger

## Data Processing Logic

The system handles complex scenarios including:
- Recharge detection and exclusion from power consumption calculations
- Cross-midnight usage calculations using previous day's last reading
- Hourly aggregation (00:00 uses first reading, other hours use last reading)
- Daily/weekly/monthly trend calculations with proper date handling

## Service Access

Default port: 9136 (mapped from container port 5000)
Frontend accessible at: `http://localhost:9136`