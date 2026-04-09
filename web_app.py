# -*- coding: utf-8 -*-
"""
价值投资之王 - 智能选股可视化网站 v14-DEBT-RATIO-FIXED
Flask后端 + 精美前端 + 新闻热点板块 + 资金流向 + 股票详情
v13改进: 每日推荐栏目化，定时自动选股（9:26/14:30），保留早晚结果

DEBT_RATIO_FIX_V3: Added debt_ratio to all data flows
"""
import requests
import json
import time
import sys
import io
import os
import hashlib
import threading
import atexit
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_from_directory
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# 禁用SSL警告（离线模式）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ========== 每日推荐数据存储 ==========
# 存储结构: {"morning": {...}, "afternoon": {...}, "last_update": "..."}
DAILY_PICK_DATA = {
    "morning": None,      # 早盘选股结果
    "afternoon": None,    # 午盘选股结果
    "last_update": None,  # 最后更新时间
}
DAILY_PICK_LOCK = threading.Lock()
DAILY_PICK_FILE = os.path.join(os.path.dirname(__file__), 'daily_pick_cache.json')

# 创建全局session，禁用SSL验证和代理 —— 关键！所有HTTPS请求必须通过此session
session = requests.Session()
session.verify = False
session.trust_env = False  # 禁用环境代理（解决代理服务未运行导致的连接失败）
retry_strategy = Retry(total=2, backoff_factor=1)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("https://", adapter)
session.mount("http://", adapter)

# 通用请求头
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://quote.eastmoney.com/'
}
DC_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://data.eastmoney.com/'
}

# Windows控制台编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

app = Flask(__name__, static_folder='static', template_folder='templates')

# ========== 每日推荐缓存管理 ==========

def load_daily_pick_cache():
    """从文件加载每日推荐缓存"""
    global DAILY_PICK_DATA
    try:
        if os.path.exists(DAILY_PICK_FILE):
            with open(DAILY_PICK_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 检查是否是今天的数据
                if data.get('date') == datetime.now().strftime('%Y-%m-%d'):
                    DAILY_PICK_DATA = data
                    print(f"✓ 加载今日选股缓存: 早上 {bool(data.get('morning'))}, 下午 {bool(data.get('afternoon'))}")
                    return
                else:
                    print("⚠️ 缓存日期不是今天，将重新选股")
    except Exception as e:
        print(f"加载缓存失败: {e}")
    # 重置为今天的空数据
    DAILY_PICK_DATA = {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "morning": None,
        "afternoon": None,
        "last_update": None,
    }

def save_daily_pick_cache():
    """保存每日推荐缓存到文件"""
    try:
        with open(DAILY_PICK_FILE, 'w', encoding='utf-8') as f:
            json.dump(DAILY_PICK_DATA, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存缓存失败: {e}")

def execute_daily_pick(session_type):
    """执行选股并存储结果

    session_type: 'morning' 或 'afternoon'
    """
    global DAILY_PICK_DATA
    print(f"\n{'='*50}")
    print(f"🕐 开始执行{('早盘' if session_type == 'morning' else '午盘')}选股...")
    print(f"{'='*50}")

    try:
        results = run_picker()
        if results:
            total = results[0].get('_total_scanned', 0) if results else 0
            for r in results:
                r.pop('_total_scanned', None)

            # 过滤新股
            filtered = [r for r in results if not r.get('name','').startswith('N') and '退' not in r.get('name','') and r.get('change_pct',0) <= 100]
            top10 = sorted(filtered, key=lambda x: x['score'], reverse=True)[:10]

            with DAILY_PICK_LOCK:
                DAILY_PICK_DATA[session_type] = {
                    "results": top10,
                    "total_scanned": total,
                    "pick_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "session_type": "早盘选股" if session_type == 'morning' else "午盘选股",
                }
                DAILY_PICK_DATA['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                DAILY_PICK_DATA['date'] = datetime.now().strftime('%Y-%m-%d')
                save_daily_pick_cache()

            print(f"✓ {('早盘' if session_type == 'morning' else '午盘')}选股完成: {len(top10)} 只股票")
        else:
            print(f"✗ 选股失败，无结果")
    except Exception as e:
        print(f"✗ 选股执行失败: {e}")

def schedule_daily_pick():
    """定时任务：每天9:26和14:30执行选股"""
    global DAILY_PICK_DATA
    while True:
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')

        # 检查是否需要重置（新的一天）
        with DAILY_PICK_LOCK:
            if DAILY_PICK_DATA.get('date') != today:
                DAILY_PICK_DATA = {
                    "date": today,
                    "morning": None,
                    "afternoon": None,
                    "last_update": None,
                }
                print(f"📅 新的一天: {today}")

        current_time = now.strftime("%H:%M")

        # 早盘选股: 9:26
        if current_time == "09:26":
            with DAILY_PICK_LOCK:
                if not DAILY_PICK_DATA.get('morning'):
                    # 在新线程中执行，避免阻塞
                    threading.Thread(target=execute_daily_pick, args=('morning',), daemon=True).start()

        # 午盘选股: 14:30
        elif current_time == "14:30":
            with DAILY_PICK_LOCK:
                if not DAILY_PICK_DATA.get('afternoon'):
                    threading.Thread(target=execute_daily_pick, args=('afternoon',), daemon=True).start()

        # 每分钟检查一次
        time.sleep(60)

def start_scheduler():
    """启动定时任务线程"""
    scheduler_thread = threading.Thread(target=schedule_daily_pick, daemon=True)
    scheduler_thread.start()
    print("✓ 定时选股任务已启动 (9:26 早盘, 14:30 午盘)")
    return scheduler_thread

# ========== 数据模块（复用smart_stock_picker逻辑）==========

def get_realtime_quotes():
    """获取实时行情数据 - 全市场扫描
    
    2026-04-02: push2/push2his clist/get 全被封禁。
    新方案：datacenter-web 获取财务筛选股票 + 腾讯qt.gtimg.cn批量获取实时行情
    """
    all_stocks = []
    dc_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://data.eastmoney.com/'
    }

    try:
        # === 第1步：从datacenter-web获取有财务数据的股票列表 ===
        print("  从财务数据中心获取股票列表...")
        candidate_stocks = {}  # code -> {name, roe, gross_margin, rev_growth, profit_growth}
        
        # 2026-04-02修复: 必须用REPORT_DATE_NAME筛选年报, 否则API返回季报年化ROE(100-200%)
        latest_report = None
        current_year = datetime.now().year
        for yr in range(current_year, current_year - 2, -1):
            try:
                test_params = {
                    'reportName': 'RPT_F10_FINANCE_MAINFINADATA',
                    'columns': 'REPORT_DATE_NAME',
                    'filter': '(REPORT_DATE_NAME="' + str(yr) + '年报")',
                    'pageNumber': 1, 'pageSize': 1,
                    'source': 'WEB', 'client': 'WEB',
                }
                tr = session.get('https://datacenter-web.eastmoney.com/api/data/v1/get',
                                  params=test_params, headers=DC_HEADERS, timeout=10)
                td = tr.json()
                if td.get('success') and td.get('result') and td['result'].get('count', 0) > 0:
                    latest_report = str(yr) + '年报'
                    print(f"  使用最新年报: {latest_report}")
                    break
            except:
                continue
        if not latest_report:
            latest_report = str(current_year - 1) + '年报'
            print(f"  默认使用年报: {latest_report}")

        # 从MAINFINADATA获取年报ROE+毛利率（按ROE排序取前3000）
        report_filter = '(REPORT_DATE_NAME="' + latest_report + '")'
        for sort_col, extra_filter, sort_dir in [
            ('ROEJQ', '(ROEJQ>5)(ROEJQ<80)', '-1'),
            ('ROEJQ', '(ROEJQ>10)(ROEJQ<80)', '-1'),
        ]:
            try:
                params = {
                    'reportName': 'RPT_F10_FINANCE_MAINFINADATA',
                    'columns': 'SECURITY_CODE,SECURITY_NAME_ABBR,ROEJQ,XSMLL,ZCFZL,XSJLL',  # ROE, 毛利率, 资产负债率, 净利率
                    'filter': report_filter + extra_filter,
                    'pageNumber': 1, 'pageSize': 3000,
                    'source': 'WEB', 'client': 'WEB',
                    'sortColumns': sort_col,
                    'sortTypes': sort_dir
                }
                resp = session.get('https://datacenter-web.eastmoney.com/api/data/v1/get',
                                    params=params, headers=DC_HEADERS, timeout=15)
                d = resp.json()
                if d.get('success') and d.get('result') and d['result'].get('data'):
                    for item in d['result']['data']:
                        code = item.get('SECURITY_CODE', '')
                        name = item.get('SECURITY_NAME_ABBR', '')
                        if not code or not name or len(code) != 6:
                            continue
                        if 'ST' in name or '*' in name:
                            continue
                        # 排除北交所(8/4开头)、B股(900/200开头)、A股重复(A2开头)
                        if code.startswith('8') or code.startswith('4') or code.startswith('920'):
                            continue
                        if code.startswith('900') or code.startswith('200'):
                            continue
                        if code.startswith('A2'):
                            continue
                        roe = item.get('ROEJQ', 0)
                        gm = item.get('XSMLL', 0)
                        zcfzl = item.get('ZCFZL', 0)  # 资产负债率
                        xsjll = item.get('XSJLL', 0)  # 净利率
                        if code not in candidate_stocks:
                            candidate_stocks[code] = {
                                'name': name, 'roe': 0, 'gross_margin': 0,
                                'rev_growth': 0, 'profit_growth': 0,
                                'debt_ratio': 0, 'net_margin': 0,
                            }
                        if roe is not None:
                            fval = float(roe)
                            if 1 <= fval <= 80 and fval > candidate_stocks[code]['roe']:
                                candidate_stocks[code]['roe'] = fval
                        if gm is not None:
                            fgm = float(gm)
                            if fgm > 0 and fgm > candidate_stocks[code]['gross_margin']:
                                candidate_stocks[code]['gross_margin'] = fgm
                        if zcfzl is not None:
                            fzcfzl = float(zcfzl)
                            if 0 <= fzcfzl <= 100 and fzcfzl > candidate_stocks[code]['debt_ratio']:
                                candidate_stocks[code]['debt_ratio'] = fzcfzl
                        if xsjll is not None:
                            fxsjll = float(xsjll)
                            if fxsjll > 0 and fxsjll > candidate_stocks[code]['net_margin']:
                                candidate_stocks[code]['net_margin'] = fxsjll
            except Exception as e:
                print(f"  获取{sort_col}列表失败: {e}")

        # 补充CPD数据（营收/净利增速）- 用DATAYEAR+DATEMMDD筛选年报
        # CPD不支持REPORT_DATE_NAME, 用(DATAYEAR=xxxx)(DATEMMDD="年报")代替
        current_year_val = current_year
        cpd_report_filter = '(DATAYEAR=' + str(current_year_val) + ')(DATEMMDD="年报")'
        # 验证最新年报是否存在
        try:
            test_p = {
                'reportName': 'RPT_LICO_FN_CPD',
                'columns': 'SECURITY_CODE',
                'filter': cpd_report_filter,
                'pageNumber': 1, 'pageSize': 1,
                'source': 'WEB', 'client': 'WEB',
            }
            tr = session.get('https://datacenter-web.eastmoney.com/api/data/v1/get',
                              params=test_p, headers=DC_HEADERS, timeout=10)
            td = tr.json()
            if not (td.get('success') and td.get('result') and td['result'].get('count', 0) > 0):
                current_year_val -= 1
                cpd_report_filter = '(DATAYEAR=' + str(current_year_val) + ')(DATEMMDD="年报")'
        except:
            current_year_val -= 1
            cpd_report_filter = '(DATAYEAR=' + str(current_year_val) + ')(DATEMMDD="年报")'
        print(f"  CPD年报筛选: {cpd_report_filter}")
        
        for cpd_filter, sort_col in [
            ('(SJLTZ>10)(SJLTZ<5000)', 'SJLTZ'),
            ('(YSTZ>10)(YSTZ<5000)', 'YSTZ'),
        ]:
            try:
                params = {
                    'reportName': 'RPT_LICO_FN_CPD',
                    'columns': 'SECURITY_CODE,SECURITY_NAME_ABBR,YSTZ,SJLTZ',
                    'filter': cpd_report_filter + cpd_filter,
                    'pageNumber': 1, 'pageSize': 3000,
                    'source': 'WEB', 'client': 'WEB',
                    'sortColumns': sort_col, 'sortTypes': '-1'
                }
                resp = session.get('https://datacenter-web.eastmoney.com/api/data/v1/get',
                                    params=params, headers=DC_HEADERS, timeout=15)
                d = resp.json()
                if d.get('success') and d.get('result') and d['result'].get('data'):
                    for item in d['result']['data']:
                        code = item.get('SECURITY_CODE', '')
                        name = item.get('SECURITY_NAME_ABBR', '')
                        if not code or len(code) != 6:
                            continue
                        if not name or 'ST' in name or '*' in name:
                            continue
                        if code.startswith('8') or code.startswith('4') or code.startswith('920'):
                            continue
                        if code.startswith('900') or code.startswith('200'):
                            continue
                        if code.startswith('A2'):
                            continue
                        ystz = item.get('YSTZ', 0)
                        sjltz = item.get('SJLTZ', 0)
                        if code not in candidate_stocks:
                            candidate_stocks[code] = {
                                'name': name, 'roe': 0, 'gross_margin': 0,
                                'rev_growth': 0, 'profit_growth': 0,
                                'debt_ratio': 0, 'net_margin': 0,
                            }
                        if ystz is not None and abs(float(ystz)) <= 1000:
                            candidate_stocks[code]['rev_growth'] = max(candidate_stocks[code]['rev_growth'], float(ystz))
                        if sjltz is not None and abs(float(sjltz)) <= 10000:
                            candidate_stocks[code]['profit_growth'] = max(candidate_stocks[code]['profit_growth'], float(sjltz))
            except Exception as e:
                print(f"  获取CPD {sort_col}失败: {e}")

        print(f"  财务筛选出 {len(candidate_stocks)} 只候选股票")

        # === 第2步：用腾讯API批量获取实时行情（并发加速）===
        # 腾讯API格式: sh600519, sz002594，每批80只
        # 重要: 腾讯API必须用HTTP，不能走HTTPS（SSL证书问题）
        codes = list(candidate_stocks.keys())
        batch_size = 80
        total_batches = (len(codes) + batch_size - 1) // batch_size
        price_data = {}
        
        print(f"  通过腾讯API获取实时行情（{total_batches}批，并发获取）...")
        
        # 定义单批次获取函数
        def fetch_batch(batch_idx):
            batch_codes = codes[batch_idx:batch_idx+batch_size]
            tx_codes = [f"sh{c}" if c.startswith('6') else f"sz{c}" for c in batch_codes]
            batch_result = {}
            try:
                url = 'http://qt.gtimg.cn/q=' + ','.join(tx_codes)
                resp = session.get(url, timeout=10)  # timeout从15降到10
                lines = resp.text.strip().split(';')
                for line in lines:
                    if not line.strip():
                        continue
                    parts = line.split('~')
                    if len(parts) < 50:
                        continue
                    code = parts[2]
                    if not code or len(code) != 6:
                        continue
                    try:
                        price = float(parts[3]) if parts[3] else 0
                    except:
                        price = 0
                    if price <= 0:
                        continue
                    try:
                        change_pct = float(parts[32]) if parts[32] else 0
                    except:
                        change_pct = 0
                    try:
                        pe = float(parts[39]) if parts[39] and parts[39] != '-' else 0
                        if pe > 10000 or pe < 0: pe = 0
                    except:
                        pe = 0
                    try:
                        total_cap_yi = float(parts[44]) if parts[44] else 0
                    except:
                        total_cap_yi = 0
                    try:
                        amount_wan = float(parts[43]) if parts[43] else 0
                    except:
                        amount_wan = 0
                    try:
                        high = float(parts[33]) if parts[33] else 0
                    except:
                        high = 0
                    try:
                        low = float(parts[34]) if parts[34] else 0
                    except:
                        low = 0
                    try:
                        open_p = float(parts[5]) if parts[5] else 0
                    except:
                        open_p = 0
                    try:
                        prev_close = float(parts[4]) if parts[4] else 0
                    except:
                        prev_close = 0
                    try:
                        volume_gu = float(parts[37]) if parts[37] else 0
                    except:
                        volume_gu = 0
                    
                    batch_result[code] = {
                        'name': parts[1], 'price': price, 'change_pct': change_pct,
                        'volume': volume_gu, 'amount': amount_wan * 10000,
                        'market_cap': total_cap_yi * 100000000, 'pe': pe,
                        'high': high, 'low': low, 'open': open_p, 'prev_close': prev_close,
                    }
            except Exception as e:
                print(f"  腾讯API第{batch_idx//batch_size+1}批失败: {e}")
            return batch_result
        
        # 并发获取所有批次（最多10个并发）
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_batch, i) for i in range(0, len(codes), batch_size)]
            for future in as_completed(futures):
                batch_result = future.result()
                price_data.update(batch_result)
        
        elapsed = time.time() - start_time
        print(f"  腾讯API获取到 {len(price_data)} 只实时行情，耗时 {elapsed:.1f}s")

        # === 第3步：合并数据 ===
        for code, fin in candidate_stocks.items():
            if code not in price_data:
                continue
            pd = price_data[code]
            stock = {
                'code': code, 'name': pd['name'] or fin['name'],
                'price': pd['price'], 'change_pct': pd['change_pct'],
                'volume': pd['volume'], 'amount': pd['amount'],
                'high': pd['high'], 'low': pd['low'],
                'open': pd['open'], 'prev_close': pd['prev_close'],
                'pe': pd['pe'], 'pb': 0,
                'roe': fin['roe'], 'gross_margin': fin['gross_margin'],
                'net_margin': fin.get('net_margin', 0), 'debt_ratio': fin.get('debt_ratio', 0),
                'rev_growth': fin['rev_growth'], 'profit_growth': fin['profit_growth'],
                'market_cap': pd['market_cap'],
            }
            all_stocks.append(stock)

        # === 第4步：PB数据简化（跳过慢速补充，用预设数据或估算）===
        # PB不是关键评分指标，优先用预设数据或从PE/ROE估算
        # 不再调用push2 stock/get逐只获取（太慢）
        preset_financials = get_preset_financials()
        for stock in all_stocks:
            code = stock['code']
            if stock.get('pb', 0) == 0:
                # 优先用预设数据
                if code in preset_financials and preset_financials[code].get('pb', 0) > 0:
                    stock['pb'] = preset_financials[code]['pb']
                # 备选：从PE和ROE估算（PB ≈ PE × ROE / 100）
                elif stock.get('pe', 0) > 0 and stock.get('roe', 0) > 0:
                    stock['pb'] = round(stock['pe'] * stock['roe'] / 100, 2)
        
        print(f"  PB数据已补充（预设+估算），完成扫描共 {len(all_stocks)} 只股票")
        return all_stocks

    except Exception as e:
        print(f"获取行情失败: {e}")
        return []

