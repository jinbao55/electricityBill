from flask import Flask, render_template, render_template_string, request, jsonify
import os
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import re
import pymysql
from datetime import datetime, timedelta, timezone
import threading
import time

load_dotenv()

# -----------------------
# 配置区域
# -----------------------
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "111.119.253.196"),
    "port": int(os.getenv("DB_PORT", "8806")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "123456"),
    "database": os.getenv("DB_NAME", "dev"),
    "charset": os.getenv("DB_CHARSET", "utf8mb4")
}

DEVICE_LIST = [
    {"id": "19101109825", "name": "孔宝宝"},
    {"id": "19104791678", "name": "旭宝宝"},
]

# -----------------------
# 时区工具（中国标准时间 UTC+8）
# -----------------------
CHINA_TZ = timezone(timedelta(hours=8))

def now_cn():
    # 生成去除 tzinfo 的本地时间，便于与 MySQL DATETIME 对接
    return datetime.now(CHINA_TZ).replace(tzinfo=None)

# -----------------------
# Flask App
# -----------------------
app = Flask(__name__)

HTML_TEMPLATE = None

# -----------------------
# 数据抓取
# -----------------------
def fetch_meter_data(device_id):
    url = f"http://www.wap.cnyiot.com/nat/pay.aspx?mid={device_id}"
    headers={"User-Agent":"Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = "utf-8"
        html_text = resp.text
    except:
        return None

    meter_id_match = re.search(r'<label\s+id=["\']metid["\'].*?>(\d+)</label>', html_text, re.S)
    meter_id = meter_id_match.group(1) if meter_id_match else None
    balance_match = re.search(r'当前剩余.*?<label[^>]*>([\d.]+)</label>', html_text, re.S)
    balance = float(balance_match.group(1)) if balance_match else None

    if not meter_id or balance is None: return None
    return {"meter_no": meter_id, "remain": balance, "collected_at": now_cn()}

def save_to_db(data):
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    sql = "INSERT INTO electricity_balance (meter_no, remain, collected_at) VALUES (%s,%s,%s)"
    try:
        cursor.execute(sql, (data["meter_no"], data["remain"], data["collected_at"]))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# -----------------------
# 数据统计
# -----------------------
def get_statistics(period="day", device_id=None):
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    now = now_cn()
    labels, balances, usage = [], [], []

    where_clause = ""
    params = []
    if device_id:
        where_clause = " AND meter_no=%s"
        params.append(device_id)

    if period=="day":
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        sql = f"SELECT collected_at, remain FROM electricity_balance WHERE collected_at >= %s {where_clause} ORDER BY collected_at"
        cursor.execute(sql,(start_time,*params))
        rows = cursor.fetchall()
        hourly={}
        for r in rows:
            h=r['collected_at'].hour
            hourly.setdefault(h, []).append(r['remain'])
        for h in range(24):
            avg = sum(hourly[h])/len(hourly[h]) if h in hourly else 0
            labels.append(f"{h:02d}点")
            balances.append(avg)
        # 用电量
        prev=None
        for val in balances:
            usage.append(max(prev-val,0) if prev is not None else 0)
            prev=val
    else:
        days = 7 if period=="week" else 30
        start_time = now - timedelta(days=days-1)
        sql = f"SELECT DATE(collected_at) AS d, remain FROM electricity_balance WHERE collected_at >= %s {where_clause} ORDER BY collected_at"
        cursor.execute(sql,(start_time,*params))
        rows = cursor.fetchall()
        daily={}
        for r in rows:
            d=str(r['d'])
            daily.setdefault(d, []).append(r['remain'])
        for d in sorted(daily.keys()):
            avg=sum(daily[d])/len(daily[d])
            labels.append(d)
            balances.append(avg)
        prev=None
        for val in balances:
            usage.append(max(prev-val,0) if prev is not None else 0)
            prev=val

    cursor.close()
    conn.close()
    return labels, balances, usage

def _compute_total_usage(conn, device_id, start_time, end_time):
    cursor = conn.cursor()
    try:
        sql = "SELECT collected_at, remain FROM electricity_balance WHERE meter_no=%s AND collected_at >= %s AND collected_at < %s ORDER BY collected_at"
        cursor.execute(sql, (device_id, start_time, end_time))
        total = 0.0
        prev = None
        for ts, rem in cursor.fetchall():
            try:
                rem_f = float(rem)
            except Exception:
                continue
            if prev is not None:
                drop = prev - rem_f
                if drop > 0:
                    total += drop
            prev = rem_f
        return total
    finally:
        cursor.close()

# -----------------------
# Flask 路由
# -----------------------
@app.route("/")
def index(): 
    return render_template("index.html", devices=DEVICE_LIST)

@app.route("/data")
def data():
    period = request.args.get("period","day")
    device_id = request.args.get("device_id")
    labels, balances, usage = get_statistics(period, device_id)
    return {"labels":labels, "balances":balances, "usage":usage}

def _get_last_balance_for_date(conn, device_id, date_obj):
    cursor = conn.cursor()
    try:
        sql = "SELECT remain FROM electricity_balance WHERE meter_no=%s AND DATE(collected_at)=%s ORDER BY collected_at DESC LIMIT 1"
        cursor.execute(sql, (device_id, date_obj.date()))
        row = cursor.fetchone()
        return float(row[0]) if row else None
    finally:
        cursor.close()

def _get_latest_balance(conn, device_id):
    cursor = conn.cursor()
    try:
        sql = "SELECT remain FROM electricity_balance WHERE meter_no=%s ORDER BY collected_at DESC LIMIT 1"
        cursor.execute(sql, (device_id,))
        row = cursor.fetchone()
        return float(row[0]) if row else None
    finally:
        cursor.close()

@app.route("/kpi")
def kpi():
    device_id = request.args.get("device_id")
    if not device_id:
        device_id = DEVICE_LIST[0]["id"] if DEVICE_LIST else None
    conn = pymysql.connect(**DB_CONFIG)
    try:
        now = now_cn()
        current_balance = _get_latest_balance(conn, device_id) if device_id else None
        yesterday = now - timedelta(days=1)
        day_before = now - timedelta(days=2)
        y_last = _get_last_balance_for_date(conn, device_id, yesterday) if device_id else None
        db_last = _get_last_balance_for_date(conn, device_id, day_before) if device_id else None
        # 充值感知：若今天余额较昨天最后一条更高，则判定有充值
        # 今日用电按：max(昨日最后余额 - 当前余额, 0)
        # 昨日用电按：max(前日最后余额 - 昨日最后余额, 0)
        # 充值估计：max(当前余额 - 昨日最后余额, 0)
        recharge_today = None
        usage_today = None
        usage_yesterday = None
        if current_balance is not None and y_last is not None:
            recharge_today = max(current_balance - y_last, 0.0)
            usage_today = max(y_last - current_balance, 0.0)
        if y_last is not None and db_last is not None:
            usage_yesterday = max(db_last - y_last, 0.0)

        return {
            "current_balance": current_balance,
            "yesterday_last_balance": y_last,
            "day_before_yesterday_last_balance": db_last,
            "usage_today": usage_today,
            "usage_yesterday": usage_yesterday,
            "recharge_today": recharge_today
        }
    finally:
        conn.close()

@app.route("/period_kpi")
def period_kpi():
    device_id = request.args.get("device_id")
    period = request.args.get("period", "day")
    if not device_id:
        device_id = DEVICE_LIST[0]["id"] if DEVICE_LIST else None
    conn = pymysql.connect(**DB_CONFIG)
    try:
        now = now_cn()
        if period == "day":
            start_cur = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_cur = now
            start_prev = start_cur - timedelta(days=1)
            end_prev = start_cur
        elif period == "week":
            start_cur = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_cur = now
            start_prev = start_cur - timedelta(days=7)
            end_prev = start_cur
        else:
            start_cur = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_cur = now
            start_prev = start_cur - timedelta(days=30)
            end_prev = start_cur

        cur_total = _compute_total_usage(conn, device_id, start_cur, end_cur)
        prev_total = _compute_total_usage(conn, device_id, start_prev, end_prev)
        return {"period": period, "current_usage": cur_total, "previous_usage": prev_total}
    finally:
        conn.close()

@app.route("/fetch")
def fetch():
    device_id = request.args.get("device_id","19101109825")
    data = fetch_meter_data(device_id)
    if data:
        save_to_db(data)
        return {"message":f"✅ 抓取成功：{data}"}
    return {"message":"❌ 抓取失败"}

# -----------------------
# 后台定时抓取
# -----------------------
def scheduled_fetch():
    for device in DEVICE_LIST:
        data = fetch_meter_data(device["id"])
        if data: save_to_db(data)

if __name__=="__main__":
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    interval_seconds = int(os.getenv("FETCH_INTERVAL_SECONDS", "60"))
    scheduler.add_job(scheduled_fetch, 'interval', seconds=interval_seconds, id='fetch_job', max_instances=1, coalesce=True)
    # 首次启动时，立即触发一次抓取，避免页面空白
    scheduler.add_job(scheduled_fetch, 'date', run_date=datetime.now() + timedelta(seconds=1), id='bootstrap_fetch', misfire_grace_time=60, coalesce=True)
    scheduler.start()
    try:
        app.run(host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "false").lower()=="true")
    finally:
        scheduler.shutdown(wait=False)
