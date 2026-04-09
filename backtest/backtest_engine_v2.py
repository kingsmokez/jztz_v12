# -*- coding: utf-8 -*-
"""
价值投资之王 - 专业股票回测引擎 v2.0
支持全市场回测、策略回测、个股回测三种模式
考虑 A 股特性：T+1、涨跌停、停牌、交易成本
"""
import sys
import io
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import time
import json

# Windows 编码设置在 main 函数中处理，避免模块导入时冲突

from backtest_core import (
    BacktestConfig, Position, Order, Trade, DataFetcher,
    PerformanceEvaluator, RiskAnalyzer, ChartGenerator, ReportGenerator
)


class BacktestEngine:
    """回测引擎核心类"""
    
    def __init__(self, initial_capital: float = 1000000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.portfolio_value = initial_capital
        self.positions: Dict[str, Position] = {}
        self.orders: List[Order] = []
        self.trades: List[Trade] = []
        self.portfolio_history: List[float] = []
        self.daily_returns: List[float] = []
        self.dates: List[str] = []
        self.sector_map: Dict[str, str] = {}
        self.t1_lock: Dict[str, str] = {}
        self.strategy_func: Optional[Callable] = None
    
    def set_strategy(self, strategy_func: Callable):
        self.strategy_func = strategy_func
    
    def _execute_order(self, order: Order, current_price: float) -> bool:
        if order.order_type == Order.SELL:
            if order.code in self.t1_lock:
                if self.t1_lock[order.code] == (self.dates[-1] if self.dates else None):
                    return False
        
        if order.order_type == Order.BUY:
            required_cash = order.price * order.shares * 1.00125
            if required_cash > self.cash:
                available_shares = int(self.cash / (order.price * 1.001) / 100) * 100
                if available_shares < 100:
                    return False
                order.shares = available_shares
            
            order.fill(current_price)
            self.cash -= (order.fill_price * order.shares + order.cost)
            
            if order.code in self.positions:
                pos = self.positions[order.code]
                total_shares = pos.shares + order.shares
                total_cost = pos.avg_price * pos.shares + order.fill_price * order.shares + order.cost
                pos.avg_price = total_cost / total_shares
                pos.shares = total_shares
            else:
                self.positions[order.code] = Position(
                    code=order.code, name=order.name, shares=order.shares,
                    avg_price=order.fill_price, buy_date=self.dates[-1] if self.dates else ""
                )
            
            self.t1_lock[order.code] = self.dates[-1] if self.dates else ""
            
            trade = Trade(code=order.code, name=order.name, order_type=Order.BUY,
                         shares=order.shares, price=order.fill_price, cost=order.cost,
                         date=order.date, reason=order.reason)
            self.trades.append(trade)
            self.orders.append(order)
            return True
            
        elif order.order_type == Order.SELL:
            if order.code not in self.positions:
                return False
            
            pos = self.positions[order.code]
            if pos.shares < order.shares:
                order.shares = pos.shares
            
            if order.shares <= 0:
                return False
            
            order.fill(current_price)
            self.cash += (order.fill_price * order.shares - order.cost)
            profit_loss = (order.fill_price - pos.avg_price) * order.shares - order.cost
            
            pos.shares -= order.shares
            if pos.shares <= 0:
                del self.positions[order.code]
                if order.code in self.t1_lock:
                    del self.t1_lock[order.code]
            
            trade = Trade(code=order.code, name=order.name, order_type=Order.SELL,
                         shares=order.shares, price=order.fill_price, cost=order.cost,
                         date=order.date, reason=order.reason)
            trade.profit_loss = profit_loss
            self.trades.append(trade)
            self.orders.append(order)
            return True
        
        return False
    
    def _update_portfolio_value(self, prices: Dict[str, float]):
        total_value = self.cash
        for code, pos in self.positions.items():
            price = prices.get(code, pos.current_price)
            pos.update_price(price)
            total_value += pos.market_value
        self.portfolio_value = total_value
        self.portfolio_history.append(total_value)
        
        if len(self.portfolio_history) >= 2:
            prev_value = self.portfolio_history[-2]
            curr_value = self.portfolio_history[-1]
            if prev_value > 0:
                daily_return = (curr_value - prev_value) / prev_value
                self.daily_returns.append(daily_return)
    
    def run_backtest(self, stock_pool: List[str], start_date: str, end_date: str,
                     strategy_func: Optional[Callable] = None, verbose: bool = True) -> dict:
        if strategy_func:
            self.strategy_func = strategy_func
        
        if not self.strategy_func:
            raise ValueError("未设置交易策略")
        
        print("=" * 80)
        print("🚀 价值投资之王 - 专业回测引擎 v2.0")
        print("=" * 80)
        print(f"📅 回测区间：{start_date} 至 {end_date}")
        print(f"💰 初始资金：¥{self.initial_capital:,.2f}")
        print(f"📊 股票池：{len(stock_pool)}只股票")
        print("=" * 80)
        
        print("\n📡 正在加载历史数据...")
        stock_data_cache = {}
        for i, code in enumerate(stock_pool, 1):
            if verbose:
                print(f"  [{i}/{len(stock_pool)}] 加载 {code}...", end=" ")
            klines = DataFetcher.get_kline_data(code, start_date, end_date, period="daily", adj="qfq")
            stock_data_cache[code] = klines
            if verbose:
                print(f"✅ {len(klines)}条")
            time.sleep(0.1)
        
        print("\n🔄 开始回测...")
        all_dates = sorted(set(d for klines in stock_data_cache.values() for d in [k["date"] for k in klines]))
        all_dates = [d for d in all_dates if start_date <= d <= end_date]
        
        if not all_dates:
            print("❌ 无有效交易数据")
            return {}
        
        print(f"   交易天数：{len(all_dates)}")
        print("=" * 80)
        
        self.portfolio_history = [self.initial_capital]
        self.daily_returns = []
        
        for date_idx, date in enumerate(all_dates):
            self.dates.append(date)
            
            if verbose and date_idx % 20 == 0:
                print(f"\n📅 第{date_idx+1}天：{date} | 组合价值：¥{self.portfolio_value:,.2f}")
            
            current_prices = {}
            for code, klines in stock_data_cache.items():
                for kline in klines:
                    if kline["date"] == date:
                        current_prices[code] = kline["close"]
                        break
            
            self._update_portfolio_value(current_prices)
            
            try:
                orders = self.strategy_func(self, date, stock_data_cache, current_prices)
            except Exception as e:
                print(f"  ❌ 策略执行失败：{e}")
                continue
            
            if orders:
                for order in orders:
                    if order.code not in current_prices:
                        continue
                    self._execute_order(order, current_prices[order.code])
        
        print("\n" + "=" * 80)
        print("📊 回测完成，正在计算绩效指标...")
        print("=" * 80)
        
        trading_days = len(all_dates)
        performance = PerformanceEvaluator.evaluate_portfolio(
            self.initial_capital, self.portfolio_history,
            self.daily_returns, self.trades, trading_days
        )
        
        risk_analysis = RiskAnalyzer.calculate_position_risk(list(self.positions.values()))
        
        chart_data = {
            "equity_curve": {"dates": self.dates, "values": self.portfolio_history},
            "drawdown_curve": ChartGenerator.generate_drawdown_curve_data(self.portfolio_history),
            "position_distribution": ChartGenerator.generate_position_distribution(list(self.positions.values())),
            "trade_records": ChartGenerator.generate_trade_record_data(self.trades),
        }
        
        text_report = ReportGenerator.generate_text_report(
            performance, risk_analysis, self.trades, list(self.positions.values())
        )
        
        json_report = {
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "performance": performance,
            "risk_analysis": risk_analysis,
            "trades": [t.to_dict() for t in self.trades],
            "positions": [p.to_dict() for p in self.positions.values()],
            "chart_data": chart_data,
        }
        
        print("\n" + text_report)
        
        return {
            "performance": performance,
            "risk_analysis": risk_analysis,
            "chart_data": chart_data,
            "text_report": text_report,
            "json_report": json_report,
        }


def value_investment_strategy(engine, date, stock_data_cache, current_prices):
    """价值投资策略：ROE>20%、PE<30、增速>15%"""
    orders = []
    day_of_month = int(date.split("-")[2])
    is_rebalance_day = (day_of_month == 1)
    
    for code, pos in list(engine.positions.items()):
        buy_date = pos.buy_date
        if buy_date:
            buy_dt = datetime.strptime(buy_date, "%Y-%m-%d")
            current_dt = datetime.strptime(date, "%Y-%m-%d")
            holding_days = (current_dt - buy_dt).days
            if holding_days >= 30:
                order = Order(code=code, name=pos.name, order_type=Order.SELL,
                             shares=pos.shares, price=current_prices.get(code, pos.current_price),
                             date=date, reason=f"持有{holding_days}天到期")
                orders.append(order)
    
    if is_rebalance_day and engine.cash > engine.initial_capital * 0.1:
        candidates = []
        for code in stock_data_cache.keys():
            if code in engine.positions:
                continue
            fin_data = DataFetcher.get_financial_data(code)
            roe = fin_data.get("roe", 0)
            rev_growth = fin_data.get("rev_growth", 0)
            quote = DataFetcher.get_realtime_quote(code)
            pe = quote.get("pe_ttm", 999) if quote else 999
            
            if roe >= 20 and pe <= 30 and rev_growth >= 15:
                candidates.append({"code": code, "name": quote.get("name", "") if quote else "",
                                  "roe": roe, "pe": pe, "growth": rev_growth})
        
        candidates.sort(key=lambda x: x["roe"], reverse=True)
        top_stocks = candidates[:5]
        
        if top_stocks:
            position_size = engine.cash * 0.9 / len(top_stocks)
            for stock in top_stocks:
                code = stock["code"]
                price = current_prices.get(code, 0)
                if price <= 0:
                    continue
                shares = int(position_size / price / 100) * 100
                if shares < 100:
                    continue
                order = Order(code=code, name=stock["name"], order_type=Order.BUY,
                             shares=shares, price=price, date=date,
                             reason=f"ROE={stock['roe']:.1f}% PE={stock['pe']:.1f}")
                orders.append(order)
    
    return orders


def run_backtest_demo(stock_codes, start_date, end_date, initial_capital=1000000.0):
    """简化回测函数"""
    engine = BacktestEngine(initial_capital=initial_capital)
    engine.set_strategy(value_investment_strategy)
    return engine.run_backtest(stock_pool=stock_codes, start_date=start_date,
                               end_date=end_date, verbose=True)


if __name__ == "__main__":
    preset_stocks = ["300015", "300760", "300122", "002007", "300059", "002049",
                     "002236", "300274", "002812", "300014", "002027", "002371",
                     "300751", "002352", "603288"]
    
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    
    result = run_backtest_demo(preset_stocks, start, end)
    
    if result:
        with open("backtest_report.json",
                  'w', encoding='utf-8') as f:
            json.dump(result["json_report"], f, ensure_ascii=False, indent=2)
        print("\n✅ 报告已保存：backtest_report.json")
