from flask import Flask, render_template_string, request, jsonify
import requests
import re
import pymysql
from datetime import datetime, timedelta
import threading
import time

# -----------------------
# 配置区域
# -----------------------
DB_CONFIG = {
    "host": "111.119.253.196",
    "port": 8806,
    "user": "root",
    "password": "123456",
    "database": "dev",
    "charset": "utf8mb4"
}

DEVICE_LIST = [
    {"id": "19101109825", "name": "设备19101109825"},
    {"id": "19104791678", "name": "设备19104791678"},
]

# -----------------------
# Flask App
# -----------------------
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>电表统计柱状图</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body{ font-family: Arial, sans-serif; padding:10px; }
canvas{ max-width:100%; height:auto; }
button, select{ margin:5px; padding:5px 10px; font-size:1em; }
</style>
</head>
<body>
<h2>电表统计</h2>

<div>
    <select id="deviceSelect" onchange="loadData(currentPeriod)">
        {% for d in devices %}
        <option value="{{d.id}}">{{d.name}}</option>
        {% endfor %}
    </select>
    <button onclick="loadData('day')">今天</button>
    <button onclick="loadData('week')">近7天</button>
    <button onclick="loadData('month')">近30天</button>
    <button onclick="fetchData()">抓取最新数据</button>
</div>

<h3>余额</h3>
<canvas id="balanceChart"></canvas>

<h3>用电量</h3>
<canvas id="usageChart"></canvas>

<p id="status"></p>

<script>
let balanceChart, usageChart;
let currentPeriod = 'day';

function renderCharts(labels, balances, usage){
    const balanceCtx = document.getElementById('balanceChart').getContext('2d');
    if(balanceChart) balanceChart.destroy();
    balanceChart = new Chart(balanceCtx, {
        type:'bar',
        data:{ labels:labels, datasets:[{
            label:'余额',
            data:balances,
            backgroundColor:'rgba(75,192,192,0.6)',
            borderColor:'rgba(75,192,192,1)',
            borderWidth:1
        }]},
        options:{
            responsive:true,
            plugins:{
                legend:{ display:false },
                tooltip:{ enabled:true },
                datalabels: { display:true, color:'#000', anchor:'end', align:'end' }
            },
            scales:{ y:{ beginAtZero:true } }
        },
        plugins:[ChartDataLabels]
    });

    const usageCtx = document.getElementById('usageChart').getContext('2d');
    if(usageChart) usageChart.destroy();
    usageChart = new Chart(usageCtx,{
        type:'bar',
        data:{ labels:labels, datasets:[{
            label:'用电量',
            data:usage,
            backgroundColor:'rgba(255,99,132,0.6)',
            borderColor:'rgba(255,99,132,1)',
            borderWidth:1
        }]},
        options:{
            responsive:true,
            plugins:{
                legend:{ display:false },
                tooltip:{ enabled:true },
                datalabels: { display:true, color:'#000', anchor:'end', align:'end' }
            },
            scales:{ y:{ beginAtZero:true } }
        },
        plugins:[ChartDataLabels]
    });
}

function loadData(period){
    currentPeriod = period;
    const deviceId = document.getElementById('deviceSelect').value;
    fetch(`/data?period=${period}&device_id=${deviceId}`)
    .then(res=>res.json())
    .then(res=>{
        if(res.labels.length===0) alert('没有数据，请先抓取或等待数据入库');
        renderCharts(res.labels, res.balances, res.usage);
    });
}

function fetchData(){
    const deviceId = document.getElementById('deviceSelect').value;
    document.getElementById('status').innerText='抓取中...';
    fetch(`/fetch?device_id=${deviceId}`)
    .then(res=>res.json())
    .then(res=>{
        document.getElementById('status').innerText=res.message;
        loadData(currentPeriod);
    });
}

// 默认加载今天
document.addEventListener("DOMContentLoaded", ()=>{ loadData('day'); });
</script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels"></script>
</body>
</html>
"""

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
    return {"meter_no": meter_id, "remain": balance, "collected_at": datetime.now()}

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
    now = datetime.now()
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

# -----------------------
# Flask 路由
# -----------------------
@app.route("/")
def index(): 
    return render_template_string(HTML_TEMPLATE, devices=DEVICE_LIST)

@app.route("/data")
def data():
    period = request.args.get("period","day")
    device_id = request.args.get("device_id")
    labels, balances, usage = get_statistics(period, device_id)
    return {"labels":labels, "balances":balances, "usage":usage}

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
def auto_fetch_loop(interval=60):
    while True:
        for device in DEVICE_LIST:
            data = fetch_meter_data(device["id"])
            if data: save_to_db(data)
        time.sleep(interval)

if __name__=="__main__":
    threading.Thread(target=auto_fetch_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=True)