def get_financial_data_fast(code):
    """快速获取财务数据（timeout=3秒，只请求关键字段）

    性能优化版：减少timeout，只请求最关键的字段
    """
    base_url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
    result = {'roe': 0, 'rev_growth': 0, 'profit_growth': 0, 'gross_margin': 0, 'debt_ratio': 0, 'net_margin': 0}

    # 1. MAINFINADATA: 拿ROE + 毛利率 + 资产负债率（最关键的指标）
    try:
        params = {
            'reportName': 'RPT_F10_FINANCE_MAINFINADATA',
            'columns': 'ROEJQ,XSMLL,ZCFZL,XSJLL',  # ROE, 毛利率, 资产负债率, 净利率
            'filter': '(SECURITY_CODE="' + code + '")',
            'pageNumber': 1, 'pageSize': 1,
            'source': 'WEB', 'client': 'WEB',
        }
        resp = session.get(base_url, params=params, headers=DC_HEADERS, timeout=3)
        d = resp.json()
        if d.get('success') and d.get('result') and d['result'].get('data'):
            item = d['result']['data'][0]
            roe_val = item.get('ROEJQ', 0)
            if roe_val is not None:
                result['roe'] = float(roe_val)
            xsml_val = item.get('XSMLL', 0)
            if xsml_val is not None:
                result['gross_margin'] = float(xsml_val)
            zcfzl_val = item.get('ZCFZL', 0)
            if zcfzl_val is not None:
                result['debt_ratio'] = float(zcfzl_val)
            xsjll_val = item.get('XSJLL', 0)
            if xsjll_val is not None:
                result['net_margin'] = float(xsjll_val)
    except:
        pass

    # 2. CPD: 拿营收同比 + 净利同比（仅当ROE有效时才请求，减少无效调用）
    if result['roe'] > 0:
        try:
            params = {
                'reportName': 'RPT_LICO_FN_CPD',
                'columns': 'YSTZ,SJLTZ',  # 只请求关键字段
                'filter': '(SECURITY_CODE="' + code + '")',
                'pageNumber': 1, 'pageSize': 1,
                'source': 'WEB', 'client': 'WEB',
            }
            resp = session.get(base_url, params=params, headers=DC_HEADERS, timeout=3)
            d = resp.json()
            if d.get('success') and d.get('result') and d['result'].get('data'):
                item = d['result']['data'][0]
                ystz = item.get('YSTZ', 0)
                if ystz is not None:
                    result['rev_growth'] = float(ystz)
                sjltz = item.get('SJLTZ', 0)
                if sjltz is not None:
                    result['profit_growth'] = float(sjltz)
        except:
            pass

    # 至少有一个有效数据才返回
    if result['roe'] != 0 or result['gross_margin'] != 0 or result['debt_ratio'] != 0:
        return result
    return None

def get_financial_data(code):
    """从东方财富财务数据中心获取个股关键财务指标（最新报告期）
    
    修复说明(2026-04-01):
    - ROE使用 RPT_F10_FINANCE_MAINFINADATA (ROEJQ字段, 有报告期排序)
    - 营收同比/净利同比使用 RPT_LICO_FN_CPD (YSTZ/SJLTZ字段)
    - 毛利率两个API都有, 优先用MAINFINADATA
    - 两个API都必须请求pageSize=1取最新报告期, 确保数据最新
    """
    base_url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
    result = {'roe': 0, 'rev_growth': 0, 'profit_growth': 0, 'gross_margin': 0, 'debt_ratio': 0, 'net_margin': 0, 'pb': 0}

    # 1. MAINFINADATA: 拿ROE + 毛利率 + 资产负债率 + 净利率 (有报告期排序, 最新数据)
    try:
        params = {
            'reportName': 'RPT_F10_FINANCE_MAINFINADATA',
            'columns': 'REPORT_DATE_NAME,ROEJQ,XSMLL,ZCFZL,XSJLL',  # ROE, 毛利率, 资产负债率, 净利率
            'filter': '(SECURITY_CODE="' + code + '")',
            'pageNumber': 1, 'pageSize': 1,
            'source': 'WEB', 'client': 'WEB',
        }
        resp = session.get(base_url, params=params, headers=DC_HEADERS, timeout=5)
        d = resp.json()
        if d.get('success') and d.get('result') and d['result'].get('data'):
            item = d['result']['data'][0]
            roe_val = item.get('ROEJQ', 0)
            if roe_val is not None:
                result['roe'] = float(roe_val)
            xsml_val = item.get('XSMLL', 0)
            if xsml_val is not None:
                result['gross_margin'] = float(xsml_val)
            zcfzl_val = item.get('ZCFZL', 0)
            if zcfzl_val is not None:
                result['debt_ratio'] = float(zcfzl_val)
            xsjll_val = item.get('XSJLL', 0)
            if xsjll_val is not None:
                result['net_margin'] = float(xsjll_val)
    except:
        pass

    # 2. CPD: 拿营收同比 + 净利同比 + PB (MAINFINADATA无此字段)
    try:
        params = {
            'reportName': 'RPT_LICO_FN_CPD',
            'columns': 'DATAYEAR,DATEMMDD,WEIGHTAVG_ROE,YSTZ,SJLTZ,XSMLL',
            'filter': '(SECURITY_CODE="' + code + '")',
            'pageNumber': 1, 'pageSize': 1,
            'source': 'WEB', 'client': 'WEB',
        }
        resp = session.get(base_url, params=params, headers=DC_HEADERS, timeout=5)
        d = resp.json()
        if d.get('success') and d.get('result') and d['result'].get('data'):
            item = d['result']['data'][0]
            ystz = item.get('YSTZ', 0)
            if ystz is not None:
                result['rev_growth'] = float(ystz)
            sjltz = item.get('SJLTZ', 0)
            if sjltz is not None:
                result['profit_growth'] = float(sjltz)
            # 如果MAINFINADATA没拿到ROE, 用CPD的作为备选
            if result['roe'] == 0:
                cpd_roe = item.get('WEIGHTAVG_ROE', 0)
                if cpd_roe is not None:
                    result['roe'] = float(cpd_roe)
            # 如果MAINFINADATA没拿到毛利率, 用CPD的作为备选
            if result['gross_margin'] == 0:
                cpd_xsml = item.get('XSMLL', 0)
                if cpd_xsml is not None:
                    result['gross_margin'] = float(cpd_xsml)
    except:
        pass

    # 至少有一个有效数据才返回
    if result['roe'] != 0 or result['rev_growth'] != 0 or result['profit_growth'] != 0 or result['debt_ratio'] != 0:
        return result
    return None

