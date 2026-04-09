# -*- coding: utf-8 -*-
"""
价值投资之王 - 专业股票回测引擎核心模块 v2.0
包含：历史数据获取、回测执行、绩效评估、风险分析
支持 A 股特性：T+1、涨跌停、停牌、交易成本
"""
import requests
import json
import sys
import urllib3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import math

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Windows 控制台编码处理
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# 创建全局session，禁用SSL验证
_session = requests.Session()
_session.verify = False
_session.trust_env = False


# ==================== 配置常量 ====================
class BacktestConfig:
    """回测配置参数"""
    # 交易成本
    STAMP_DUTY = 0.001  # 印花税 0.1%（卖出收取）
    COMMISSION = 0.00025  # 佣金万 2.5
    MIN_COMMISSION = 5  # 最低佣金 5 元
    SLIPPAGE = 0.001  # 滑点 0.1%

    # 交易规则
    T_PLUS_1 = True  # T+1 交易
    PRICE_LIMIT_10 = 0.10  # 普通股票涨跌停 10%
    PRICE_LIMIT_20 = 0.20  # 创业板/科创板涨跌停 20%

    # 数据源（使用新浪财经API + 腾讯行情 + 东方财富数据中心）
    SINA_KLINE = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
    TENCENT_QUOTE = "http://qt.gtimg.cn/q="
    FINANCE_API = "https://datacenter-web.eastmoney.com"


# ==================== 数据结构 ====================
class Position:
    """持仓对象"""
    def __init__(self, code: str, name: str, shares: int, avg_price: float, buy_date: str):
        self.code = code
        self.name = name
        self.shares = shares
        self.avg_price = avg_price
        self.buy_date = buy_date
        self.current_price = 0.0
        self.market_value = 0.0
        self.profit_loss = 0.0
        self.profit_loss_pct = 0.0
    
    def update_price(self, price: float):
        """更新当前价格并计算盈亏"""
        self.current_price = price
        self.market_value = self.shares * price
        self.profit_loss = (price - self.avg_price) * self.shares
        self.profit_loss_pct = (price / self.avg_price - 1) * 100
    
    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "shares": self.shares,
            "avg_price": round(self.avg_price, 2),
            "current_price": round(self.current_price, 2),
            "market_value": round(self.market_value, 2),
            "profit_loss": round(self.profit_loss, 2),
            "profit_loss_pct": round(self.profit_loss_pct, 2),
            "buy_date": self.buy_date,
        }


class Order:
    """订单对象"""
    BUY = "BUY"
    SELL = "SELL"
    
    def __init__(self, code: str, name: str, order_type: str, shares: int, 
                 price: float, date: str, reason: str = ""):
        self.code = code
        self.name = name
        self.order_type = order_type
        self.shares = shares
        self.price = price
        self.date = date
        self.reason = reason  # 买卖理由
        self.status = "PENDING"  # PENDING, FILLED, CANCELLED
        self.fill_price = 0.0
        self.fill_shares = 0
        self.cost = 0.0  # 交易成本
    
    def fill(self, fill_price: float):
        """成交订单"""
        self.fill_price = fill_price
        self.fill_shares = self.shares
        self.status = "FILLED"
        # 计算交易成本
        trade_value = fill_price * self.shares
        commission = max(trade_value * BacktestConfig.COMMISSION, BacktestConfig.MIN_COMMISSION)
        stamp_duty = trade_value * BacktestConfig.STAMP_DUTY if self.order_type == self.SELL else 0
        slippage_cost = trade_value * BacktestConfig.SLIPPAGE
        self.cost = commission + stamp_duty + slippage_cost
    
    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "code": self.code,
            "name": self.name,
            "type": self.order_type,
            "shares": self.shares,
            "price": round(self.price, 2),
            "fill_price": round(self.fill_price, 2),
            "cost": round(self.cost, 2),
            "reason": self.reason,
            "status": self.status,
        }


