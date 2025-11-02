from flask import Flask, render_template, render_template_string, request, jsonify, g
import json
import os
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import requests
import re
import pymysql
from datetime import datetime, timedelta, timezone
import threading
import time
from functools import lru_cache
from html import unescape

load_dotenv()

# -----------------------
# 配置区域
# -----------------------
def _require_env(key, *, cast=None, allow_empty=False, default=None):
    """读取环境变量并执行必要的格式校验"""
    value = os.getenv(key)
    if value is None or (not allow_empty and value == ""):
        if default is not None:
            value = default
        else:
            raise RuntimeError(f"Missing required environment variable: {key}")
    if cast:
        try:
            return cast(value)
        except ValueError as exc:
            raise RuntimeError(f"Invalid value for {key}: {value}") from exc
    return value


def _load_device_list():
    """
    从环境变量加载设备配置。
    支持两种模式：
      1. DEVICES_JSON：JSON 数组，每个对象可包含 server_chan_key 或 server_chan_key_env 字段
      2. DEFAULT_DEVICE_ID / DEFAULT_DEVICE_NAME / DEFAULT_DEVICE_SERVER_CHAN_KEY：兼容旧配置
    """
    devices_json = os.getenv("DEVICES_JSON")
    devices = []

    if devices_json:
        try:
            raw_devices = json.loads(devices_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("DEVICES_JSON must be valid JSON array") from exc

        if not isinstance(raw_devices, list):
            raise RuntimeError("DEVICES_JSON must decode to a JSON array")

        for item in raw_devices:
            if not isinstance(item, dict):
                continue
            device_id = item.get("id")
            if not device_id:
                continue

            device_name = item.get("name") or str(device_id)
            key_env = item.get("server_chan_key_env")
            server_key = ""
            if key_env:
                server_key = os.getenv(key_env, "")
            else:
                server_key = item.get("server_chan_key", "") or ""

            devices.append({
                "id": str(device_id),
                "name": device_name,
                "server_chan_key": server_key,
            })

    default_device_id = os.getenv("DEFAULT_DEVICE_ID")
    if not devices and default_device_id:
        devices.append({
            "id": default_device_id,
            "name": os.getenv("DEFAULT_DEVICE_NAME", default_device_id),
            "server_chan_key": os.getenv("DEFAULT_DEVICE_SERVER_CHAN_KEY", ""),
        })

    return devices


def _cast_int_env(raw_value):
    """将环境变量字符串转换为 int，支持内联注释"""
    if raw_value is None:
        raise ValueError("环境变量缺少整数值")
    cleaned = raw_value.split("#", 1)[0].strip()
    if not cleaned:
        raise ValueError(f"环境变量值无效：{raw_value!r}")
    return int(cleaned)


DB_CONFIG = {
    "host": _require_env("DB_HOST"),
    "port": _require_env("DB_PORT", cast=_cast_int_env),
    "user": _require_env("DB_USER"),
    "password": _require_env("DB_PASSWORD"),
    "database": _require_env("DB_NAME"),
    "charset": _require_env("DB_CHARSET"),
    "autocommit": True,
    "connect_timeout": _cast_int_env(os.getenv("DB_CONNECT_TIMEOUT", "5")),
    "read_timeout": _cast_int_env(os.getenv("DB_READ_TIMEOUT", "10")),
    "write_timeout": _cast_int_env(os.getenv("DB_WRITE_TIMEOUT", "10")),
}

DEVICE_LIST = _load_device_list()

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
# 数据库连接池优化
# -----------------------
def get_db():
    """获取数据库连接，使用Flask的g对象实现连接复用"""
    if 'db_conn' not in g:
        g.db_conn = pymysql.connect(**DB_CONFIG)
    return g.db_conn

@app.teardown_appcontext
def close_db(error):
    """请求结束时关闭数据库连接"""
    db = g.pop('db_conn', None)
    if db is not None:
        db.close()

# -----------------------
# 缓存机制优化
# -----------------------
@lru_cache(maxsize=50)
def get_cached_statistics(period, device_id, target_date, cache_key):
    """缓存统计数据查询结果，cache_key用于缓存过期控制"""
    return get_statistics_raw(period, device_id, target_date)

@lru_cache(maxsize=20)
def get_cached_kpi(device_id, target_date, cache_key):
    """缓存KPI数据查询结果"""
    return get_kpi_raw(device_id, target_date)

def get_cache_key():
    """生成缓存键，5分钟更新一次"""
    return int(time.time() // 300)  # 5分钟缓存周期


def _strip_tags(html_text):
    """基础的 HTML 标签清理，用于宽松匹配文本内容"""
    if not html_text:
        return ""
    return re.sub(r"<[^>]+>", " ", html_text)


def _extract_first_number(text):
    """从文本中提取第一个数字（含小数）"""
    if not text:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text.replace(",", ""))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _parse_meter_page(html_text):
    """解析电表页面 HTML，提取表号与剩余电量"""
    normalized = unescape(html_text or "")
    plain_text = None

    # 先尝试通过 label id 精确匹配
    meter_id_match = re.search(
        r'id=["\']metid["\'][^>]*>([^<]+)', normalized, re.IGNORECASE | re.DOTALL
    )
    meter_id = meter_id_match.group(1).strip() if meter_id_match else None

    # label 匹配可能失败，退回到纯文本匹配
    if not meter_id:
        plain_text = _strip_tags(normalized)
        fallback_match = re.search(
            r"(?:电表号|表号)\s*(?:[:：]|&#58;|&colon;)?\s*([0-9A-Za-z\-]+)",
            plain_text,
        )
        if fallback_match:
            meter_id = fallback_match.group(1).strip()

    # 匹配剩余电量，优先使用 label
    power_match = re.search(
        r"剩余电量(?:[:：]|&#58;|&colon;)?</span>\s*<label[^>]*>([^<]+)</label>",
        normalized,
        re.IGNORECASE | re.DOTALL,
    )
    raw_power = power_match.group(1).strip() if power_match else None

    if raw_power is None:
        if plain_text is None:
            plain_text = _strip_tags(normalized)
        fallback_power = re.search(
            r"剩余电量(?:[:：]|&#58;|&colon;)?[^0-9]*([0-9]+(?:\.[0-9]+)?)",
            plain_text,
        )
        raw_power = fallback_power.group(1) if fallback_power else None

    power = _extract_first_number(raw_power)

    return meter_id, power


def fetch_meter_data(device_id):
    url = f"http://www.wap.cnyiot.com/nat/pay.aspx?mid={device_id}"
    headers={"User-Agent":"Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"
        html_text = resp.text
    except Exception as exc:
        app.logger.warning("抓取设备 %s 页面失败: %s", device_id, exc)
        return None

    meter_id, power = _parse_meter_page(html_text)

    if not meter_id or power is None:
        app.logger.warning(
            "设备 %s 抓取成功但无法解析数据（meter_id=%s, remain=%s）",
            device_id,
            meter_id,
            power,
        )
        return None

    return {"meter_no": meter_id, "remain": power, "collected_at": now_cn()}

def save_to_db(data):
    conn = pymysql.connect(**DB_CONFIG)
    sql = "INSERT INTO electricity_balance (meter_no, remain, collected_at) VALUES (%s,%s,%s)"
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (data["meter_no"], data["remain"], data["collected_at"]))
    finally:
        conn.close()

# -----------------------
# 数据统计（原始版本，供缓存调用）
# -----------------------
def get_statistics_raw(period="day", device_id=None, target_date=None):
    """原始统计数据查询函数，使用连接池"""
    conn = get_db()
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

            # 使用统一的每日用电计算方法（带充值处理）
            if device_id:
                daily_usage = _calculate_daily_usage_with_recharge(conn, device_id, start_time)
            else:
                daily_usage = 0.0

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

            # 使用改进的每小时用电计算逻辑，处理充值情况
            hourly_usage = _calculate_hourly_usage_with_recharge(rows, prev_remain)
            for h in range(24):
                usage.append(hourly_usage.get(h, 0.0))

        else:
            # week / month 使用改进的算法
            days = 7 if period == "week" else 30
            start_time = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = now.replace(hour=23, minute=59, second=59, microsecond=999999)

            # 使用逐日计算的方法，确保充值处理的一致性
            last_by_day = {}
            usage_by_day = {}
            
            # 构建连续日期序列
            cur_date = start_time.date()
            end_date = now.date()
            ordered_days = []
            while cur_date <= end_date:
                ordered_days.append(str(cur_date))
                cur_date = cur_date + timedelta(days=1)
            
            # 为每一天计算用电量
            if device_id:
                for day_str in ordered_days:
                    day_date = datetime.strptime(day_str, "%Y-%m-%d")
                    # 获取当日最后余额
                    last_balance = _get_last_balance_for_date(conn, device_id, day_date)
                    if last_balance is not None:
                        last_by_day[day_str] = last_balance
                    
                    # 计算当日真实用电量（处理充值）
                    daily_usage = _calculate_daily_usage_with_recharge(conn, device_id, day_date)
                    usage_by_day[day_str] = daily_usage

            for d in ordered_days:
                labels.append(d)
                balances.append(last_by_day.get(d, None))
                usage.append(float(usage_by_day.get(d, 0.0)))

        return labels, balances, usage
    finally:
        cursor.close()

# 统计数据接口（使用缓存）
def get_statistics(period="day", device_id=None, target_date=None):
    """缓存版本的统计数据接口"""
    cache_key = get_cache_key()
    return get_cached_statistics(period, device_id, target_date, cache_key)


def _compute_total_usage(conn, device_id, start_time, end_time):
    cursor = conn.cursor()
    try:
        sql = "SELECT collected_at, remain FROM electricity_balance WHERE meter_no=%s AND collected_at >= %s AND collected_at < %s ORDER BY collected_at"
        cursor.execute(sql, (device_id, start_time, end_time))
        total = 0.0
        prev = None
        for _, rem in cursor.fetchall():
            try:
                rem_f = float(rem)
            except Exception:
                continue
            if prev is not None:
                # 只计算余额下降，避免充值被算作负用电
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

def _calculate_hourly_usage_with_recharge(rows, prev_remain):
    """计算每小时用电量，正确处理充值情况"""
    hourly_usage = {}
    
    # 按小时分组数据
    hourly_data = {}
    for r in rows:
        if r['remain'] is None:
            continue
        h = r['collected_at'].hour
        if h not in hourly_data:
            hourly_data[h] = []
        hourly_data[h].append({
            'time': r['collected_at'],
            'remain': float(r['remain'])
        })
    
    # 对每小时的数据按时间排序
    for h in hourly_data:
        hourly_data[h].sort(key=lambda x: x['time'])
    
    # 计算每小时用电量
    for h in range(24):
        if h == 0:
            # 00点：从前一天最后余额开始计算
            if prev_remain is not None and h in hourly_data:
                usage = _calculate_period_usage_with_recharge(hourly_data[h], prev_remain)
                hourly_usage[h] = usage
            else:
                hourly_usage[h] = 0.0
        else:
            # 其他小时：从上一小时的最后余额开始计算
            prev_hour = h - 1
            if prev_hour in hourly_data and h in hourly_data:
                # 上一小时的最后余额作为起始点
                prev_hour_last = hourly_data[prev_hour][-1]['remain']
                usage = _calculate_period_usage_with_recharge(hourly_data[h], prev_hour_last)
                hourly_usage[h] = usage
            else:
                hourly_usage[h] = 0.0
    
    return hourly_usage

def _calculate_period_usage_with_recharge(period_data, start_balance):
    """计算某个时间段内的用电量，处理充值情况"""
    if not period_data or start_balance is None:
        return 0.0
    
    total_usage = 0.0
    last_balance = start_balance
    
    for data_point in period_data:
        current_balance = data_point['remain']
        
        # 如果余额增加，说明充值了
        if current_balance > last_balance:
            # 充值：更新基准为充值后的余额，但不计算"用电"
            last_balance = current_balance
        else:
            # 正常用电：累加消耗
            usage = last_balance - current_balance
            if usage > 0:
                total_usage += usage
            last_balance = current_balance
    
    return total_usage

def _calculate_daily_usage_with_recharge(conn, device_id, target_date):
    """计算指定日期的真实用电量，处理充值情况"""
    cursor = conn.cursor()
    try:
        start_time = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(days=1)
        
        # 获取当天所有读数
        sql = """
            SELECT collected_at, remain
            FROM electricity_balance
            WHERE meter_no=%s AND collected_at >= %s AND collected_at < %s
            ORDER BY collected_at
        """
        cursor.execute(sql, (device_id, start_time, end_time))
        today_records = cursor.fetchall()
        
        if not today_records:
            return 0.0
            
        # 获取昨天最后一条读数作为起始点
        prev_sql = """
            SELECT remain FROM electricity_balance
            WHERE meter_no=%s AND collected_at < %s
            ORDER BY collected_at DESC LIMIT 1
        """
        cursor.execute(prev_sql, (device_id, start_time))
        
        prev_row = cursor.fetchone()
        prev_balance = float(prev_row[0]) if prev_row else None
        
        total_usage = 0.0
        last_balance = prev_balance
        
        for _, remain in today_records:
            current_balance = float(remain) if remain is not None else None
            if current_balance is None:
                continue
                
            if last_balance is None:
                last_balance = current_balance
                continue
                
            # 如果余额增加，说明充值了
            if current_balance > last_balance:
                # 充值：更新基准为充值后的余额，但不计算"用电"
                last_balance = current_balance
            else:
                # 正常用电：累加消耗
                usage = last_balance - current_balance
                if usage > 0:
                    total_usage += usage
                last_balance = current_balance
            
        return total_usage
    finally:
        cursor.close()

# -----------------------
# Server酱微信通知功能
# -----------------------
def send_server_chan_notification(send_key, title, desp=""):
    """使用Server酱发送微信通知"""
    if not send_key:
        return {"success": False, "message": "SendKey未配置"}
        
    url = f"https://sctapi.ftqq.com/{send_key}.send"
    data = {
        "title": title,
        "desp": desp
    }
    
    try:
        response = requests.post(url, data=data, timeout=10, verify=False)
        result = response.json()
        
        if result.get("code") == 0:
            return {"success": True, "message": "发送成功"}
        else:
            return {"success": False, "message": f"发送失败: {result.get('message', '未知错误')}"}
            
    except Exception as e:
        return {"success": False, "message": f"发送异常: {str(e)}"}

def get_yesterday_report(device_id, device_name):
    """获取昨日用电报告"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        yesterday = (now_cn() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 获取昨日用电量
        yesterday_usage = _calculate_daily_usage_with_recharge(conn, device_id, yesterday)
        
        # 获取昨日结束时的余额
        yesterday_last_balance = _get_last_balance_for_date(conn, device_id, yesterday)
        
        # 获取前天结束时的余额
        day_before_yesterday = yesterday - timedelta(days=1)
        day_before_last_balance = _get_last_balance_for_date(conn, device_id, day_before_yesterday)
        
        conn.close()
        
        return {
            "device_name": device_name,
            "date": yesterday.strftime("%Y年%m月%d日"),
            "usage": round(yesterday_usage, 2) if yesterday_usage else 0,
            "balance_start": round(day_before_last_balance, 2) if day_before_last_balance else "无数据",
            "balance_end": round(yesterday_last_balance, 2) if yesterday_last_balance else "无数据"
        }
        
    except Exception as e:
        return {
            "device_name": device_name,
            "date": "昨日",
            "usage": "获取失败",
            "balance_start": "获取失败", 
            "balance_end": "获取失败",
            "error": str(e)
        }

def send_daily_reports():
    """发送每日用电报告"""
    print(f"[{now_cn().strftime('%Y-%m-%d %H:%M:%S')}] 开始发送每日用电报告...")
    
    for device in DEVICE_LIST:
        device_id = device["id"]
        device_name = device["name"]
        send_key = device.get("server_chan_key")
        
        if not send_key:
            print(f"设备 {device_name} 未配置Server酱SendKey，跳过")
            continue
            
        # 获取昨日报告
        report = get_yesterday_report(device_id, device_name)
        
        # 构造通知内容
        title = f" 昨日用电: {report['usage']} 度"
        
        if "error" in report:
            desp = f"""
            ## 📊 用电报告
            **设备名称：** {report['device_name']}  
            **日期：** {report['date']}  
            **状态：** 数据获取失败  
            **错误：** {report['error']}

        ---
        *电表监控系统自动发送*
        """
        else:
            # 用电量判断
            usage = report['usage']
            if isinstance(usage, (int, float)):
                if usage > 10:
                    usage_icon = "🔥"
                    usage_desc = "用电较多"
                elif usage > 5:
                    usage_icon = "⚡"
                    usage_desc = "正常用电"
                elif usage > 0:
                    usage_icon = "💡"
                    usage_desc = "用电较少"
                else:
                    usage_icon = "💤"
                    usage_desc = "几乎无用电"
            else:
                usage_icon = "❓"
                usage_desc = "数据异常"
                
            desp = f"""
## 📊 用电报告
**设备名称：** {report['device_name']}  
**日期：** {report['date']}  
**用电量：** {usage_icon} {report['usage']} 度 ({usage_desc})  
**期初余额：** {report['balance_start']} 度  
**期末余额：** {report['balance_end']} 度  

## 📈 用电分析
- 昨日消耗了 **{report['usage']}** 度电
- 剩余电量 **{report['balance_end']}** 度

---
*电表监控系统每日9点自动发送*
"""
        
        # 发送通知
        result = send_server_chan_notification(send_key, title, desp)
        
        if result["success"]:
            print(f"✅ {device_name} 用电报告发送成功")
        else:
            print(f"❌ {device_name} 用电报告发送失败: {result['message']}")

@app.route("/kpi")
def kpi():
    device_id = request.args.get("device_id")
    target_date = request.args.get("date")  # 新增：支持查询历史日期的KPI
    
    if not device_id:
        device_id = DEVICE_LIST[0]["id"] if DEVICE_LIST else None
    
    conn = pymysql.connect(**DB_CONFIG)
    try:
        now = now_cn()
        
        # 如果指定了日期，使用指定日期；否则使用今天
        if target_date:
            try:
                base_date = datetime.strptime(target_date, "%Y-%m-%d")
            except ValueError:
                base_date = now
        else:
            base_date = now
            
        current_balance = _get_latest_balance(conn, device_id) if device_id else None
        
        # 计算目标日期和前一天
        yesterday = base_date - timedelta(days=1)
        day_before = base_date - timedelta(days=2)
        
        # 获取各日期的最后余额
        base_last = _get_last_balance_for_date(conn, device_id, base_date) if device_id else None
        y_last = _get_last_balance_for_date(conn, device_id, yesterday) if device_id else None
        db_last = _get_last_balance_for_date(conn, device_id, day_before) if device_id else None
        
        # 使用新的算法计算真实用电量（处理充值）
        usage_target = _calculate_daily_usage_with_recharge(conn, device_id, base_date) if device_id else None
        usage_yesterday = _calculate_daily_usage_with_recharge(conn, device_id, yesterday) if device_id else None
        
        # 充值检测：只在查询今日时计算
        recharge_today = None
        if target_date is None or target_date == now.strftime("%Y-%m-%d"):
            # 查询今日：计算充值
            if current_balance is not None and y_last is not None:
                recharge_today = max(current_balance - y_last + (usage_target or 0), 0.0)

        return {
            "current_balance": current_balance,
            "target_date_last_balance": base_last,  # 目标日期最后余额
            "yesterday_last_balance": y_last,
            "day_before_yesterday_last_balance": db_last,
            "usage_target": usage_target,  # 目标日期用电量
            "usage_yesterday": usage_yesterday,
            "recharge_today": recharge_today,
            # 保持向后兼容
            "usage_today": usage_target,
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

@app.route("/recharge_history")
def recharge_history():
    """获取充值历史记录"""
    device_id = request.args.get("device_id")
    days = int(request.args.get("days", "30"))  # 默认查询30天
    limit = int(request.args.get("limit", "50"))  # 默认返回50条记录
    
    if not device_id:
        device_id = DEVICE_LIST[0]["id"] if DEVICE_LIST else None
    
    if not device_id:
        return {"recharges": [], "message": "没有可用的设备"}
    
    conn = get_db()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        now = now_cn()
        start_time = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 查询指定时间范围内的所有余额记录
        sql = """
            SELECT collected_at, remain
            FROM electricity_balance
            WHERE meter_no=%s AND collected_at >= %s
            ORDER BY collected_at ASC
        """
        cursor.execute(sql, (device_id, start_time))
        records = cursor.fetchall()
        
        if not records:
            return {"recharges": [], "message": "暂无充值记录"}
        
        recharges = []
        prev_record = None
        
        for record in records:
            current_time = record['collected_at']
            current_remain = float(record['remain']) if record['remain'] is not None else None
            
            if current_remain is None:
                continue
                
            if prev_record is not None:
                prev_remain = float(prev_record['remain']) if prev_record['remain'] is not None else None
                
                if prev_remain is not None and current_remain > prev_remain:
                    # 检测到可能的充值
                    balance_increase = current_remain - prev_remain
                    
                    # 充值验证：余额增加≥8元时，四舍五入到最近的10的整数倍
                    if balance_increase >= 8:
                        # 四舍五入到最近的10的整数倍
                        estimated_recharge = round(balance_increase / 10) * 10
                        
                        # 确保估算的充值金额与实际增加值的差异不超过5元，且≥10元
                        if estimated_recharge >= 10 and abs(estimated_recharge - balance_increase) <= 5:
                            recharges.append({
                                "recharge_time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                                "recharge_date": current_time.strftime("%Y-%m-%d"),
                                "recharge_amount": int(estimated_recharge),  # 估算的充值金额
                                "balance_before": round(prev_remain, 2),
                                "balance_after": round(current_remain, 2),
                                "device_id": device_id
                            })
            
            prev_record = record
        
        # 按时间倒序排列，最新的充值在前
        recharges.reverse()
        
        # 限制返回数量
        if limit > 0:
            recharges = recharges[:limit]
        
        return {
            "recharges": recharges,
            "total_count": len(recharges),
            "query_days": days,
            "device_id": device_id
        }
        
    finally:
        cursor.close()

@app.route("/fetch")
def fetch():
    device_id = request.args.get("device_id")
    if not device_id and DEVICE_LIST:
        device_id = DEVICE_LIST[0]["id"]
    if not device_id:
        return {"message": "❌ 抓取失败：未配置可用设备"}

    data = fetch_meter_data(device_id)
    if data:
        save_to_db(data)
        return {"message":f"✅ 抓取成功：{data}"}
    return {"message":"❌ 抓取失败"}

@app.route("/test_notification")
def test_notification():
    """测试通知功能"""
    device_id = request.args.get("device_id")
    
    # 如果未指定设备，使用第一个设备
    if not device_id:
        if DEVICE_LIST:
            device = DEVICE_LIST[0]
        else:
            return {"success": False, "message": "没有可用的设备"}
    else:
        device = next((d for d in DEVICE_LIST if d["id"] == device_id), None)
        if not device:
            return {"success": False, "message": f"设备 {device_id} 未找到"}
    
    device_id = device["id"]
    device_name = device["name"]
    send_key = device.get("server_chan_key")
    
    if not send_key:
        return {"success": False, "message": f"设备 {device_name} 未配置Server酱SendKey"}
    
    # 获取昨日报告
    report = get_yesterday_report(device_id, device_name)
    
    # 构造测试通知内容
    title = f"🧪 昨日用电：{report['usage']} 度"
    desp = f"""
## 📊 测试报告
**设备名称：** {report['device_name']}  
**日期：** {report['date']}  
**用电量：** {report['usage']} 度  
**期初余额：** {report['balance_start']} 度  
**期末余额：** {report['balance_end']} 度  

## ✅ 测试状态
- 通知功能正常
- 数据获取成功

---
*这是一条测试消息*
"""
    
    # 发送通知
    result = send_server_chan_notification(send_key, title, desp)
    
    return {
        "success": result["success"],
        "message": result["message"],
        "device_name": device_name,
        "report": report
    }

# -----------------------
# 后台定时抓取
# -----------------------
def scheduled_fetch():
    for device in DEVICE_LIST:
        data = fetch_meter_data(device["id"])
        if data: save_to_db(data)

if __name__=="__main__":
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    interval_seconds = _require_env("FETCH_INTERVAL_SECONDS", cast=_cast_int_env, default="300")
    
    # 数据抓取任务
    scheduler.add_job(scheduled_fetch, 'interval', seconds=interval_seconds, id='fetch_job', max_instances=1, coalesce=True)
    
    # 每日9点发送用电报告
    scheduler.add_job(send_daily_reports, 'cron', hour=9, minute=0, id='daily_report_job', max_instances=1, coalesce=True)
    
    # 首次启动时，立即触发一次抓取，避免页面空白
    scheduler.add_job(scheduled_fetch, 'date', run_date=datetime.now() + timedelta(seconds=1), id='bootstrap_fetch', misfire_grace_time=60, coalesce=True)
    
    scheduler.start()
    
    print(f"[{now_cn().strftime('%Y-%m-%d %H:%M:%S')}] 电表监控系统启动完成")
    print(f"- 数据抓取间隔：{interval_seconds}秒")
    print(f"- 每日报告时间：每天上午9:00")
    print(f"- 配置的设备数量：{len(DEVICE_LIST)}")
    
    try:
        port_env = os.getenv("PORT")
        port = _cast_int_env(port_env) if port_env else 5000
        app.run(host=os.getenv("HOST", "0.0.0.0"), port=port, debug=os.getenv("FLASK_DEBUG", "false").lower()=="true")
    finally:
        scheduler.shutdown(wait=False)
