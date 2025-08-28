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
def get_statistics(period="day", device_id=None, target_date=None):
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        now = now_cn()
        labels, balances, usage = [], [], []

        where_clause = ""
        params = []
        if device_id:
            where_clause = " AND meter_no=%s"
            params.append(device_id)

        if period == "day":
            if target_date:
                try:
                    base = datetime.strptime(target_date, "%Y-%m-%d")
                except Exception:
                    base = now
                start_time = base.replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=1)

            # 1) 当天所有读数
            sql_day = f"""
                SELECT collected_at, remain
                FROM electricity_balance
                WHERE collected_at >= %s AND collected_at < %s {where_clause}
                ORDER BY collected_at
            """
            cursor.execute(sql_day, tuple([start_time, end_time] + params))
            rows = cursor.fetchall()

            # 2) start_time 之前最近一条读数（用于 0 点的用电计算）
            sql_prev = f"""
                SELECT collected_at, remain
                FROM electricity_balance
                WHERE collected_at < %s {where_clause}
                ORDER BY collected_at DESC
                LIMIT 1
            """
            cursor.execute(sql_prev, tuple([start_time] + params))
            prev_row = cursor.fetchone()
            prev_remain = float(prev_row['remain']) if prev_row and prev_row['remain'] is not None else None

            # 取每小时余额：00点取第一条，其他小时取最后一条
            last_by_hour = {}
            first_by_hour = {}
            for r in rows:
                if r['remain'] is None:
                    continue
                h = r['collected_at'].hour
                # 记录每小时的最后一条
                last_by_hour[h] = float(r['remain'])
                # 记录每小时的第一条（只在第一次遇到时记录）
                if h not in first_by_hour:
                    first_by_hour[h] = float(r['remain'])

            # labels / balances（00点到23点）
            for h in range(24):
                labels.append(f"{h:02d}点")
                # 00点使用第一条余额，其他小时使用最后一条余额
                if h == 0:
                    balances.append(first_by_hour.get(h, None))
                else:
                    balances.append(last_by_hour.get(h, None))

            # 计算每小时用电：hour0 用 prev_remain - hour0_first，其他小时用 prev_hour_last - curr_hour_last
            for h in range(24):
                if h == 0:
                    # 00点用电 = 前一天最后余额 - 00点第一条余额
                    first_val_00 = first_by_hour.get(0, None)
                    if prev_remain is not None and first_val_00 is not None:
                        usage.append(max(prev_remain - first_val_00, 0))
                    else:
                        usage.append(0)
                else:
                    # 其他小时用电 = 上小时最后余额 - 当前小时最后余额
                    if h == 1:
                        # 01点特殊处理：上小时是00点，需要用00点的最后一条余额
                        prev_last = last_by_hour.get(0, None)
                    else:
                        prev_last = last_by_hour.get(h - 1, None)
                    curr_last = last_by_hour.get(h, None)
                    if prev_last is not None and curr_last is not None:
                        usage.append(max(prev_last - curr_last, 0))
                    else:
                        usage.append(0)

        else:
            # week / month
            days = 7 if period == "week" else 30
            start_time = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)

            sql_range = f"""
                SELECT collected_at, remain
                FROM electricity_balance
                WHERE collected_at >= %s AND collected_at <= %s {where_clause}
                ORDER BY collected_at
            """
            cursor.execute(sql_range, tuple([start_time, end_time] + params))
            rows = cursor.fetchall()

            # 取得 start_time 之前最近一条记录，用于把跨午夜的下降计入首日
            sql_prev = f"""
                SELECT collected_at, remain
                FROM electricity_balance
                WHERE collected_at < %s {where_clause}
                ORDER BY collected_at DESC
                LIMIT 1
            """
            cursor.execute(sql_prev, tuple([start_time] + params))
            prev_row = cursor.fetchone()
            prev_remain = float(prev_row['remain']) if prev_row and prev_row['remain'] is not None else None

            # 遍历计算当日最后余额与当日内部下降量累加
            last_by_day = {}
            usage_by_day = {}
            prev_ts = None
            prev_remain_iter = None
            prev_day = None
            for r in rows:
                ts = r['collected_at']
                rem = float(r['remain']) if r['remain'] is not None else None
                if rem is None:
                    continue
                day_key = str(ts.date())
                # 更新当日最后余额
                last_by_day[day_key] = rem
                # 计算当日内部下降（只在同一天的连续两条读数之间计算）
                if prev_ts is not None:
                    cur_day = day_key
                    if prev_day == cur_day and prev_remain_iter is not None:
                        drop = prev_remain_iter - rem
                        if drop > 0:
                            usage_by_day[cur_day] = usage_by_day.get(cur_day, 0.0) + drop
                prev_ts = ts
                prev_remain_iter = rem
                prev_day = day_key

            # 把 start_time 之前的最近一条记录和当天第一条读数之间的下降计入首日（避免漏算跨午夜下降）
            if prev_remain is not None and rows:
                first_row = rows[0]
                first_day = str(first_row['collected_at'].date())
                first_rem = float(first_row['remain']) if first_row['remain'] is not None else None
                if first_rem is not None and prev_remain > first_rem:
                    usage_by_day[first_day] = usage_by_day.get(first_day, 0.0) + (prev_remain - first_rem)

            # 构建连续日期序列并填充
            cur_date = start_time.date()
            end_date = now.date()
            ordered_days = []
            while cur_date <= end_date:
                ordered_days.append(str(cur_date))
                cur_date = cur_date + timedelta(days=1)

            for d in ordered_days:
                labels.append(d)
                balances.append(last_by_day.get(d, None))
                usage.append(float(usage_by_day.get(d, 0.0)))

        return labels, balances, usage
    finally:
        cursor.close()
        conn.close()


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
    target_date = request.args.get("date")
    labels, balances, usage = get_statistics(period, device_id, target_date)
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
    interval_seconds = int(os.getenv("FETCH_INTERVAL_SECONDS", "300"))
    scheduler.add_job(scheduled_fetch, 'interval', seconds=interval_seconds, id='fetch_job', max_instances=1, coalesce=True)
    # 首次启动时，立即触发一次抓取，避免页面空白
    scheduler.add_job(scheduled_fetch, 'date', run_date=datetime.now() + timedelta(seconds=1), id='bootstrap_fetch', misfire_grace_time=60, coalesce=True)
    scheduler.start()
    try:
        app.run(host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "false").lower()=="true")
    finally:
        scheduler.shutdown(wait=False)
