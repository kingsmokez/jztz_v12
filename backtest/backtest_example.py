# -*- coding: utf-8 -*-
"""
价值投资之王 - 回测引擎使用示例
演示如何使用回测引擎进行策略验证
"""
import sys
import json
from datetime import datetime, timedelta

# Windows 控制台编码处理
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

from backtest_engine_v2 import BacktestEngine, Order, DataFetcher


# ==================== 策略示例 1: 低 PE 策略 ====================
def low_pe_strategy(engine, date, stock_data_cache, current_prices):
    """
    低 PE 策略
    规则：
    1. 选择 PE<20 的股票
    2. ROE>15%
    3. 等权重配置
    4. 每月调仓
    """
    orders = []
    day = int(date.split("-")[2])
    
    # 卖出持有超过 30 天的股票
    for code, pos in list(engine.positions.items()):
        if pos.buy_date:
            days = (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(pos.buy_date, "%Y-%m-%d")).days
            if days >= 30:
                orders.append(Order(code=code, name=pos.name, order_type=Order.SELL,
                                   shares=pos.shares, price=current_prices.get(code, 0),
                                   date=date, reason="持有 30 天到期"))
    
    # 调仓日买入
    if day == 1 and engine.cash > engine.initial_capital * 0.2:
        candidates = []
        for code in stock_data_cache.keys():
            if code in engine.positions:
                continue
            fin = DataFetcher.get_financial_data(code)
            quote = DataFetcher.get_realtime_quote(code)
            pe = quote.get("pe_ttm", 999) if quote else 999
            roe = fin.get("roe", 0)
            
            if pe > 0 and pe < 20 and roe > 15:
                candidates.append({"code": code, "name": quote.get("name", "") if quote else "",
                                  "pe": pe, "roe": roe})
        
        candidates.sort(key=lambda x: x["pe"])
        top = candidates[:5]
        
        if top:
            size = engine.cash * 0.8 / len(top)
            for s in top:
                price = current_prices.get(s["code"], 0)
                if price <= 0:
                    continue
                shares = int(size / price / 100) * 100
                if shares >= 100:
                    orders.append(Order(code=s["code"], name=s["name"], order_type=Order.BUY,
                                       shares=shares, price=price, date=date,
                                       reason=f"PE={s['pe']:.1f} ROE={s['roe']:.1f}%"))
    
    return orders


# ==================== 策略示例 2: 高成长策略 ====================
def high_growth_strategy(engine, date, stock_data_cache, current_prices):
    """
    高成长策略
    规则：
    1. 营收增速>30%
    2. 净利增速>30%
    3. ROE>15%
    4. 持有 60 天
    """
    orders = []
    
    # 卖出持有超过 60 天的股票
    for code, pos in list(engine.positions.items()):
        if pos.buy_date:
            days = (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(pos.buy_date, "%Y-%m-%d")).days
            if days >= 60:
                orders.append(Order(code=code, name=pos.name, order_type=Order.SELL,
                                   shares=pos.shares, price=current_prices.get(code, 0),
                                   date=date, reason="持有 60 天到期"))
    
    # 每月初买入
    day = int(date.split("-")[2])
    if day == 1 and engine.cash > engine.initial_capital * 0.2:
        candidates = []
        for code in stock_data_cache.keys():
            if code in engine.positions:
                continue
            fin = DataFetcher.get_financial_data(code)
            rev_g = fin.get("rev_growth", 0)
            profit_g = fin.get("profit_growth", 0)
            roe = fin.get("roe", 0)
            
            if rev_g > 30 and profit_g > 30 and roe > 15:
                quote = DataFetcher.get_realtime_quote(code)
                candidates.append({"code": code, "name": quote.get("name", "") if quote else "",
                                  "rev_g": rev_g, "profit_g": profit_g, "roe": roe})
        
        candidates.sort(key=lambda x: x["rev_g"], reverse=True)
        top = candidates[:5]
        
        if top:
            size = engine.cash * 0.9 / len(top)
            for s in top:
                price = current_prices.get(s["code"], 0)
                if price <= 0:
                    continue
                shares = int(size / price / 100) * 100
                if shares >= 100:
                    orders.append(Order(code=s["code"], name=s["name"], order_type=Order.BUY,
                                       shares=shares, price=price, date=date,
                                       reason=f"营收增{ s['rev_g']:.1f}% 净利增{s['profit_g']:.1f}%"))
    
    return orders