class Trade:
    """成交记录"""
    def __init__(self, code: str, name: str, order_type: str, shares: int, 
                 price: float, cost: float, date: str, reason: str = ""):
        self.code = code
        self.name = name
        self.order_type = order_type
        self.shares = shares
        self.price = price
        self.cost = cost
        self.date = date
        self.reason = reason
        self.profit_loss = 0.0  # 卖出时计算盈亏
    
    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "code": self.code,
            "name": self.name,
            "type": self.order_type,
            "shares": self.shares,
            "price": round(self.price, 2),
            "cost": round(self.cost, 2),
            "profit_loss": round(self.profit_loss, 2) if self.order_type == "SELL" else None,
            "reason": self.reason,
        }


# ==================== 历史数据获取 ====================
class DataFetcher:
    """历史数据获取器"""
    
    @staticmethod
    def get_sina_code(code: str) -> str:
        """将股票代码转换为新浪 API 格式"""
        if code.startswith('6'):
            return f"sh{code}"  # 上海
        elif code.startswith('0'):
            return f"sz{code}"  # 深圳
        elif code.startswith('3'):
            return f"sz{code}"  # 创业板
        elif code.startswith('688'):
            return f"sh{code}"  # 科创板
        return f"sz{code}"

    # 腾讯和新浪使用相同的代码格式
    get_tencent_code = get_sina_code

    @classmethod
    def get_kline_data(cls, code: str, start_date: str, end_date: str,
                       period: str = "daily", adj: str = "qfq") -> List[dict]:
        """
        获取 K 线数据（使用新浪财经 API）
        :param code: 股票代码
        :param start_date: 开始日期 YYYY-MM-DD
        :param end_date: 结束日期 YYYY-MM-DD
        :param period: 周期 daily/weekly/monthly
        :param adj: 复权类型 qfq/hfq/none（新浪接口返回不复权数据，需要手动处理）
        :return: K 线数据列表
        """
        try:
            sina_code = cls.get_sina_code(code)

            # 周期参数：240=日K, 1440=周K, 10080=月K（简化处理，主要支持日K）
            scale_map = {"daily": "240", "weekly": "1440", "monthly": "10080"}
            scale = scale_map.get(period, "240")

            # 计算需要获取的数据条数（从结束日期往前）
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            days_diff = (end_dt - start_dt).days + 30  # 多获取一些数据确保覆盖
            datalen = str(min(days_diff, 1000))  # 最多1000条

            url = BacktestConfig.SINA_KLINE
            params = {
                "symbol": sina_code,
                "scale": scale,
                "ma": "no",
                "datalen": datalen,
            }
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
            resp = _session.get(url, params=params, headers=headers, timeout=15)

            # 新浪返回 JSON 数组
            data = resp.json()
            if data and isinstance(data, list):
                klines = []
                for item in data:
                    if isinstance(item, dict):
                        date = item.get("day", "")
                        # 过滤日期范围
                        if start_date <= date <= end_date:
                            klines.append({
                                "date": date,
                                "open": float(item.get("open", 0)),
                                "close": float(item.get("close", 0)),
                                "high": float(item.get("high", 0)),
                                "low": float(item.get("low", 0)),
                                "volume": float(item.get("volume", 0)),
                                "amount": 0,
                                "change_pct": 0,
                                "change_amount": 0,
                                "amplitude": 0,
                                "turnover_rate": 0,
                            })
                # 按日期排序
                klines.sort(key=lambda x: x["date"])
                return klines
        except Exception as e:
            print(f"  获取{code}K线失败：{e}")
        return []
    
    @classmethod
    def get_realtime_quote(cls, code: str) -> Optional[dict]:
        """获取单只股票实时行情（使用腾讯 API）"""
        try:
            tx_code = cls.get_tencent_code(code)
            url = f"{BacktestConfig.TENCENT_QUOTE}{tx_code}"
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
            resp = _session.get(url, headers=headers, timeout=5)

            # 腾讯返回格式: v_sz300015="51~爱尔眼科~300015~..."
            text = resp.text.strip()
            if '=' in text:
                text = text.split('=', 1)[1].strip('"')

            if text and '~' in text:
                parts = text.split('~')
                if len(parts) >= 45:
                    price = float(parts[3]) if parts[3] else 0
                    yesterday_close = float(parts[4]) if parts[4] else 0
                    change_pct = float(parts[5]) if parts[5] else 0
                    change_amount = float(parts[31]) if len(parts) > 31 and parts[31] else 0
                    total_volume = float(parts[6]) if len(parts) > 6 and parts[6] else 0
                    total_amount = float(parts[37]) if len(parts) > 37 and parts[37] else 0
                    turnover_rate = float(parts[38]) if len(parts) > 38 and parts[38] else 0
                    pe_ttm = float(parts[39]) if len(parts) > 39 and parts[39] else 0
                    pb = float(parts[46]) if len(parts) > 46 and parts[46] else 0
                    total_market_cap = float(parts[45]) if len(parts) > 45 and parts[45] else 0

                    return {
                        "code": code,
                        "name": parts[1] if len(parts) > 1 else "",
                        "price": price,
                        "yesterday_close": yesterday_close,
                        "open": float(parts[7]) if len(parts) > 7 and parts[7] else 0,
                        "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                        "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                        "volume": total_volume,
                        "amount": total_amount,
                        "change_pct": change_pct,
                        "change_amount": change_amount,
                        "turnover_rate": turnover_rate,
                        "pe_ttm": pe_ttm,
                        "pb": pb,
                        "market_cap": total_market_cap * 10000,  # 万转换为元
                    }
        except Exception as e:
            print(f"  获取{code}实时行情失败：{e}")
        return None
    
    @classmethod
    def get_financial_data(cls, code: str) -> dict:
        """获取财务数据（ROE、毛利率、营收增速、净利增速）"""
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}
        base_url = f"{BacktestConfig.FINANCE_API}/api/data/v1/get"
        result = {'roe': 0, 'rev_growth': 0, 'profit_growth': 0, 'gross_margin': 0, 
                  'net_margin': 0, 'debt_ratio': 0}
        
        # 获取 ROE、毛利率
        try:
            params = {
                'reportName': 'RPT_F10_FINANCE_MAINFINADATA',
                'columns': 'REPORT_DATE_NAME,ROEJQ,XSMLL,XSJLL',
                'filter': f'(SECURITY_CODE="{code}")',
                'pageNumber': 1, 'pageSize': 1,
                'source': 'WEB', 'client': 'WEB',
            }
            resp = _session.get(base_url, params=params, headers=headers, timeout=5)
            d = resp.json()
            if d.get('success') and d.get('result') and d['result'].get('data'):
                item = d['result']['data'][0]
                roe_val = item.get('ROEJQ', 0)
                if roe_val is not None: result['roe'] = float(roe_val)
                xsml_val = item.get('XSMLL', 0)
                if xsml_val is not None: result['gross_margin'] = float(xsml_val)
                xsjl_val = item.get('XSJLL', 0)
                if xsjl_val is not None: result['net_margin'] = float(xsjl_val)
        except:
            pass
        
        # 获取营收增速、净利增速
        try:
            params = {
                'reportName': 'RPT_LICO_FN_CPD',
                'columns': 'YSTZ,SJLTZ',
                'filter': f'(SECURITY_CODE="{code}")',
                'pageNumber': 1, 'pageSize': 1,
                'source': 'WEB', 'client': 'WEB',
            }
            resp = _session.get(base_url, params=params, headers=headers, timeout=5)
            d = resp.json()
            if d.get('success') and d.get('result') and d['result'].get('data'):
                item = d['result']['data'][0]
                ystz = item.get('YSTZ', 0)
                if ystz is not None: result['rev_growth'] = float(ystz)
                sjltz = item.get('SJLTZ', 0)
                if sjltz is not None: result['profit_growth'] = float(sjltz)
        except:
            pass
        
        return result
    
    @classmethod
    def get_stock_info(cls, code: str) -> dict:
        """获取股票基本信息（行业、概念、是否 ST 等）"""
        try:
            tx_code = cls.get_tencent_code(code)
            url = f"{BacktestConfig.TENCENT_QUOTE}{tx_code}"
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
            resp = _session.get(url, headers=headers, timeout=5)

            # 腾讯返回格式
            text = resp.text.strip()
            if '=' in text:
                text = text.split('=', 1)[1].strip('"')

            if text and '~' in text:
                parts = text.split('~')
                name = parts[1] if len(parts) > 1 else ""
                return {
                    "name": name,
                    "industry": "",  # 行业数据需要额外接口
                    "concept": "",   # 概念数据需要额外接口
                    "is_st": "ST" in name,
                    "is_300": code.startswith("3"),  # 创业板
                    "is_688": code.startswith("688"),  # 科创板
                    "market_cap": float(parts[45]) * 10000 if len(parts) > 45 and parts[45] else 0,
                }
        except Exception as e:
            print(f"  获取{code}股票信息失败：{e}")
        return {"name": "", "is_st": False, "is_300": False, "is_688": False}