def get_preset_financials():
    """预设高质量中小盘股票财务数据 - 从离线数据库加载"""
    # 尝试从离线数据库加载
    offline_path = os.path.join(os.path.dirname(__file__), 'offline_stocks.json')
    if os.path.exists(offline_path):
        try:
            with open(offline_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                stocks = data.get('stocks', [])
                # 转换为字典格式 {code: {name, roe, ...}}
                result = {}
                for s in stocks:
                    if not s.get('excluded', False):  # 排除白酒和银行
                        code = s['code']
                        result[code] = {
                            'name': s['name'],
                            'price': s.get('price', 0),
                            'roe': s['roe'],
                            'gross_margin': s['gross_margin'],
                            'net_margin': s['net_margin'],
                            'debt_ratio': s.get('debt_ratio', 0),  # 资产负债率
                            'rev_growth': s['rev_growth'],
                            'profit_growth': s['profit_growth'],
                            'pe': s['pe'],
                            'pb': s['pb'],
                            'market_cap': s['market_cap'],
                            'change_pct': s.get('change_pct', 0)
                        }
                print(f"✓ 从离线数据库加载 {len(result)} 只股票")
                return result
        except Exception as e:
            print(f"× 离线数据库加载失败: {e}")
    
    # 备用：硬编码15只核心股票
    return {
        "300015": {"name": "爱尔眼科", "roe": 22.5, "gross_margin": 48.5, "net_margin": 18.2, "rev_growth": 25.5, "profit_growth": 32.5, "pe": 65.2, "pb": 12.5, "market_cap": 2500},
        "300760": {"name": "迈瑞医疗", "roe": 32.5, "gross_margin": 85.5, "net_margin": 35.2, "rev_growth": 22.5, "profit_growth": 28.5, "pe": 45.2, "pb": 15.2, "market_cap": 35000},
        "300122": {"name": "智飞生物", "roe": 35.2, "gross_margin": 45.2, "net_margin": 32.5, "rev_growth": 28.5, "profit_growth": 38.5, "pe": 18.5, "pb": 8.2, "market_cap": 1200},
        "002007": {"name": "华兰生物", "roe": 22.5, "gross_margin": 65.5, "net_margin": 35.2, "rev_growth": 18.5, "profit_growth": 22.5, "pe": 35.2, "pb": 5.8, "market_cap": 450},
        "300059": {"name": "东方财富", "roe": 18.5, "gross_margin": 65.2, "net_margin": 65.2, "rev_growth": 35.2, "profit_growth": 42.5, "pe": 45.8, "pb": 5.2, "market_cap": 2800},
        "002049": {"name": "紫光国微", "roe": 28.5, "gross_margin": 52.5, "net_margin": 35.2, "rev_growth": 35.8, "profit_growth": 42.5, "pe": 55.8, "pb": 12.5, "market_cap": 1200},
        "002236": {"name": "大华股份", "roe": 18.2, "gross_margin": 42.5, "net_margin": 15.8, "rev_growth": 15.2, "profit_growth": 18.5, "pe": 22.5, "pb": 3.2, "market_cap": 550},
        "300274": {"name": "阳光电源", "roe": 22.5, "gross_margin": 28.5, "net_margin": 15.8, "rev_growth": 45.2, "profit_growth": 55.8, "pe": 35.2, "pb": 8.5, "market_cap": 1800},
        "002812": {"name": "恩捷股份", "roe": 22.5, "gross_margin": 45.8, "net_margin": 32.5, "rev_growth": 55.2, "profit_growth": 65.8, "pe": 28.5, "pb": 6.8, "market_cap": 580},
        "300014": {"name": "亿纬锂能", "roe": 20.5, "gross_margin": 22.5, "net_margin": 18.5, "rev_growth": 65.8, "profit_growth": 75.2, "pe": 32.5, "pb": 7.2, "market_cap": 1500},
        "002027": {"name": "分众传媒", "roe": 25.8, "gross_margin": 65.8, "net_margin": 42.5, "rev_growth": 18.5, "profit_growth": 25.2, "pe": 28.5, "pb": 4.8, "market_cap": 1200},
        "002371": {"name": "北方华创", "roe": 25.8, "gross_margin": 35.2, "net_margin": 18.5, "rev_growth": 35.8, "profit_growth": 45.2, "pe": 65.5, "pb": 10.5, "market_cap": 1800},
        "300751": {"name": "迈为股份", "roe": 28.5, "gross_margin": 72.5, "net_margin": 35.8, "rev_growth": 55.2, "profit_growth": 65.8, "pe": 45.2, "pb": 12.5, "market_cap": 950},
        "002352": {"name": "顺丰控股", "roe": 12.5, "gross_margin": 18.5, "net_margin": 5.2, "rev_growth": 28.5, "profit_growth": 35.8, "pe": 35.8, "pb": 3.8, "market_cap": 1850},
        "603288": {"name": "海天味业", "roe": 32.5, "gross_margin": 38.5, "net_margin": 28.5, "rev_growth": 15.2, "profit_growth": 18.5, "pe": 45.8, "pb": 12.5, "market_cap": 2500},
    }

def evaluate_stock(stock):
    """五维价值投资评估 - 支持全市场股票"""
    score = 0
    dimensions = {"profitability": 0, "growth": 0, "health": 0, "valuation": 0, "cashflow": 0}
    reasons = []

    # 排除白酒和银行
    liquor_names = ["贵州茅台", "五粮液", "洋河股份", "泸州老窖", "山西汾酒", "酒鬼酒", "水井坊", "古井贡酒", "古井贡酒", "迎驾贡酒", "今世缘", "舍得酒业", "老白干酒", "伊力特", "口子窖", "金徽酒", "皇台酒业", "岩石股份", "顺鑫农业"]
    bank_codes = ["601398", "601288", "600000", "600036", "601166", "600015", "600016", "601328", "600919", "600028", "601939", "601988", "601318", "600030"]
    name = stock.get("name", "")
    code = stock.get("code", "")
    # 过滤北交所/B股/A股重复
    if code.startswith('8') or code.startswith('4') or code.startswith('920'):
        return None
    if code.startswith('900') or code.startswith('200') or code.startswith('A2'):
        return None
    if any(n in name for n in liquor_names) or code in bank_codes:
        return None

    roe = stock.get("roe", 0)
    gross_margin = stock.get("gross_margin", 0)
    net_margin = stock.get("net_margin", 0)
    rev_growth = stock.get("rev_growth", 0)
    profit_growth = stock.get("profit_growth", 0)
    pe = stock.get("pe", 0)
    pb = stock.get("pb", 0)
    debt_ratio = stock.get("debt_ratio", 0)
    market_cap = stock.get("market_cap", 0)

    # 数据完整度判断
    has_profitability = roe > 0 or gross_margin > 0 or net_margin > 0
    has_growth = rev_growth != 0 or profit_growth != 0
    has_valuation = pe > 0 or pb > 0

    # 盈利能力 (最高35分) - 连续评分而非阶梯式，增加区分度
    if roe < 0:
        dimensions["profitability"] = 0
        reasons.append(f"ROE {roe:.1f}% 亏损 ⚠️")
    elif roe >= 18:  # 优化：20% -> 18%
        # ROE 20%-40%映射到 25-35分（连续），每增加1%ROE多1分
        dimensions["profitability"] = min(25 + (roe - 20) * 1, 35)
        reasons.append(f"ROE {roe:.1f}% 优秀")
    elif roe >= 15:
        dimensions["profitability"] = 15 + (roe - 15) * 2  # 15-25分
        reasons.append(f"ROE {roe:.1f}% 良好")
    elif roe > 0:
        dimensions["profitability"] = roe * 1  # 0-15分
        reasons.append(f"ROE {roe:.1f}%")
    else:
        if profit_growth > 20:
            dimensions["profitability"] = 12
            reasons.append("净利润高增长，盈利能力推测良好")
        elif profit_growth > 0:
            dimensions["profitability"] = 8
        else:
            dimensions["profitability"] = 0

    if gross_margin >= 40:
        dimensions["profitability"] = min(dimensions["profitability"] + 8, 35)
        reasons.append(f"毛利率 {gross_margin:.1f}% ✓")
    elif gross_margin > 0:
        dimensions["profitability"] = min(dimensions["profitability"] + 3, 35)

    if net_margin >= 15:
        dimensions["profitability"] = min(dimensions["profitability"] + 5, 35)
        reasons.append(f"净利率 {net_margin:.1f}% ✓")
    score += dimensions["profitability"]

    # 成长性 (25分) - ROE为负时成长性打折
    if roe < 0:
        # 亏损企业，成长性最多5分（即使有增速也可能是扭亏为盈）
        if profit_growth > 20 and rev_growth > 0:
            dimensions["growth"] = 5
            reasons.append("亏损企业但有改善迹象")
        else:
            dimensions["growth"] = 0
        score += dimensions["growth"]
    else:
        if rev_growth > 0 and profit_growth > 0:
            avg_growth = (rev_growth + profit_growth) / 2
        elif rev_growth > 0:
            avg_growth = rev_growth
        elif profit_growth > 0:
            avg_growth = profit_growth
        else:
            avg_growth = 0

        if avg_growth >= 20:
            dimensions["growth"] = min(20 + (avg_growth - 20) * 0.5, 25)  # 20-25分连续
            reasons.append(f"成长性 {avg_growth:.1f}% 优秀")
        elif avg_growth >= 15:
            dimensions["growth"] = 15 + (avg_growth - 15) * 1  # 15-20分连续
            reasons.append(f"成长性 {avg_growth:.1f}% 良好")
        elif avg_growth >= 10:
            dimensions["growth"] = 10 + (avg_growth - 10) * 1  # 10-15分连续
        elif avg_growth > 0:
            dimensions["growth"] = avg_growth * 1  # 0-10分连续
        else:
            dimensions["growth"] = 0
        score += dimensions["growth"]

    # 财务健康 (20分)
    if debt_ratio > 0 and debt_ratio < 1000:  # 过滤异常值
        if debt_ratio <= 50:
            dimensions["health"] = 20
            reasons.append(f"资产负债率 {debt_ratio:.1f}% ✓健康")
        elif debt_ratio <= 70:
            dimensions["health"] = 12
        else:
            dimensions["health"] = 5
    else:
        dimensions["health"] = 0  # 优化：无数据不给分  # 无数据给中等分
    score += dimensions["health"]

    # 估值 (20分) - 连续评分
    # 注意：PE为负说明亏损（TTM），不应给估值分
    if pe > 0 and pe < 1000:
        if pe <= 12:  # 优化：15 -> 12
            dimensions["valuation"] = min(15 + (15 - pe) * 0.33, 20)  # PE越低分越高
            reasons.append(f"PE {pe:.1f} 低估 ✓")
        elif pe <= 20:  # 优化：25 -> 20
            dimensions["valuation"] = 15 - (pe - 15) * 0.5  # 15→10分
            reasons.append(f"PE {pe:.1f} 合理")
        elif pe <= 35:
            dimensions["valuation"] = 10 - (pe - 25) * 0.5  # 10→5分
        elif pe <= 50:
            dimensions["valuation"] = 5 - (pe - 35) * 0.33  # 5→0分
            dimensions["valuation"] = max(dimensions["valuation"], 0)
        else:
            dimensions["valuation"] = 0
            if pe > 100:
                reasons.append(f"PE {pe:.1f} 高估 ⚠️")
    elif pe <= 0:
        dimensions["valuation"] = 0
    else:
        dimensions["valuation"] = 8

    if 0 < pb <= 3:
        dimensions["valuation"] = min(dimensions["valuation"] + 5, 20)
    elif 3 < pb <= 5:
        dimensions["valuation"] = min(dimensions["valuation"] + 2, 20)
    score += dimensions["valuation"]

    # 现金流质量 (加分项，上限5分)
    # 通过 PE 和 ROE 推导盈利质量：低PE+高ROE = 现金流充裕
    # PE低说明利润含金量高（不是纸面利润），ROE高说明资产周转效率好
    market_cap_yi = market_cap / 100000000 if market_cap > 0 else 0
    if pe > 0 and roe > 15:
        # 盈利为正且ROE优秀
        if pe <= 20:
            dimensions["cashflow"] = 5
            score += 5
            reasons.append(f"PE {pe:.1f} + ROE {roe:.1f}% 现金流充裕 ✓")
        elif pe <= 30:
            dimensions["cashflow"] = 4
            score += 4
            reasons.append(f"PE {pe:.1f} + ROE {roe:.1f}% 盈利质量良好")
        elif pe <= 45:
            dimensions["cashflow"] = 2
            score += 2
            reasons.append(f"PE {pe:.1f} + ROE {roe:.1f}% 盈利质量一般")
        else:
            dimensions["cashflow"] = 1
            score += 1
            reasons.append(f"PE {pe:.1f} 偏高 利润含金量待验证")
    elif pe > 0 and roe > 0:
        # 有盈利但ROE一般
        if pe <= 20:
            dimensions["cashflow"] = 3
            score += 3
            reasons.append(f"PE {pe:.1f} 低估值 盈利较真实")
        elif pe <= 35:
            dimensions["cashflow"] = 1
            score += 1
    else:
        dimensions["cashflow"] = 0
        if pe <= 0 and roe <= 0:
            reasons.append("亏损企业 现金流堪忧 ⚠️")
    # 市值信息（不参与评分，仅展示）
    if market_cap_yi > 0:
        reasons.append(f"市值 {market_cap_yi:.0f}亿")

    # 买卖点
    buy_sell = calculate_buy_sell(stock, score)

    # 四舍五入所有维度分数，确保显示一致
    rounded_dimensions = {k: round(v) for k, v in dimensions.items()}

    return {
        "code": code,
        "name": name,
        "price": stock.get("price", 0),
        "change_pct": stock.get("change_pct", 0),
        "pe": pe,
        "pb": pb,
        "roe": roe,
        "gross_margin": gross_margin,
        "net_margin": net_margin,
        "debt_ratio": debt_ratio,
        "rev_growth": rev_growth,
        "profit_growth": profit_growth,
        "market_cap": market_cap_yi,
        "score": round(score, 1),  # 综合评分保留1位小数
        "dimensions": rounded_dimensions,  # 维度分数四舍五入为整数
        "reasons": reasons,
        "buy_sell": buy_sell,
    }

def calculate_buy_sell(stock, score):
    """计算买卖点 + 五星评级
    
    2026-04-08修复：
    - 调整fair_pe公式，考虑成长性溢价（高成长股PE理应更高）
    - 取消硬性None返回，score>=50的股票全部给出建议
    - 放宽门槛，让更多优质股能展示出来
    """
    price = stock.get("price", 0)
    pe = stock.get("pe", 0)
    roe = stock.get("roe", 0)
    gross_margin = stock.get("gross_margin", 0)
    rev_growth = stock.get("rev_growth", 0)
    profit_growth = stock.get("profit_growth", 0)
    if price <= 0 or pe <= 0:
        return None

    # === 动态计算合理PE（考虑成长性溢价）===
    # 基础：fair_pe = ROE * 1.5（比之前的1.2更宽松）
    # 成长性溢价：营收/净利增速越高，合理PE越高
    avg_growth = (rev_growth + profit_growth) / 2
    growth_premium = min(avg_growth * 0.3, 15)  # 成长溢价最多+15倍
    
    fair_pe = roe * 1.5 + growth_premium
    # 设置合理范围：最低 12 倍，最高 60 倍（成长股可以给更高估值）
    fair_pe = max(12, min(60, fair_pe))

    # 五星评级逻辑
    star_rating = 1  # 默认至少1星（有评分就有星级）

    if pe < fair_pe:
        # 当前低于合理估值：推荐买入区间
        if score >= 82:
            buy_point = round(price * 0.95, 2)  # 5%折扣
            upside = min(max((fair_pe - pe) / pe, 0.25), 0.8)
            sell_point = round(price * (1 + upside), 2)
            rec = "强烈推荐"
            star_rating = 5 if score >= 86 and roe >= 18 and gross_margin >= 28 else 4
            if star_rating == 4 and price - buy_point <= price * 0.05:
                star_rating = 5
        elif score >= 68:
            buy_point = round(price * 0.92, 2)
            upside = min(max((fair_pe - pe) / pe, 0.25), 0.7)
            sell_point = round(price * (1 + upside), 2)
            rec = "推荐买入"
            star_rating = 4 if score >= 75 else 3
        elif score >= 55:
            buy_point = round(price * 0.88, 2)
            upside = min(max((fair_pe - pe) / pe, 0.2), 0.5)
            sell_point = round(price * (1 + upside), 2)
            rec = "可逢低关注"
            star_rating = 3 if score >= 62 else 2
        else:
            # score < 55 但仍进入评估的，给基本建议
            buy_point = round(price * 0.85, 2)
            upside = 0.3
            sell_point = round(price * 1.3, 2)
            rec = "轻度关注"
            star_rating = 1
    else:
        # 当前高于合理估值：等待回调或谨慎持有
        if score >= 75 and pe < fair_pe * 1.3:
            # 估值偏高但基本面优秀
            buy_point = round(price * 0.85, 2)
            upside = min(max((fair_pe - pe) / pe, 0.15), 0.5)
            sell_point = round(price * (1 + max(upside, 0.2)), 2)
            rec = "等待更好买点"
            star_rating = 3
        elif score >= 58:
            buy_point = round(price * 0.82, 2)
            upside = 0.25
            sell_point = round(price * 1.25, 2)
            rec = "高估观望"
            star_rating = 2
        else:
            buy_point = round(price * 0.80, 2)
            sell_point = round(price * 1.18, 2)
            rec = "暂不推荐"
            star_rating = 1

    return {
        "current": price,
        "buy": buy_point,
        "sell": sell_point,
        "upside": round((sell_point - price) / price * 100, 1),
        "downside": round((price - buy_point) / price * 100, 1),
        "recommendation": rec,
        "star_rating": star_rating,
    }

def run_picker():
    """执行选股主流程 - 全市场扫描"""
    print("正在获取全市场实时行情...")
    all_stocks = get_realtime_quotes()

    if not all_stocks or len(all_stocks) < 50:
        print("⚠️ 实时行情获取失败，启用离线模式")
        print("📦 从离线数据库加载股票...")
        # fallback: 使用预设库
        preset_data = get_preset_financials()
        stock_pool = []
        for code, fin in preset_data.items():
            entry = {
                "code": code, "name": fin["name"],
                "price": fin.get("price", 0),
                "roe": fin["roe"], "gross_margin": fin["gross_margin"],
                "net_margin": fin["net_margin"], "debt_ratio": fin.get("debt_ratio", 0),
                "rev_growth": fin["rev_growth"],
                "profit_growth": fin["profit_growth"], "pe": fin["pe"],
                "pb": fin["pb"], "market_cap": fin["market_cap"],
                "change_pct": fin.get("change_pct", 0),
            }
            stock_pool.append(entry)
        print(f"✓ 离线模式：加载 {len(stock_pool)} 只股票")
    else:
        print(f"成功获取 {len(all_stocks)} 只股票行情，开始五维评估...")
        # 用预设数据增强实时数据中缺少财务指标的股票
        preset_data = get_preset_financials()
        stock_pool = []
        for stock in all_stocks:
            code = stock["code"]
            # 如果实时数据缺少关键财务指标，用预设库积极补充
            if code in preset_data:
                fin = preset_data[code]
                # 补充缺失的财务数据
                if stock.get("roe", 0) == 0:
                    stock["roe"] = fin.get("roe", 0)
                if stock.get("gross_margin", 0) == 0:
                    stock["gross_margin"] = fin.get("gross_margin", 0)
                if stock.get("net_margin", 0) == 0:
                    stock["net_margin"] = fin.get("net_margin", 0)
                if stock.get("debt_ratio", 0) == 0:
                    stock["debt_ratio"] = fin.get("debt_ratio", 0)
                if stock.get("rev_growth", 0) == 0:
                    stock["rev_growth"] = fin.get("rev_growth", 0)
                if stock.get("profit_growth", 0) == 0:
                    stock["profit_growth"] = fin.get("profit_growth", 0)
                # PB优先使用实时数据，如果没有则用预设
                if stock.get("pb", 0) == 0:
                    stock["pb"] = fin.get("pb", 0)
                # 如果PE无效但PB有效，可以从PB反推
                if stock.get("pe", 0) == 0 and stock.get("pb", 0) > 0 and stock.get("roe", 0) > 0:
                    # PE = PB / ROE (简化估算)
                    stock["pe"] = round(stock["pb"] / (stock["roe"] / 100), 1) if stock["roe"] > 0 else 0
            stock_pool.append(stock)

        # 对评分可能≥50的股票，用财务数据中心校准ROE和毛利率
        # 性能优化：并发请求加速，先做一轮快速评估找出评分较高的股票优先校准
        # (行情API的ROE(f37)经常缺失或过期，必须用年报数据覆盖)
        
        # 快速预评估：找出评分可能较高的股票
        # 改进策略：先快速评估所有股票，找出评分>=50的候选，然后校准这些股票
        # 这样确保首页和详情页评分一致（因为首页校准了所有可能进入结果列表的股票）
        quick_eval_candidates = []
        for s in stock_pool:
            # 快速判断：ROE>10 或 debt_ratio缺失 或 gross_margin缺失 或 PE有效
            # 放宽条件，确保更多股票被校准
            if s.get("roe", 0) >= 10 or s.get("debt_ratio", 0) == 0 or s.get("gross_margin", 0) == 0 or (s.get("pe", 0) > 0 and s.get("pe", 0) < 50):
                quick_eval_candidates.append(s)
        
        # 按ROE排序，优先校准ROE高的股票（这些评分可能更高）
        quick_eval_candidates.sort(key=lambda x: x.get("roe", 0), reverse=True)
        
        # 优化校准策略：只校准评分可能>=55的股票（减少API调用）
        # 快速预评估：ROE>=12 或 PE有效且<40 或 毛利率>=30
        high_potential = [s for s in stock_pool if 
                          s.get("roe", 0) >= 12 or 
                          (s.get("pe", 0) > 0 and s.get("pe", 0) < 40) or 
                          s.get("gross_margin", 0) >= 30]
        
        # 按ROE排序，优先校准ROE高的（评分潜力更大）
        high_potential.sort(key=lambda x: x.get("roe", 0), reverse=True)
        
        # 校准范围：最多50只（从100减少到50，显著减少API调用）
        candidates_to_process = high_potential[:50]
        
        if candidates_to_process:
            print(f"  并发校准 {len(candidates_to_process)} 只高潜力股票...")
            
            # 定义单只股票校准函数（优化timeout）
            def calibrate_single_stock(stock):
                fin_data = get_financial_data_fast(stock["code"])
                if fin_data:
                    if fin_data.get("roe", 0) != 0:
                        stock["roe"] = fin_data["roe"]
                    if stock.get("gross_margin", 0) == 0 and fin_data.get("gross_margin", 0) != 0:
                        stock["gross_margin"] = fin_data["gross_margin"]
                    if stock.get("rev_growth", 0) == 0 and fin_data.get("rev_growth", 0) != 0:
                        stock["rev_growth"] = fin_data["rev_growth"]
                    if stock.get("profit_growth", 0) == 0 and fin_data.get("profit_growth", 0) != 0:
                        stock["profit_growth"] = fin_data["profit_growth"]
                    if fin_data.get("debt_ratio", 0) != 0:
                        stock["debt_ratio"] = fin_data["debt_ratio"]
                    if fin_data.get("net_margin", 0) != 0:
                        stock["net_margin"] = fin_data["net_margin"]
                return stock["code"]
            
            # 并发执行（30个线程，timeout=3秒）
            start_time = time.time()
            with ThreadPoolExecutor(max_workers=30) as executor:
                futures = [executor.submit(calibrate_single_stock, s) for s in candidates_to_process]
                completed = 0
                for future in as_completed(futures):
                    completed += 1
                    if completed % 10 == 0:
                        print(f"    已校准 {completed}/{len(candidates_to_process)}...")
            
            elapsed = time.time() - start_time
            print(f"  校准完成，耗时 {elapsed:.1f}s")

    # 对所有股票进行五维评估
    results = []
    total_scanned = len(stock_pool)
    for stock in stock_pool:
        r = evaluate_stock(stock)
        if r and r["score"] >= 50:
            results.append(r)

    # 动态排序：基础分数 + 实时涨跌幅微调（让排名随盘面变化）
    # 涨幅每1%加0.3分，跌幅每1%减0.2分（变化幅度小，不影响核心评分逻辑）
    for r in results:
        change = r.get("change_pct", 0)
        r["_dynamic_score"] = r["score"] + change * 0.3

    results.sort(key=lambda x: x["_dynamic_score"], reverse=True)

    # 清理内部字段 + 分数四舍五入保留1位小数
    for r in results:
        r.pop("_dynamic_score", None)
        # 评分保留1位小数，避免过长小数点
        r["score"] = round(r["score"], 1)
        # 确保debt_ratio存在
        if "debt_ratio" not in r:
            r["debt_ratio"] = 0
        # 买卖点价格也保留2位小数
        if r.get("buy_sell"):
            r["buy_sell"]["buy"] = round(r["buy_sell"]["buy"], 2)
            r["buy_sell"]["sell"] = round(r["buy_sell"]["sell"], 2)
            r["buy_sell"]["current"] = round(r["buy_sell"]["current"], 2)

    # 在第一个结果中附带总数
    if results:
        results[0]['_total_scanned'] = total_scanned
    print(f"评估完成，扫描 {total_scanned} 只，符合条件股票: {len(results)} 只")
    return results

# ========== 新闻热点模块 ==========

import re

# 板块关键词映射（全局复用）
SECTOR_KEYWORDS = {
    "半导体": ["芯片", "半导体", "集成电路", "AI芯片", "GPU", "CPU", "存储芯片", "封装", "光刻"],
    "人工智能": ["人工智能", "AI", "大模型", "ChatGPT", "生成式AI", "机器学习", "深度学习", "自动驾驶", "Sora"],
    "新能源汽车": ["新能源车", "电动车", "电动汽车", "混动", "充电桩", "电池", "锂电", "固态电池", "比亚迪", "特斯拉", "宁德时代"],
    "光伏": ["光伏", "太阳能", "硅片", "组件", "逆变器", "HJT", "TOPCon"],
    "医药生物": ["医药", "生物", "创新药", "疫苗", "CXO", "医疗器械", "中药", "仿制药", "PD-1", "医保"],
    "消费电子": ["消费电子", "手机", "华为", "苹果", "MR", "VR", "AR", "折叠屏", "智能穿戴"],
    "房地产": ["房地产", "楼市", "房价", "房企", "拿地", "保交楼", "城中村", "地产"],
    "银行": ["银行", "信贷", "贷款", "降准", "降息", "LPR", "利率", "央行"],
    "军工": ["军工", "国防", "航天", "航空", "导弹", "军备", "战斗机", "航母"],
    "白酒": ["白酒", "茅台", "五粮液", "酒"],
    "证券": ["证券", "券商", "资本市场", "IPO", "注册制", "北交所", "牛市", "熊市"],
    "数字经济": ["数字经济", "数据要素", "云计算", "大数据", "数据中心", "算力"],
    "机器人": ["机器人", "人形机器人", "工业机器人", "减速器", "伺服电机"],
    "游戏传媒": ["游戏", "传媒", "影视", "短剧", "直播", "网游"],
    "有色金属": ["有色", "黄金", "铜", "铝", "锂", "稀土", "钴", "镍"],
    "养殖": ["养殖", "猪", "鸡", "饲料", "农业"],
    "电力": ["电力", "电网", "储能", "特高压", "风电", "核电", "火电"],
    "化工": ["化工", "新材料", "塑料", "化纤"],
}

def fetch_sina_sectors(category):
    """从新浪财经获取板块实时行情数据
    
    category: 'class' (概念板块, ~175个) 或 'industry' (行业板块, ~84个)
    数据源: https://money.finance.sina.com.cn/q/view/newFLJK.php?param={category}
    
    返回字段: code, name, stock_count, avg_pe, change_pct, turnover,
              volume, amount, leader_code, leader_name, leader_price, leader_change
    """
    url = f'https://money.finance.sina.com.cn/q/view/newFLJK.php?param={category}'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        r = session.get(url, headers=HEADERS, timeout=15)
        r.encoding = 'gb2312'
        text = r.text.strip()
        
        start = text.find('{')
        end = text.rfind('}')
        if start < 0 or end < 0:
            return []
        
        data = json.loads(text[start:end+1])
        sectors = []
        
        for key, val in data.items():
            parts = val.split(',')
            if len(parts) < 13:
                continue
            try:
                sectors.append({
                    "code": parts[0],                    # gn_hwqc / hangye_ZA01
                    "name": parts[1],                    # 板块名称
                    "stock_count": int(parts[2]),        # 成分股数量
                    "avg_pe": float(parts[3]),           # 平均PE
                    "change_pct": float(parts[4]),       # 涨跌幅(%)
                    "turnover": float(parts[5]),         # 换手率(%)
                    "volume": int(parts[6]),             # 成交量(手)
                    "amount": int(parts[7]),             # 成交额(元)
                    "leader_code": parts[8],             # 领涨股代码 如 sh603158
                    "leader_name": parts[12],            # 领涨股名称
                    "leader_price": float(parts[10]),    # 领涨股现价
                    "leader_change": float(parts[9]),    # 领涨股涨幅(%)
                })
            except (ValueError, IndexError):
                continue
        
        return sectors
    except Exception as e:
        print(f"  fetch_sina_sectors({category}) 失败: {e}")
        return []


def get_sector_news():
    """抓取财经新闻 + 板块实时行情 + 关联分析
    
    2026-04-02 v8: push2/push2his 全被封。
    数据源方案:
    - 行业板块(84个): 新浪 newFLJK.php?param=industry
    - 概念板块(175个): 新浪 newFLJK.php?param=class  
    - 新闻: 新浪 feed.mix.sina.com.cn
    - 不再依赖 sector_codes.json 和 push2 API
    
    2026-04-03 v9: 离线模式支持
    """
    news_list = []

    # ---- 1. 新浪API获取行业板块实时行情 ----
    print("  获取行业板块行情(新浪)...")
    sector_data = fetch_sina_sectors('industry')
    print(f"  行业板块: {len(sector_data)} 个")

    # ---- 2. 新浪API获取概念板块实时行情 ----
    print("  获取概念板块行情(新浪)...")
    concept_data = fetch_sina_sectors('class')
    print(f"  概念板块: {len(concept_data)} 个")

    # ---- 3. 离线模式检测 ----
    if len(sector_data) == 0 and len(concept_data) == 0:
        print("⚠️ 板块数据获取失败，启用离线模式")
        # 返回模拟板块数据
        sector_data = [
            {"name": "半导体", "change_pct": 2.85, "avg_pe": 65.2, "stock_count": 85, "leader_name": "北方华创", "leader_change": 5.25, "code": "hangye_bandaoti"},
            {"name": "医疗器械", "change_pct": 1.95, "avg_pe": 45.2, "stock_count": 120, "leader_name": "迈瑞医疗", "leader_change": 1.85, "code": "hangye_yiliaoqixie"},
            {"name": "锂电池", "change_pct": 3.25, "avg_pe": 35.2, "stock_count": 95, "leader_name": "宁德时代", "leader_change": 2.65, "code": "hangye_lidianchi"},
            {"name": "光伏设备", "change_pct": 2.45, "avg_pe": 22.5, "stock_count": 65, "leader_name": "阳光电源", "leader_change": 4.25, "code": "hangye_guangfushebei"},
            {"name": "生物制品", "change_pct": -1.25, "avg_pe": 28.5, "stock_count": 80, "leader_name": "智飞生物", "leader_change": -1.25, "code": "hangye_shengwuzhipin"},
            {"name": "软件开发", "change_pct": 1.85, "avg_pe": 85.2, "stock_count": 150, "leader_name": "科大讯飞", "leader_change": 2.85, "code": "hangye_ruanjiankaifa"},
            {"name": "消费电子", "change_pct": -0.85, "avg_pe": 28.5, "stock_count": 110, "leader_name": "立讯精密", "leader_change": 1.85, "code": "hangye_xiaofeidianzi"},
            {"name": "化学制药", "change_pct": 0.65, "avg_pe": 32.5, "stock_count": 95, "leader_name": "药明康德", "leader_change": 2.15, "code": "hangye_huaxuezhiyao"},
        ]
        concept_data = [
            {"name": "创新药", "change_pct": 1.85, "avg_pe": 38.5, "stock_count": 140, "leader_name": "智飞生物", "leader_change": -1.25, "code": "gn_cxy"},
            {"name": "新能源汽车", "change_pct": 3.15, "avg_pe": 42.5, "stock_count": 180, "leader_name": "比亚迪", "leader_change": 4.15, "code": "gn_xinnengyuanqiche"},
            {"name": "人工智能", "change_pct": 2.65, "avg_pe": 125.2, "stock_count": 120, "leader_name": "科大讯飞", "leader_change": 2.85, "code": "gn_rengongzhineng"},
            {"name": "芯片国产化", "change_pct": 3.85, "avg_pe": 85.2, "stock_count": 95, "leader_name": "北方华创", "leader_change": 5.25, "code": "gn_xinpianbaotichan"},
            {"name": "储能", "change_pct": 2.95, "avg_pe": 32.5, "stock_count": 75, "leader_name": "阳光电源", "leader_change": 4.25, "code": "gn_chuneng"},
            {"name": "工业4.0", "change_pct": 1.55, "avg_pe": 35.2, "stock_count": 130, "leader_name": "汇川技术", "leader_change": 2.45, "code": "gn_gongye40"},
            {"name": "数字经济", "change_pct": 2.25, "avg_pe": 55.2, "stock_count": 145, "leader_name": "东方财富", "leader_change": 3.25, "code": "gn_shuzijinji"},
            {"name": "碳中和", "change_pct": 2.15, "avg_pe": 28.5, "stock_count": 165, "leader_name": "隆基绿能", "leader_change": 2.45, "code": "gn_tanzhonghe"},
        ]
        print(f"✓ 离线模式：加载 {len(sector_data)} 个行业板块 + {len(concept_data)} 个概念板块")

    # ---- 4. 从新浪财经获取新闻 ----
    try:
        r = session.get("https://feed.mix.sina.com.cn/api/roll/get",
                         params={"pageid": "153", "lid": "2509", "k": "", "r": "0.5", "page": 1},
                         headers=HEADERS, timeout=10)
        d = r.json()
        if d.get('result') and d['result'].get('data'):
            for item in d['result']['data'][:40]:
                news_list.append({
                    "title": item.get('title', ''),
                    "time": item.get('ctime', ''),
                    "source": item.get('media_name', ''),
                    "summary": item.get('intro', '') or item.get('summary', ''),
                })
    except Exception as e:
        print(f"  获取新闻失败: {e}")

    if not news_list:
        print("⚠️ 新闻获取失败，启用离线模式")
        # 模拟财经新闻数据
        news_list = [
            {"title": "半导体板块集体走强，北方华创领涨", "url": "#", "time": "10:25", "summary": "受国产替代加速推动，半导体板块今日表现强势，北方华创涨停，中微公司涨超8%。"},
            {"title": "新能源汽车销量创新高，比亚迪单月突破30万辆", "url": "#", "time": "11:15", "summary": "比亚迪发布最新销售数据，单月销量突破30万辆，继续领跑新能源汽车市场。"},
            {"title": "光伏行业景气度持续提升，龙头企业订单饱满", "url": "#", "time": "13:30", "summary": "阳光电源、隆基绿能等光伏龙头获大额订单，行业景气度持续向好。"},
            {"title": "AI应用加速落地，科大讯飞股价创年内新高", "url": "#", "time": "14:20", "summary": "科大讯飞发布AI大模型应用成果，股价创年内新高，人工智能板块整体走强。"},
            {"title": "医疗器械国产化进程加快，迈瑞医疗获批量采购订单", "url": "#", "time": "15:05", "summary": "迈瑞医疗获多省份医疗设备集中采购订单，国产医疗器械替代进程加速。"},
            {"title": "锂电池产业链整合加速，宁德时代布局上游资源", "url": "#", "time": "15:45", "summary": "宁德时代宣布投资锂矿资源，完善产业链布局，锂电池板块整体受益。"},
            {"title": "消费电子回暖信号显现，立讯精密获苹果新订单", "url": "#", "time": "16:10", "summary": "立讯精密获得苹果新订单，消费电子产业链回暖信号明显。"},
            {"title": "医药研发外包市场扩张，药明康德业绩超预期", "url": "#", "time": "16:35", "summary": "药明康德发布业绩预告，净利润增长超预期，医药研发外包市场持续扩张。"},
        ]
        print(f"✓ 离线模式：加载 {len(news_list)} 条模拟新闻")

    # ---- 4. 新闻与板块关联分析 ----
    利好词 = ["上涨", "增长", "突破", "超预期", "利好", "政策支持", "补贴", "创新高", "大涨", "暴涨",
              "加速", "提升", "扩大", "向好", "复苏", "回暖", "走强", "拉升", "涨停", "爆发"]
    利空词 = ["下跌", "下滑", "亏损", "收紧", "制裁", "打压", "暴跌", "跌停", "危机", "风险", "利空", "放缓"]

    all_sectors = sector_data + concept_data
    for news in news_list:
        affected = []
        text = news.get("title", "") + " " + news.get("summary", "")
        for sector, keywords in SECTOR_KEYWORDS.items():
            match_count = sum(1 for kw in keywords if kw in text)
            if match_count > 0:
                sector_info = next((s for s in all_sectors if s["name"] == sector or sector in s["name"]), None)
                if any(kw in text for kw in 利好词):
                    impact = "利好"
                elif any(kw in text for kw in 利空词):
                    impact = "利空"
                else:
                    impact = "关注"
                affected.append({
                    "sector": sector,
                    "impact": impact,
                    "match_count": match_count,
                    "change_pct": sector_info["change_pct"] if sector_info else 0,
                    "leader": sector_info.get("leader_name", "") if sector_info else "",
                    "main_net": sector_info.get("amount", 0) if sector_info else 0,
                })
        affected.sort(key=lambda x: x["match_count"], reverse=True)
        news["affected_sectors"] = affected[:5]

    relevant_news = [n for n in news_list if n.get("affected_sectors")]

    # 排名
    top_sectors = sorted(sector_data, key=lambda x: x.get("change_pct", 0), reverse=True)[:15]
    top_concepts = sorted(concept_data, key=lambda x: x.get("change_pct", 0), reverse=True)[:15]
    # 按成交额排序（如果没有amount字段，用change_pct替代）
    top_fund_inflow = sorted(sector_data, key=lambda x: x.get("amount", x.get("change_pct", 0)), reverse=True)[:10]

    return {
        "news": relevant_news[:25] if relevant_news else news_list[:25],
        "all_news": news_list[:40],
        "total_news": len(news_list),
        "top_sectors": top_sectors,
        "top_concepts": top_concepts,
        "top_fund_inflow": top_fund_inflow,
        "sector_count": len(sector_data),
        "concept_count": len(concept_data),
    }

# ========== Flask路由 ==========

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/pick')
def api_pick():
    """执行选股并返回JSON

    注意: run_picker()内部会调用get_realtime_quotes()，不要重复调用
    """
    try:
        results = run_picker()
        total = results[0].get('_total_scanned', len(get_preset_financials())) if results else len(get_preset_financials())
        # 清理内部字段
        for r in results:
            r.pop('_total_scanned', None)
            # 补充 debt_ratio（如果缺失则从财务数据API获取）
            if 'debt_ratio' not in r or r.get('debt_ratio', 0) == 0:
                fin = get_financial_data_fast(r.get('code', ''))
                if fin and fin.get('debt_ratio', 0) != 0:
                    r['debt_ratio'] = fin['debt_ratio']
                else:
                    r['debt_ratio'] = 0
            # 补充 net_margin
            if 'net_margin' not in r or r.get('net_margin', 0) == 0:
                fin = get_financial_data_fast(r.get('code', ''))
                if fin and fin.get('net_margin', 0) != 0:
                    r['net_margin'] = fin['net_margin']
        return jsonify({
            "success": True,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_scanned": total,
            "results": results,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/news')
def api_news():
    """获取新闻热点与板块分析"""
    try:
        result = get_sector_news()
        return jsonify({
            "success": True,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **result,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/sector_stocks')
def api_sector_stocks():
    """获取板块成分股（用于板块详情）
    
    支持两种板块代码格式:
    - 东方财富 BK 代码 (如 BK0420): 通过 datacenter-web + 腾讯API
    - 新浪板块代码 (如 gn_hwqc, hangye_ZA01): 通过新浪 Market_Center API
    """
    sector_code = request.args.get("code", "")
    sector_name = request.args.get("name", "")
    if not sector_code:
        return jsonify({"success": False, "error": "缺少板块代码"}), 400

    try:
        stocks = []
        em_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://quote.eastmoney.com/"
        }
        tx_headers = {'User-Agent': 'Mozilla/5.0'}

        # ---- 优先方案: 新浪板块代码直接用新浪API ----
        if sector_code.startswith('gn_') or sector_code.startswith('hangye_'):
            print(f"  新浪板块成分股: {sector_code} ({sector_name})")
            try:
                url = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
                all_stocks = []
                # 分页获取，每页最多返回约40条，获取全部
                for page in range(1, 6):
                    params = {
                        'page': page, 'num': 50,
                        'sort': 'changepercent', 'asc': 0,
                        'node': sector_code,
                        '_s_r_a': 'page'
                    }
                    r = session.get(url, params=params,
                                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                                            'Referer': 'https://finance.sina.com.cn/'}, timeout=10)
                    r.encoding = 'utf-8'
                    page_stocks = r.json()
                    if not page_stocks:
                        break
                    all_stocks.extend(page_stocks)
                
                for item in all_stocks:
                    try:
                        name = item.get('name', '')
                        if 'ST' in name or '*' in name:
                            continue
                        code = item.get('code', '')
                        price = float(item.get('trade', 0) or 0)
                        if price <= 0 or not code:
                            continue
                        pe_raw = item.get('per', 0) or 0
                        pe_val = 0
                        if pe_raw and pe_raw != '-' and float(pe_raw) > 0 and float(pe_raw) < 10000:
                            pe_val = float(pe_raw)
                        pb_raw = item.get('pb', 0) or 0
                        pb_val = 0
                        if pb_raw and pb_raw != '-':
                            try: pb_val = float(pb_raw)
                            except: pb_val = 0
                        stocks.append({
                            "code": code, "name": name, "price": price,
                            "change_pct": float(item.get('changepercent', 0) or 0),
                            "amount": float(item.get('amount', 0) or 0),
                            "pe": pe_val, "pb": pb_val, "roe": 0, "gross_margin": 0,
                            "market_cap": float(item.get('nmc', 0) or 0),
                        })
                    except:
                        continue
            except Exception as e:
                print(f"  新浪板块API失败: {e}")

            if stocks:
                stocks.sort(key=lambda x: x["change_pct"], reverse=True)
                return jsonify({"success": True, "sector_name": sector_name, "stocks": stocks[:50], "total": len(stocks)})
            else:
                return jsonify({"success": False, "error": "无法获取板块成分股"}), 500

        # ---- 东方财富BK代码方案 ----
        # 先尝试从push2 clist/get获取（如果恢复的话）
        try:
            url = "https://push2.eastmoney.com/api/qt/clist/get"
            params = {
                "pn": 1, "pz": 20, "po": 1, "np": 1,
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": 2, "invt": 2, "fid": "f3",
                "fs": f"b:{sector_code}+f:!50",
                "fields": "f2,f3,f12,f14,f20,f162,f167"
            }
            resp = session.get(url, params=params, headers=EM_HEADERS, timeout=5)
            data = resp.json()
            if data.get("data") and data["data"].get("diff"):
                for item in data["data"]["diff"]:
                    try:
                        code = str(item.get("f12", ""))
                        name = item.get("f14", "")
                        if "ST" in name or "*" in name:
                            continue
                        price = float(item.get("f2", 0))
                        if price <= 0:
                            continue
                        pe_raw = item.get("f162", 0) or item.get("f9", 0)
                        pe_val = 0
                        if pe_raw and pe_raw != "-":
                            try: pe_val = float(pe_raw)
                            except: pe_val = 0
                        pb_raw = item.get("f167", 0) or item.get("f23", 0)
                        pb_val = 0
                        if pb_raw and pb_raw != "-":
                            try: pb_val = float(pb_raw)
                            except: pb_val = 0
                        stocks.append({
                            "code": code, "name": name, "price": price,
                            "change_pct": float(item.get("f3", 0)),
                            "amount": float(item.get("f6", 0)) if item.get("f6", 0) else 0,
                            "pe": pe_val, "pb": pb_val, "roe": 0, "gross_margin": 0,
                            "market_cap": float(item.get("f20", 0)) / 100000000 if item.get("f20", 0) > 0 else 0,
                        })
                    except:
                        continue
                if stocks:
                    stocks.sort(key=lambda x: x["change_pct"], reverse=True)
                    return jsonify({"success": True, "sector_name": sector_name, "stocks": stocks[:20], "total": len(stocks)})
        except:
            pass  # clist/get被拒，用备选方案

        # 备选方案：用datacenter-web获取成分股代码，然后用腾讯API获取行情
        print(f"  clist/get blocked, getting sector {sector_code} stocks...")
        try:
            dc_params = {
                'reportName': 'RPT_INDUSTRY_INDEX',
                'columns': 'BOARD_CODE,SECURITY_CODE,INDICATOR_VALUE',
                'filter': f'(BOARD_CODE="{sector_code}")',
                'pageNumber': 1, 'pageSize': 25,
                'source': 'WEB', 'client': 'WEB',
            }
            resp = session.get('https://datacenter-web.eastmoney.com/api/data/v1/get',
                                params=dc_params, headers=DC_HEADERS, timeout=10)
            d = resp.json()
            member_codes = []
            if d.get('success') and d.get('result') and d['result'].get('data'):
                for item in d['result']['data']:
                    sc = item.get('SECURITY_CODE', '')
                    if sc and len(sc) == 6:
                        member_codes.append(sc)

            if member_codes:
                tx_codes = [f"sh{c}" if c.startswith('6') else f"sz{c}" for c in member_codes]
                url = 'http://qt.gtimg.cn/q=' + ','.join(tx_codes)
                tx_resp = session.get(url, timeout=15)
                lines = tx_resp.text.strip().split(';')
                for line in lines:
                    if not line.strip():
                        continue
                    parts = line.split('~')
                    if len(parts) < 50:
                        continue
                    code = parts[2]
                    try:
                        price = float(parts[3]) if parts[3] else 0
                        if price <= 0: continue
                        stocks.append({
                            "code": code, "name": parts[1], "price": price,
                            "change_pct": float(parts[32]) if parts[32] else 0,
                            "amount": float(parts[43]) * 10000 if parts[43] else 0,
                            "pe": float(parts[39]) if parts[39] and parts[39] != '-' and float(parts[39]) < 10000 else 0,
                            "pb": 0, "roe": 0, "gross_margin": 0,
                            "market_cap": float(parts[44]) if parts[44] else 0,
                        })
                    except:
                        continue

            stocks.sort(key=lambda x: x["change_pct"], reverse=True)
        except Exception as e2:
            print(f"  备选方案也失败: {e2}")

        if stocks:
            stocks.sort(key=lambda x: x["change_pct"], reverse=True)
            return jsonify({
                "success": True,
                "sector_name": sector_name,
                "stocks": stocks[:20],
                "total": len(stocks),
            })
        else:
            return jsonify({"success": False, "error": "无法获取板块成分股"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/market')
def api_market():
    """获取全市场概览"""
    stocks = get_realtime_quotes()
    
    # 离线模式：使用预设数据
    if not stocks or len(stocks) < 50:
        print("⚠️ 市场概览：实时行情获取失败，启用离线模式")
        preset = get_preset_financials()
        stocks = []
        for code, fin in preset.items():
            stocks.append({
                "code": code,
                "name": fin["name"],
                "price": fin.get("price", 0),
                "change_pct": fin.get("change_pct", 0),
                "amount": fin.get("market_cap", 0) * 100000000,  # 市值转成交额（模拟）
            })
    
    if not stocks:
        return jsonify({"success": False, "error": "无法获取市场数据"})

    total = len(stocks)
    up_count = len([s for s in stocks if s["change_pct"] > 0])
    down_count = len([s for s in stocks if s["change_pct"] < 0])
    flat_count = total - up_count - down_count
    avg_change = sum(s["change_pct"] for s in stocks) / total if total else 0

    # 涨幅前10
    top_gainers = sorted(stocks, key=lambda x: x["change_pct"], reverse=True)[:10]
    # 跌幅前10
    top_losers = sorted(stocks, key=lambda x: x["change_pct"])[:10]
    # 成交额前10
    top_volume = sorted(stocks, key=lambda x: x.get("amount", 0), reverse=True)[:10]

    return jsonify({
        "success": True,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total": total,
            "up": up_count,
            "down": down_count,
            "flat": flat_count,
            "avg_change": round(avg_change, 2),
        },
        "top_gainers": [{"code": s["code"], "name": s["name"], "price": s["price"], "change_pct": s["change_pct"], "amount": s.get("amount", 0)} for s in top_gainers],
        "top_losers": [{"code": s["code"], "name": s["name"], "price": s["price"], "change_pct": s["change_pct"], "amount": s.get("amount", 0)} for s in top_losers],
        "top_volume": [{"code": s["code"], "name": s["name"], "price": s["price"], "change_pct": s["change_pct"], "amount": s.get("amount", 0)} for s in top_volume],
    })

@app.route('/api/search_stock')
def api_search_stock():
    """搜索全市场股票（支持名称或代码模糊匹配）
    
    2026-04-02: push2和searchapi全被封，改用腾讯API + 东方财富财务数据中心
    - 代码搜索: 腾讯API直接查行情
    - 名称搜索: 东方财富智能搜索(smartbox)获取候选，腾讯API获取行情
    - 财务数据: 东方财富datacenter-web
    """
    query = request.args.get("q", "").strip()
    if not query or len(query) < 1:
        return jsonify({"success": False, "error": "请输入搜索关键词"}), 400

    try:
        matched_stocks = []
        tx_headers = {'User-Agent': 'Mozilla/5.0'}
        dc_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://data.eastmoney.com/'
        }

        # 1. 名称搜索：东方财富smartbox接口
        if not query.isdigit() or len(query) >= 2:
            try:
                smartbox_url = "https://searchapi.eastmoney.com/api/suggest/get"
                smartbox_params = {
                    "input": query,
                    "type": "14",
                    "token": "D43BF722C8E33BDC906FB84D85E326E8",
                    "count": 10,
                }
                resp = session.get(smartbox_url, params=smartbox_params,
                                    headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://so.eastmoney.com/'},
                                    timeout=10)
                data = resp.json()
                if data.get("QuotationCodeTable") and data["QuotationCodeTable"].get("Data"):
                    for item in data["QuotationCodeTable"]["Data"][:10]:
                        try:
                            code = str(item.get("Code", ""))
                            name = item.get("Name", "")
                            classify = item.get("Classify", "")
                            if not code or not name or classify != "AStock":
                                continue
                            if "ST" in name or "*" in name:
                                continue
                            if code.startswith('8') or code.startswith('4') or code.startswith('920'):
                                continue
                            matched_stocks.append({"code": code, "name": name})
                        except:
                            continue
            except Exception as e:
                print(f"Smartbox搜索失败: {e}")

        # 2. 代码搜索：如果输入是纯数字
        if query.isdigit():
            code = query.zfill(6)
            if code not in [s["code"] for s in matched_stocks]:
                # 判断市场后缀
                tx_code = f"sh{code}" if code.startswith('6') else f"sz{code}"
                matched_stocks.append({"code": code, "name": ""})

        # 3. 批量获取行情：用腾讯API
        if matched_stocks:
            tx_codes = []
            for s in matched_stocks:
                c = s["code"]
                tx_codes.append(f"sh{c}" if c.startswith('6') else f"sz{c}")

            # 腾讯API每批80只
            for i in range(0, len(tx_codes), 80):
                batch = tx_codes[i:i+80]
                try:
                    url = 'http://qt.gtimg.cn/q=' + ','.join(batch)
                    resp = session.get(url, timeout=15)
                    lines = resp.text.strip().split(';')
                    for line in lines:
                        if not line.strip():
                            continue
                        parts = line.split('~')
                        if len(parts) < 50:
                            continue
                        code = parts[2]
                        if not code or len(code) != 6:
                            continue
                        try:
                            price = float(parts[3]) if parts[3] else 0
                        except:
                            price = 0
                        if price <= 0:
                            continue
                        try:
                            change_pct = float(parts[32]) if parts[32] else 0
                        except:
                            change_pct = 0
                        try:
                            pe = float(parts[39]) if parts[39] and parts[39] != '-' else 0
                            if pe > 10000 or pe < 0: pe = 0
                        except:
                            pe = 0
                        try:
                            total_cap_yi = float(parts[44]) if parts[44] else 0
                        except:
                            total_cap_yi = 0
                        try:
                            high = float(parts[33]) if parts[33] else 0
                        except:
                            high = 0
                        try:
                            low = float(parts[34]) if parts[34] else 0
                        except:
                            low = 0
                        try:
                            open_p = float(parts[5]) if parts[5] else 0
                        except:
                            open_p = 0
                        try:
                            prev_close = float(parts[4]) if parts[4] else 0
                        except:
                            prev_close = 0
                        try:
                            volume_gu = float(parts[37]) if parts[37] else 0
                        except:
                            volume_gu = 0
                        try:
                            amount_wan = float(parts[43]) if parts[43] else 0
                        except:
                            amount_wan = 0

                        # 更新matched_stocks中的行情数据
                        for ms in matched_stocks:
                            if ms["code"] == code:
                                ms.update({
                                    "name": parts[1] or ms["name"],
                                    "price": price, "change_pct": change_pct,
                                    "volume": volume_gu, "amount": amount_wan * 10000,
                                    "market_cap": total_cap_yi * 100000000,
                                    "pe": pe, "pb": 0,
                                    "high": high, "low": low, "open": open_p, "prev_close": prev_close,
                                })
                                break
                except Exception as e:
                    print(f"腾讯API搜索行情失败: {e}")

        # 过滤掉没获取到行情的
        matched_stocks = [s for s in matched_stocks if s.get("price", 0) > 0]

        # 4. 补充PB：用腾讯API的PB字段(parts[46])
        # 腾讯API parts[46]有时候是PB
        for ms in matched_stocks:
            if ms.get("pb", 0) == 0 and ms.get("pe", 0) > 0:
                # 腾讯API没有可靠的PB字段，尝试从东方财富datacenter获取
                pass

        # 5. 用财务数据中心补充ROE/毛利率/增速
        for stock in matched_stocks:
            fin_data = get_financial_data(stock["code"])
            if fin_data:
                stock["roe"] = fin_data.get("roe", 0)
                stock["gross_margin"] = fin_data.get("gross_margin", 0)
                stock["rev_growth"] = fin_data.get("rev_growth", 0)
                stock["profit_growth"] = fin_data.get("profit_growth", 0)
            else:
                stock["roe"] = 0
                stock["gross_margin"] = 0
                stock["rev_growth"] = 0
                stock["profit_growth"] = 0
            stock.setdefault("net_margin", 0)
            stock.setdefault("debt_ratio", 0)

            # 预设数据补充
            preset = get_preset_financials()
            code = stock["code"]
            if code in preset:
                fin = preset[code]
                for k in ["roe", "gross_margin", "net_margin", "rev_growth", "profit_growth", "pb"]:
                    if stock.get(k, 0) == 0 and fin.get(k):
                        stock[k] = fin[k]

        # 6. 五维评估
        results = []
        for stock in matched_stocks:
            r = evaluate_stock(stock)
            if r:
                results.append(r)
            else:
                results.append({
                    "code": stock["code"], "name": stock["name"],
                    "price": stock.get("price", 0), "change_pct": stock.get("change_pct", 0),
                    "pe": stock.get("pe", 0), "pb": stock.get("pb", 0),
                    "roe": stock.get("roe", 0), "gross_margin": stock.get("gross_margin", 0),
                    "net_margin": stock.get("net_margin", 0),
                    "rev_growth": stock.get("rev_growth", 0), "profit_growth": stock.get("profit_growth", 0),
                    "market_cap": stock.get("market_cap", 0) / 100000000 if stock.get("market_cap", 0) > 0 else 0,
                    "score": 0,
                    "dimensions": {"profitability": 0, "growth": 0, "health": 0, "valuation": 0, "cashflow": 0},
                    "reasons": [], "buy_sell": None,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return jsonify({
            "success": True,
            "query": query,
            "results": results,
            "total_matched": len(matched_stocks),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/daily_pick')
def daily_pick():
    """每日推荐页面 - 展示早盘和午盘选股结果"""
    return render_template('daily_pick.html')

@app.route('/api/daily_pick')
def api_daily_pick():
    """获取每日推荐数据"""
    global DAILY_PICK_DATA

    with DAILY_PICK_LOCK:
        data = DAILY_PICK_DATA.copy()

    # 如果没有任何数据，尝试执行一次选股
    if not data.get('morning') and not data.get('afternoon'):
        # 判断当前时间段
        now = datetime.now()
        current_hour = now.hour

        if current_hour >= 14:
            # 下午时段，执行午盘选股
            execute_daily_pick('afternoon')
            # 如果上午还没选，也执行一次
            if not DAILY_PICK_DATA.get('morning'):
                execute_daily_pick('morning')
        elif current_hour >= 9:
            # 上午时段，执行早盘选股
            execute_daily_pick('morning')

        with DAILY_PICK_LOCK:
            data = DAILY_PICK_DATA.copy()

    # 确保 debt_ratio 字段存在
    for session in ['morning', 'afternoon']:
        if data.get(session) and data[session].get('results'):
            for stock in data[session]['results']:
                if 'debt_ratio' not in stock:
                    stock['debt_ratio'] = 0

    return jsonify({
        "success": True,
        "date": data.get('date', datetime.now().strftime('%Y-%m-%d')),
        "morning": data.get('morning'),
        "afternoon": data.get('afternoon'),
        "last_update": data.get('last_update'),
    })

@app.route('/api/daily_pick/refresh')
def api_daily_pick_refresh():
    """手动刷新每日推荐"""
    session_type = request.args.get('session', 'auto')

    if session_type == 'auto':
        # 自动判断：下午执行午盘，上午执行早盘
        current_hour = datetime.now().hour
        session_type = 'afternoon' if current_hour >= 14 else 'morning'

    if session_type not in ['morning', 'afternoon']:
        return jsonify({"success": False, "error": "无效的session参数，请使用morning或afternoon"}), 400

    execute_daily_pick(session_type)

    return jsonify({
        "success": True,
        "message": f"{'早盘' if session_type == 'morning' else '午盘'}选股已完成",
        "session_type": session_type,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

@app.route('/api/stock_detail')
def api_stock_detail():
    """获取单个股票详情 + 相关新闻"""
    """获取单个股票详情 + 相关新闻"""
    code = request.args.get("code", "")
    if not code:
        return jsonify({"success": False, "error": "缺少股票代码"}), 400

    # 优先从缓存中获取该股票的选股数据（保持评分一致）
    cached_stock = None
    with DAILY_PICK_LOCK:
        for pick_session in ['morning', 'afternoon']:
            session_data = DAILY_PICK_DATA.get(pick_session, {})
            if session_data and session_data.get('results'):
                for s in session_data['results']:
                    if s.get('code') == code:
                        cached_stock = s.copy()
                        break
            if cached_stock:
                break

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/"
    }

    # 判断市场：深圳股票用0.前缀，上海股票用1.前缀
    if code.startswith('6'):
        secid = f"1.{code}"
    else:  # 深圳（000/002/300开头）
        secid = f"0.{code}"

    stock_info = None
    # 1. 获取实时行情 - 优先腾讯API（push2已被封）
    try:
        tx_code = f"sh{code}" if code.startswith('6') else f"sz{code}"
        url = f'http://qt.gtimg.cn/q={tx_code}'
        tx_resp = session.get(url, timeout=10)
        lines = tx_resp.text.strip().split(';')
        for line in lines:
            if not line.strip():
                continue
            # 处理腾讯 API 返回格式: v_sz300015="51~爱尔眼科~..."
            if '=' in line:
                line = line.split('=', 1)[1].strip('"')
            parts = line.split('~')
            if len(parts) < 50:
                continue
            try:
                price = float(parts[3]) if parts[3] else 0
                if price <= 0:
                    continue
                pe_val = 0
                if parts[39] and parts[39] != '-':
                    pe_val = float(parts[39])
                    if pe_val > 10000 or pe_val < 0:
                        pe_val = 0
                stock_info = {
                    "code": code,
                    "name": parts[1],
                    "price": price,
                    "change_pct": float(parts[32]) if parts[32] else 0,
                    "high": float(parts[33]) if parts[33] else 0,
                    "low": float(parts[34]) if parts[34] else 0,
                    "open": float(parts[5]) if parts[5] else 0,
                    "prev_close": float(parts[4]) if parts[4] else 0,
                    "volume": float(parts[37]) if parts[37] else 0,
                    "amount": float(parts[43]) * 10000 if parts[43] else 0,
                    "pe": pe_val,
                    "pb": 0,
                    "roe": 0,
                    "gross_margin": 0,
                    "net_margin": 0,
                    "rev_growth": 0,
                    "profit_growth": 0,
                    "debt_ratio": 0,
                    "market_cap": float(parts[44]) if parts[44] else 0,
                    "main_net_flow": 0,
                }
                break
            except:
                continue
    except Exception as e:
        print(f"腾讯API获取股票行情失败: {e}")

    # 从预设财务数据补充缺失的财务指标
    if stock_info:
        preset = get_preset_financials()
        if code in preset:
            fin = preset[code]
            if stock_info.get("roe", 0) == 0 and fin.get("roe"):
                stock_info["roe"] = fin.get("roe", 0)
            if stock_info.get("gross_margin", 0) == 0 and fin.get("gross_margin"):
                stock_info["gross_margin"] = fin.get("gross_margin", 0)
            if stock_info.get("net_margin", 0) == 0 and fin.get("net_margin"):
                stock_info["net_margin"] = fin.get("net_margin", 0)
            if stock_info.get("rev_growth", 0) == 0 and fin.get("rev_growth"):
                stock_info["rev_growth"] = fin.get("rev_growth", 0)
            if stock_info.get("profit_growth", 0) == 0 and fin.get("profit_growth"):
                stock_info["profit_growth"] = fin.get("profit_growth", 0)
            if stock_info.get("pb", 0) == 0 and fin.get("pb"):
                stock_info["pb"] = fin["pb"]
            if stock_info.get("pe", 0) == 0 and fin.get("pe"):
                stock_info["pe"] = fin["pe"]

        # 优先从财务数据中心校准关键指标（ROE/营收增速/净利增速/毛利率/资产负债率/净利率）
        fin_data = get_financial_data(code)
        if fin_data:
            # ROE: 财务数据中心年报ROE比行情API更准确, 直接覆盖
            if fin_data.get("roe", 0) != 0:
                stock_info["roe"] = fin_data["roe"]
            if stock_info.get("gross_margin", 0) == 0 and fin_data.get("gross_margin", 0) != 0:
                stock_info["gross_margin"] = fin_data["gross_margin"]
            if stock_info.get("rev_growth", 0) == 0 and fin_data.get("rev_growth", 0) != 0:
                stock_info["rev_growth"] = fin_data["rev_growth"]
            if stock_info.get("profit_growth", 0) == 0 and fin_data.get("profit_growth", 0) != 0:
                stock_info["profit_growth"] = fin_data["profit_growth"]
            # 资产负债率（关键！之前一直缺失导致财务健康=0）
            if fin_data.get("debt_ratio", 0) != 0:
                stock_info["debt_ratio"] = fin_data["debt_ratio"]
            # 净利率
            if fin_data.get("net_margin", 0) != 0:
                stock_info["net_margin"] = fin_data["net_margin"]

        # 通用反推：如果PE无效但PB和ROE有效，用PB/ROE估算PE
        if stock_info.get("pe", 0) == 0 and stock_info.get("pb", 0) > 0 and stock_info.get("roe", 0) > 0:
            stock_info["pe"] = round(stock_info["pb"] / (stock_info["roe"] / 100), 1)

    # 如果实时数据获取失败，但有缓存数据，使用缓存数据
    if not stock_info and cached_stock:
        stock_info = {
            "code": cached_stock.get("code", code),
            "name": cached_stock.get("name", ""),
            "price": cached_stock.get("price", 0),
            "change_pct": cached_stock.get("change_pct", 0),
            "high": cached_stock.get("high", 0),
            "low": cached_stock.get("low", 0),
            "open": cached_stock.get("open", 0),
            "prev_close": cached_stock.get("prev_close", 0),
            "volume": cached_stock.get("volume", 0),
            "amount": cached_stock.get("amount", 0),
            "pe": cached_stock.get("pe", 0),
            "pb": cached_stock.get("pb", 0),
            "roe": cached_stock.get("roe", 0),
            "gross_margin": cached_stock.get("gross_margin", 0),
            "net_margin": cached_stock.get("net_margin", 0),
            "rev_growth": cached_stock.get("rev_growth", 0),
            "profit_growth": cached_stock.get("profit_growth", 0),
            "debt_ratio": cached_stock.get("debt_ratio", 0),
            "market_cap": cached_stock.get("market_cap", 0),
        }

    if not stock_info:
        return jsonify({"success": False, "error": "股票不存在或无法获取数据"}), 404

    # 2. 评分计算：优先使用缓存数据（保持与首页/每日推荐一致）
    if cached_stock:
        # 使用缓存的评分和维度数据
        score = cached_stock.get("score", 0)
        dimensions = cached_stock.get("dimensions", {"profitability": 0, "growth": 0, "health": 0, "valuation": 0, "cashflow": 0})
        # 用缓存的财务数据覆盖实时数据中的财务指标（保持一致）
        for key in ["roe", "gross_margin", "net_margin", "rev_growth", "profit_growth", "debt_ratio"]:
            if cached_stock.get(key):
                stock_info[key] = cached_stock[key]
    else:
        # 没有缓存数据，重新计算评分
        eval_result = evaluate_stock(stock_info)
        score = eval_result["score"] if eval_result else 0
        dimensions = eval_result["dimensions"] if eval_result else {"profitability": 0, "growth": 0, "health": 0, "valuation": 0, "cashflow": 0}

    analysis = []

    # 构建分析详情（供详情页展示）
    roe = stock_info.get("roe", 0)
    gross_margin = stock_info.get("gross_margin", 0)
    net_margin = stock_info.get("net_margin", 0)
    rev_growth = stock_info.get("rev_growth", 0)
    profit_growth = stock_info.get("profit_growth", 0)
    pe = stock_info.get("pe", 0)
    pb = stock_info.get("pb", 0)
    debt_ratio = stock_info.get("debt_ratio", 0)
    market_cap_yi = stock_info.get("market_cap", 0)

    # 盈利能力分析
    if roe >= 20:
        analysis.append({"dim": "盈利能力", "score": round(dimensions["profitability"]), "max": 35, "detail": f"ROE {roe:.1f}% 优秀（≥20%）", "level": "excellent"})
    elif roe >= 15:
        analysis.append({"dim": "盈利能力", "score": round(dimensions["profitability"]), "max": 35, "detail": f"ROE {roe:.1f}% 良好（≥15%）", "level": "good"})
    elif roe > 0:
        analysis.append({"dim": "盈利能力", "score": round(dimensions["profitability"]), "max": 35, "detail": f"ROE {roe:.1f}% 一般", "level": "fair"})
    else:
        analysis.append({"dim": "盈利能力", "score": 0, "max": 35, "detail": "ROE数据缺失", "level": "unknown"})

    if gross_margin >= 40:
        analysis.append({"dim": "毛利率", "score": "+8", "max": 35, "detail": f"毛利率 {gross_margin:.1f}% 优秀（≥40%）", "level": "excellent"})
    elif gross_margin > 0:
        analysis.append({"dim": "毛利率", "score": "+3", "max": 35, "detail": f"毛利率 {gross_margin:.1f}%", "level": "fair"})

    if net_margin >= 15:
        analysis.append({"dim": "净利率", "score": "+5", "max": 35, "detail": f"净利率 {net_margin:.1f}% 优秀（≥15%）", "level": "excellent"})

    # 成长性分析
    if rev_growth > 0 and profit_growth > 0:
        avg_growth = (rev_growth + profit_growth) / 2
    elif rev_growth > 0:
        avg_growth = rev_growth
    elif profit_growth > 0:
        avg_growth = profit_growth
    else:
        avg_growth = 0

    if avg_growth >= 20:
        analysis.append({"dim": "成长性", "score": 25, "max": 25, "detail": f"平均增速 {avg_growth:.1f}% 优秀（≥20%）", "level": "excellent"})
    elif avg_growth >= 15:
        analysis.append({"dim": "成长性", "score": 20, "max": 25, "detail": f"平均增速 {avg_growth:.1f}% 良好（≥15%）", "level": "good"})
    elif avg_growth >= 10:
        analysis.append({"dim": "成长性", "score": 15, "max": 25, "detail": f"平均增速 {avg_growth:.1f}% 一般（≥10%）", "level": "fair"})
    elif avg_growth > 0:
        analysis.append({"dim": "成长性", "score": 8, "max": 25, "detail": f"平均增速 {avg_growth:.1f}% 较低", "level": "poor"})
    else:
        analysis.append({"dim": "成长性", "score": 0, "max": 25, "detail": "成长性数据缺失", "level": "unknown"})

    # 财务健康分析
    if debt_ratio > 0 and debt_ratio < 1000:
        if debt_ratio <= 50:
            analysis.append({"dim": "财务健康", "score": 20, "max": 20, "detail": f"资产负债率 {debt_ratio:.1f}% 优秀（≤50%）", "level": "excellent"})
        elif debt_ratio <= 70:
            analysis.append({"dim": "财务健康", "score": 12, "max": 20, "detail": f"资产负债率 {debt_ratio:.1f}% 一般（≤70%）", "level": "fair"})
        else:
            analysis.append({"dim": "财务健康", "score": 5, "max": 20, "detail": f"资产负债率 {debt_ratio:.1f}% 偏高", "level": "poor"})
    else:
        analysis.append({"dim": "财务健康", "score": 10, "max": 20, "detail": "资产负债率数据缺失，给中等分", "level": "unknown"})

    # 估值分析
    if pe > 0 and pe < 1000:
        if pe <= 12:  # 优化：15 -> 12
            analysis.append({"dim": "估值", "score": round(dimensions["valuation"]), "max": 20, "detail": f"PE {pe:.1f} 低估（≤15）", "level": "excellent"})
        elif pe <= 20:  # 优化：25 -> 20
            analysis.append({"dim": "估值", "score": round(dimensions["valuation"]), "max": 20, "detail": f"PE {pe:.1f} 合理（≤25）", "level": "good"})
        elif pe <= 35:
            analysis.append({"dim": "估值", "score": round(dimensions["valuation"]), "max": 20, "detail": f"PE {pe:.1f} 偏高（≤35）", "level": "fair"})
        elif pe <= 50:
            analysis.append({"dim": "估值", "score": round(dimensions["valuation"]), "max": 20, "detail": f"PE {pe:.1f} 偏高（≤50）", "level": "poor"})
        else:
            analysis.append({"dim": "估值", "score": round(dimensions["valuation"]), "max": 20, "detail": f"PE {pe:.1f} 高估", "level": "poor"})
    else:
        analysis.append({"dim": "估值", "score": 8, "max": 20, "detail": "无PE数据，成长股给予中等分", "level": "unknown"})

    if 0 < pb <= 3:
        analysis.append({"dim": "市净率", "score": "+5", "max": 20, "detail": f"PB {pb:.2f} 低估（≤3）", "level": "excellent"})
    elif 3 < pb <= 5:
        analysis.append({"dim": "市净率", "score": "+2", "max": 20, "detail": f"PB {pb:.2f} 合理", "level": "good"})

    # 现金流质量分析
    if pe > 0 and roe > 15:
        if pe <= 20:
            analysis.append({"dim": "现金流质量", "score": 5, "max": 5, "detail": f"PE {pe:.1f} + ROE {roe:.1f}% 现金流充裕", "level": "excellent"})
        elif pe <= 30:
            analysis.append({"dim": "现金流质量", "score": 4, "max": 5, "detail": f"PE {pe:.1f} + ROE {roe:.1f}% 盈利质量良好", "level": "good"})
        elif pe <= 45:
            analysis.append({"dim": "现金流质量", "score": 2, "max": 5, "detail": f"PE {pe:.1f} + ROE {roe:.1f}% 盈利质量一般", "level": "fair"})
        else:
            analysis.append({"dim": "现金流质量", "score": 1, "max": 5, "detail": f"PE {pe:.1f} 偏高 利润含金量待验证", "level": "poor"})
    elif pe > 0 and roe > 0:
        if pe <= 20:
            analysis.append({"dim": "现金流质量", "score": 3, "max": 5, "detail": f"PE {pe:.1f} 低估值 盈利较真实", "level": "good"})
        elif pe <= 35:
            analysis.append({"dim": "现金流质量", "score": 1, "max": 5, "detail": f"PE {pe:.1f} 盈利质量一般", "level": "fair"})
        else:
            analysis.append({"dim": "现金流质量", "score": 0, "max": 5, "detail": "数据不足", "level": "unknown"})
    else:
        analysis.append({"dim": "现金流质量", "score": 0, "max": 5, "detail": "盈利数据不足", "level": "unknown"})

    # 买卖点：优先使用缓存数据
    if cached_stock and cached_stock.get("buy_sell"):
        buy_sell = cached_stock["buy_sell"]
    else:
        buy_sell = calculate_buy_sell(stock_info, score)

    stock_news = []
    try:
        # 东方财富新闻API已挂，改用新浪财经
        r = session.get("https://feed.mix.sina.com.cn/api/roll/get",
                         params={"pageid": "153", "lid": "2509", "k": "", "r": "0.5", "page": 1},
                         headers=HEADERS, timeout=10)
        d = r.json()
        if d.get('result') and d['result'].get('data'):
            keyword = stock_info["name"]
            for item in d['result']['data'][:30]:
                title = item.get('title', '')
                intro = item.get('intro', '') or ''
                text = title + ' ' + intro
                if keyword in text:
                    impact = "关注"
                    if any(w in text for w in ["上涨", "增长", "突破", "超预期", "利好", "大涨", "暴涨"]):
                        impact = "利好"
                    elif any(w in text for w in ["下跌", "亏损", "下滑", "收紧", "暴跌", "利空"]):
                        impact = "利空"
                    stock_news.append({
                        "title": title,
                        "time": item.get('ctime', ''),
                        "source": item.get('media_name', ''),
                        "summary": intro,
                        "impact": impact,
                    })
    except Exception as e:
        print(f"获取相关新闻失败: {e}")

    return jsonify({
        "success": True,
        "stock": stock_info,
        "score": score,
        "dimensions": dimensions,
        "analysis": analysis,
        "buy_sell": buy_sell,
        "news": stock_news[:8],
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

if __name__ == '__main__':
    print("\n🏛️ 价值投资之王 · 智能选股可视化网站 v14-DEBT-RATIO-FIXED")
    print("   访问 http://localhost:5557")
    print("   每日推荐: 自动选股 9:26(早盘) / 14:30(午盘)")

    # 加载缓存
    load_daily_pick_cache()

    # 启动定时任务
    start_scheduler()

    # 注册退出时保存
    atexit.register(save_daily_pick_cache)

    app.run(host='0.0.0.0', port=5557, debug=False)