# ==================== 策略示例 3: 五维价值策略 ====================
def five_dim_strategy(engine, date, stock_data_cache, current_prices):
    """
    五维价值策略（完整版）
    规则：
    1. ROE>20% (35 分)
    2. 毛利率>40% (8 分)
    3. 净利率>15% (5 分)
    4. 营收增速>15% (25 分)
    5. PE<30 (20 分)
    6. 总分>60 才买入
    7. 持有 45 天
    """
    orders = []
    
    # 卖出持有超过 45 天的股票
    for code, pos in list(engine.positions.items()):
        if pos.buy_date:
            days = (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(pos.buy_date, "%Y-%m-%d")).days
            if days >= 45:
                orders.append(Order(code=code, name=pos.name, order_type=Order.SELL,
                                   shares=pos.shares, price=current_prices.get(code, 0),
                                   date=date, reason="持有 45 天到期"))
    
    # 每月初调仓
    day = int(date.split("-")[2])
    if day == 1 and engine.cash > engine.initial_capital * 0.2:
        candidates = []
        for code in stock_data_cache.keys():
            if code in engine.positions:
                continue
            
            fin = DataFetcher.get_financial_data(code)
            quote = DataFetcher.get_realtime_quote(code)
            
            roe = fin.get("roe", 0)
            gross_margin = fin.get("gross_margin", 0)
            net_margin = fin.get("net_margin", 0)
            rev_growth = fin.get("rev_growth", 0)
            pe = quote.get("pe_ttm", 999) if quote else 999
            
            # 五维评分
            score = 0
            # 盈利能力
            if roe >= 20: score += 35
            elif roe >= 15: score += 25
            elif roe > 0: score += 15
            if gross_margin >= 40: score += 8
            if net_margin >= 15: score += 5
            # 成长性
            if rev_growth >= 20: score += 25
            elif rev_growth >= 15: score += 20
            elif rev_growth > 0: score += 10
            # 估值
            if 0 < pe <= 15: score += 20
            elif pe <= 25: score += 15
            elif pe <= 35: score += 10
            
            if score >= 60:
                candidates.append({
                    "code": code, "name": quote.get("name", "") if quote else "",
                    "score": score, "roe": roe, "pe": pe, "growth": rev_growth
                })
        
        candidates.sort(key=lambda x: x["score"], reverse=True)
        top = candidates[:5]
        
        if top:
            size = engine.cash * 0.9 / len(top)
            for s in top:
                price = current_prices.get(s["code"], 0)
                if price <= 0:
                    continue
                shares = int(size / price / 100) * 100
                if shares >= 100:
                    orders.append(Order(code=s["code"], name=s["name"], order_type=Order.BUY,
                                       shares=shares, price=price, date=date,
                                       reason=f"五维{ s['score']}分 ROE={s['roe']:.1f}%"))
    
    return orders


# ==================== 运行回测 ====================
def run_example():
    """运行示例回测"""
    print("=" * 80)
    print("📊 价值投资之王 - 回测引擎示例")
    print("=" * 80)
    
    # 股票池（15 只预设股票）
    stock_pool = [
        "300015", "300760", "300122", "002007",  # 医疗健康
        "300059", "002049", "002236",  # 科技
        "300274", "002812", "300014",  # 新能源
        "002027",  # 传媒
        "002371", "300751",  # 材料
        "002352",  # 物流
        "603288",  # 食品
    ]
    
    # 回测区间（过去一年）
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    
    # 选择策略
    strategies = [
        ("低 PE 策略", low_pe_strategy),
        ("高成长策略", high_growth_strategy),
        ("五维价值策略", five_dim_strategy),
    ]
    
    results = []
    
    for strategy_name, strategy_func in strategies:
        print(f"\n{'='*80}")
        print(f"🚀 运行策略：{strategy_name}")
        print(f"{'='*80}")
        
        engine = BacktestEngine(initial_capital=1000000.0)
        engine.set_strategy(strategy_func)
        
        result = engine.run_backtest(
            stock_pool=stock_pool,
            start_date=start_date,
            end_date=end_date,
            verbose=False  # 简化输出
        )
        
        if result and result.get("performance"):
            perf = result["performance"]
            results.append({
                "strategy": strategy_name,
                "performance": perf,
            })
            
            print(f"\n📊 {strategy_name} 结果:")
            print(f"  总收益：{perf.get('total_return', 0):.2f}%")
            print(f"  年化：{perf.get('annualized_return', 0):.2f}%")
            print(f"  夏普：{perf.get('sharpe_ratio', 0):.2f}")
            print(f"  回撤：-{perf.get('max_drawdown', 0):.2f}%")
            print(f"  胜率：{perf.get('win_rate', 0):.2f}%")
    
    # 汇总对比
    print(f"\n{'='*80}")
    print("📊 策略对比")
    print(f"{'='*80}")
    print(f"{'策略':<15} {'总收益':>10} {'年化':>10} {'夏普':>8} {'回撤':>10} {'胜率':>8}")
    print(f"{'-'*80}")
    for r in results:
        p = r["performance"]
        print(f"{r['strategy']:<15} {p.get('total_return', 0):>9.2f}% {p.get('annualized_return', 0):>9.2f}% "
              f"{p.get('sharpe_ratio', 0):>8.2f} -{p.get('max_drawdown', 0):>9.2f}% "
              f"{p.get('win_rate', 0):>7.2f}%")
    
    # 保存结果
    output = {
        "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "backtest_period": f"{start_date} 至 {end_date}",
        "stock_pool_size": len(stock_pool),
        "strategies": results,
    }
    
    with open("backtest_comparison.json",
              'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 对比报告已保存：backtest_comparison.json")
    
    return results


if __name__ == "__main__":
    run_example()