# ==================== 绩效评估 ====================
class PerformanceEvaluator:
    """绩效评估器"""
    
    @staticmethod
    def calculate_total_return(initial_capital: float, final_value: float) -> float:
        """计算总收益率"""
        if initial_capital <= 0:
            return 0
        return (final_value - initial_capital) / initial_capital * 100
    
    @staticmethod
    def calculate_annualized_return(total_return: float, days: int) -> float:
        """计算年化收益率"""
        if days <= 0:
            return 0
        years = days / 365.0
        if years <= 0:
            return total_return
        return ((1 + total_return / 100) ** (1 / years) - 1) * 100
    
    @staticmethod
    def calculate_sharpe_ratio(daily_returns: List[float], risk_free_rate: float = 0.02) -> float:
        """
        计算夏普比率
        :param daily_returns: 日收益率列表
        :param risk_free_rate: 无风险利率（年化）
        :return: 夏普比率
        """
        if not daily_returns or len(daily_returns) < 5:
            return 0
        
        # 日收益率年化
        trading_days = 242
        avg_daily_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_daily_return) ** 2 for r in daily_returns) / len(daily_returns)
        std_daily = math.sqrt(variance)
        
        if std_daily == 0:
            return 0
        
        annual_return = avg_daily_return * trading_days
        annual_std = std_daily * math.sqrt(trading_days)
        
        return (annual_return - risk_free_rate) / annual_std
    
    @staticmethod
    def calculate_max_drawdown(portfolio_values: List[float]) -> Tuple[float, int, int]:
        """
        计算最大回撤
        :param portfolio_values: 投资组合价值序列
        :return: (最大回撤百分比，峰值索引，谷值索引)
        """
        if not portfolio_values or len(portfolio_values) < 2:
            return 0, 0, 0
        
        max_dd = 0
        peak_idx = 0
        trough_idx = 0
        peak = portfolio_values[0]
        
        for i, value in enumerate(portfolio_values):
            if value > peak:
                peak = value
                peak_idx = i
            
            dd = (peak - value) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                trough_idx = i
        
        return max_dd, peak_idx, trough_idx
    
    @staticmethod
    def calculate_win_rate(trades: List[Trade]) -> float:
        """计算胜率"""
        if not trades:
            return 0
        
        profitable_trades = sum(1 for t in trades if t.order_type == "SELL" and t.profit_loss > 0)
        total_sell_trades = sum(1 for t in trades if t.order_type == "SELL")
        
        if total_sell_trades == 0:
            return 0
        
        return profitable_trades / total_sell_trades * 100
    
    @staticmethod
    def calculate_profit_loss_ratio(trades: List[Trade]) -> float:
        """计算盈亏比"""
        if not trades:
            return 0
        
        profitable = [t.profit_loss for t in trades if t.order_type == "SELL" and t.profit_loss > 0]
        losing = [t.profit_loss for t in trades if t.order_type == "SELL" and t.profit_loss < 0]
        
        avg_profit = sum(profitable) / len(profitable) if profitable else 0
        avg_loss = abs(sum(losing) / len(losing)) if losing else 0
        
        if avg_loss == 0:
            return 0 if avg_profit == 0 else float('inf')
        
        return avg_profit / avg_loss
    
    @staticmethod
    def calculate_volatility(daily_returns: List[float]) -> float:
        """计算年化波动率"""
        if not daily_returns or len(daily_returns) < 2:
            return 0
        
        avg_return = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_return) ** 2 for r in daily_returns) / len(daily_returns)
        std_daily = math.sqrt(variance)
        
        # 年化
        return std_daily * math.sqrt(242) * 100
    
    @staticmethod
    def calculate_var(portfolio_values: List[float], confidence_level: float = 0.95) -> float:
        """
        计算 VaR（Value at Risk，风险价值）
        :param portfolio_values: 投资组合价值序列
        :param confidence_level: 置信水平（95% 或 99%）
        :return: VaR 值（百分比）
        """
        if not portfolio_values or len(portfolio_values) < 10:
            return 0
        
        # 计算日收益率
        returns = []
        for i in range(1, len(portfolio_values)):
            r = (portfolio_values[i] - portfolio_values[i-1]) / portfolio_values[i-1]
            returns.append(r)
        
        if not returns:
            return 0
        
        # 排序
        returns.sort()
        
        # 取分位数
        index = int((1 - confidence_level) * len(returns))
        var_95 = abs(returns[index]) * 100 if index < len(returns) else 0
        
        return var_95
    
    @classmethod
    def evaluate_portfolio(cls, initial_capital: float, portfolio_values: List[float],
                          daily_returns: List[float], trades: List[Trade],
                          trading_days: int) -> dict:
        """
        综合评估投资组合
        :return: 绩效指标字典
        """
        if not portfolio_values:
            return {}
        
        final_value = portfolio_values[-1]
        total_return = cls.calculate_total_return(initial_capital, final_value)
        annual_return = cls.calculate_annualized_return(total_return, trading_days)
        sharpe = cls.calculate_sharpe_ratio(daily_returns)
        max_dd, peak_idx, trough_idx = cls.calculate_max_drawdown(portfolio_values)
        volatility = cls.calculate_volatility(daily_returns)
        var_95 = cls.calculate_var(portfolio_values, 0.95)
        win_rate = cls.calculate_win_rate(trades)
        profit_loss_ratio = cls.calculate_profit_loss_ratio(trades)
        
        return {
            "initial_capital": initial_capital,
            "final_value": round(final_value, 2),
            "total_return": round(total_return, 2),
            "annualized_return": round(annual_return, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 2),
            "volatility": round(volatility, 2),
            "var_95": round(var_95, 2),
            "win_rate": round(win_rate, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "trading_days": trading_days,
            "total_trades": len([t for t in trades if t.order_type == "SELL"]),
            "peak_date_index": peak_idx,
            "trough_date_index": trough_idx,
        }


# ==================== 风险分析 ====================
class RiskAnalyzer:
    """风险分析器"""
    
    @staticmethod
    def calculate_sector_concentration(positions: List[Position], 
                                       sector_map: Dict[str, str]) -> dict:
        """
        计算行业集中度
        :param positions: 持仓列表
        :param sector_map: 股票代码 -> 行业 映射
        :return: 行业集中度指标
        """
        if not positions:
            return {}
        
        sector_values = {}
        total_value = sum(p.market_value for p in positions)
        
        if total_value == 0:
            return {}
        
        for pos in positions:
            sector = sector_map.get(pos.code, "未知")
            if sector not in sector_values:
                sector_values[sector] = 0
            sector_values[sector] += pos.market_value
        
        # 计算各行业占比
        sector_weights = {s: v / total_value * 100 for s, v in sector_values.items()}
        
        # 最大行业集中度
        max_sector_weight = max(sector_weights.values()) if sector_weights else 0
        
        # HHI 指数（赫芬达尔指数）
        hhi = sum(w ** 2 for w in sector_weights.values())
        
        return {
            "sector_weights": sector_weights,
            "max_sector_weight": round(max_sector_weight, 2),
            "hhi_index": round(hhi, 2),
            "num_sectors": len(sector_weights),
        }
    
    @staticmethod
    def calculate_position_risk(positions: List[Position]) -> dict:
        """
        计算持仓风险
        :param positions: 持仓列表
        :return: 风险指标
        """
        if not positions:
            return {}
        
        total_value = sum(p.market_value for p in positions)
        total_profit_loss = sum(p.profit_loss for p in positions)
        
        # 单只股票最大仓位
        max_position_weight = 0
        if total_value > 0:
            max_position_weight = max(p.market_value / total_value * 100 for p in positions)
        
        # 平均仓位
        avg_position_weight = 100 / len(positions) if positions else 0
        
        # 亏损持仓数量
        losing_positions = sum(1 for p in positions if p.profit_loss < 0)
        
        return {
            "total_market_value": round(total_value, 2),
            "total_profit_loss": round(total_profit_loss, 2),
            "max_position_weight": round(max_position_weight, 2),
            "avg_position_weight": round(avg_position_weight, 2),
            "num_positions": len(positions),
            "num_losing_positions": losing_positions,
            "losing_ratio": round(losing_positions / len(positions) * 100, 2) if positions else 0,
        }
    
    @staticmethod
    def calculate_beta(stock_returns: List[float], market_returns: List[float]) -> float:
        """
        计算 Beta 系数（需要市场收益率数据）
        :param stock_returns: 股票收益率序列
        :param market_returns: 市场收益率序列（如沪深 300）
        :return: Beta 系数
        """
        if not stock_returns or not market_returns:
            return 0
        
        n = min(len(stock_returns), len(market_returns))
        if n < 10:
            return 0
        
        # 简化计算：协方差 / 市场方差
        avg_stock = sum(stock_returns[:n]) / n
        avg_market = sum(market_returns[:n]) / n
        
        covariance = sum((stock_returns[i] - avg_stock) * (market_returns[i] - avg_market) 
                        for i in range(n)) / n
        market_variance = sum((market_returns[i] - avg_market) ** 2 for i in range(n)) / n
        
        if market_variance == 0:
            return 0
        
        return covariance / market_variance


# ==================== 可视化工具 ====================
class ChartGenerator:
    """图表生成器（生成 HTML 可视化数据）"""
    
    @staticmethod
    def generate_equity_curve_data(portfolio_values: List[float], 
                                   dates: List[str]) -> dict:
        """生成收益曲线数据"""
        return {
            "dates": dates,
            "values": portfolio_values,
        }
    
    @staticmethod
    def generate_drawdown_curve_data(portfolio_values: List[float]) -> List[float]:
        """生成回撤曲线数据"""
        if not portfolio_values:
            return []
        
        drawdowns = []
        peak = portfolio_values[0]
        
        for value in portfolio_values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak * 100 if peak > 0 else 0
            drawdowns.append(dd)
        
        return drawdowns
    
    @staticmethod
    def generate_position_distribution(positions: List[Position]) -> dict:
        """生成持仓分布数据"""
        if not positions:
            return {}
        
        total_value = sum(p.market_value for p in positions)
        if total_value == 0:
            return {}
        
        distribution = []
        for pos in positions:
            weight = pos.market_value / total_value * 100
            distribution.append({
                "code": pos.code,
                "name": pos.name,
                "weight": round(weight, 2),
                "profit_loss_pct": round(pos.profit_loss_pct, 2),
            })
        
        # 按权重排序
        distribution.sort(key=lambda x: x["weight"], reverse=True)
        
        return {
            "positions": distribution,
            "total_count": len(positions),
        }
    
    @staticmethod
    def generate_trade_record_data(trades: List[Trade]) -> List[dict]:
        """生成交易记录数据"""
        return [t.to_dict() for t in trades]


# ==================== 回测报告生成 ====================
class ReportGenerator:
    """回测报告生成器"""
    
    @staticmethod
    def generate_text_report(performance: dict, risk_analysis: dict, 
                            trades: List[Trade], positions: List[Position]) -> str:
        """生成文本格式回测报告"""
        report = []
        report.append("=" * 80)
        report.append("📊 价值投资之王 - 专业回测报告")
        report.append("=" * 80)
        
        # 绩效指标
        report.append("\n【绩效指标】")
        report.append(f"  初始资金：¥{performance.get('initial_capital', 0):,.2f}")
        report.append(f"  最终价值：¥{performance.get('final_value', 0):,.2f}")
        report.append(f"  总收益率：{performance.get('total_return', 0):.2f}%")
        report.append(f"  年化收益：{performance.get('annualized_return', 0):.2f}%")
        report.append(f"  夏普比率：{performance.get('sharpe_ratio', 0):.2f}")
        report.append(f"  最大回撤：{performance.get('max_drawdown', 0):.2f}%")
        report.append(f"  年化波动：{performance.get('volatility', 0):.2f}%")
        report.append(f"  VaR(95%)：{performance.get('var_95', 0):.2f}%")
        report.append(f"  胜率：{performance.get('win_rate', 0):.2f}%")
        report.append(f"  盈亏比：{performance.get('profit_loss_ratio', 0):.2f}")
        report.append(f"  交易天数：{performance.get('trading_days', 0)}")
        report.append(f"  总交易次数：{performance.get('total_trades', 0)}")
        
        # 风险分析
        if risk_analysis:
            report.append("\n【风险分析】")
            if "sector_weights" in risk_analysis:
                report.append("  行业集中度:")
                for sector, weight in risk_analysis["sector_weights"].items():
                    report.append(f"    {sector}: {weight:.2f}%")
                report.append(f"  HHI 指数：{risk_analysis.get('hhi_index', 0):.2f}")
                report.append(f"  最大行业占比：{risk_analysis.get('max_sector_weight', 0):.2f}%")
            
            if "total_market_value" in risk_analysis:
                report.append(f"  持仓总市值：¥{risk_analysis.get('total_market_value', 0):,.2f}")
                report.append(f"  持仓盈亏：¥{risk_analysis.get('total_profit_loss', 0):,.2f}")
                report.append(f"  最大单票仓位：{risk_analysis.get('max_position_weight', 0):.2f}%")
                report.append(f"  亏损持仓数：{risk_analysis.get('num_losing_positions', 0)}")
        
        # 交易记录
        if trades:
            report.append("\n【交易记录】")
            for i, trade in enumerate(trades[-10:], 1):  # 只显示最近 10 笔
                report.append(f"  {i}. {trade.date} {trade.order_type} {trade.name}({trade.code}) "
                            f"{trade.shares}股 @ ¥{trade.price:.2f} 成本¥{trade.cost:.2f}")
        
        # 当前持仓
        if positions:
            report.append("\n【当前持仓】")
            for pos in positions:
                report.append(f"  {pos.name}({pos.code}): {pos.shares}股 "
                            f"成本¥{pos.avg_price:.2f} 现价¥{pos.current_price:.2f} "
                            f"盈亏¥{pos.profit_loss:.2f} ({pos.profit_loss_pct:+.2f}%)")
        
        report.append("\n" + "=" * 80)
        return "\n".join(report)
    
    @staticmethod
    def generate_json_report(performance: dict, risk_analysis: dict,
                            trades: List[Trade], positions: List[Position],
                            chart_data: dict) -> dict:
        """生成 JSON 格式回测报告"""
        return {
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "performance": performance,
            "risk_analysis": risk_analysis,
            "trades": [t.to_dict() for t in trades],
            "positions": [p.to_dict() for p in positions],
            "chart_data": chart_data,
        }
