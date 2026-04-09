# 价值投资之王 - 专业回测引擎 v2.0

## 📚 概述

这是一个专业的股票策略回测系统，支持全市场回测、策略回测、个股回测三种模式，完整考虑 A 股特性（T+1 交易、涨跌停限制、交易成本等）。

## 🎯 核心功能

### 1. 历史数据获取
- **日线数据**：支持前复权/后复权/不复权
- **财务数据**：ROE、毛利率、净利率、营收增速、净利增速
- **实时行情**：PE、PB、市值、涨跌幅等

### 2. 回测执行引擎
- **模拟交易**：支持买入/卖出订单
- **持仓管理**：自动计算持仓成本、盈亏
- **订单系统**：支持市价单、限价单
- **A 股特性**：
  - T+1 交易限制
  - 涨跌停限制（±10%/20%）
  - 交易成本（印花税 0.1%、佣金万 2.5、滑点 0.1%）
  - 最小交易单位 100 股

### 3. 绩效评估（完整指标）
| 指标 | 说明 | 目标值 |
|------|------|--------|
| 总收益率 | 整个回测期的总收益 | >50% |
| 年化收益 | 年化复合收益率 | >20% |
| 夏普比率 | 风险调整后收益 | >1.5 |
| 最大回撤 | 最大峰值回撤 | <25% |
| 胜率 | 盈利交易占比 | >55% |
| 盈亏比 | 平均盈利/平均亏损 | >2.0 |
| 波动率 | 年化波动率 | <30% |
| VaR(95%) | 95% 置信度风险价值 | <5% |

### 4. 风险分析
- **波动率分析**：年化波动率计算
- **VaR 风险价值**：95% 置信度下的最大可能损失
- **行业集中度**：HHI 指数、最大行业占比
- **持仓风险**：单票最大仓位、亏损持仓比例

### 5. 可视化报告
- **收益曲线**：组合价值变化趋势
- **回撤曲线**：回撤变化趋势
- **持仓分布**：饼图展示行业/个股分布
- **交易记录**：详细买卖记录表格

## 📁 文件结构

```
c:/Users/Administrator/WorkBuddy/Claw/
├── backtest_core.py          # 核心模块（数据获取、绩效评估、风险分析）
├── backtest_engine_v2.py     # 回测引擎主模块（执行引擎、策略框架）
├── backtest_example.py       # 使用示例（3 个策略示例）
├── templates/
│   └── backtest_report.html  # 可视化报告模板
├── backtest_engine.py        # 旧版回测（保留兼容）
└── backtest_collector.py     # 数据收集器（保留）
```

## 🚀 快速开始

### 示例 1: 运行预设策略回测

```python
from backtest_engine_v2 import run_backtest_demo
from datetime import datetime, timedelta

# 股票池
stocks = ["300015", "300760", "300122", "002007", "300059"]

# 回测区间
end = datetime.now().strftime("%Y-%m-%d")
start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

# 运行回测
result = run_backtest_demo(stocks, start, end, initial_capital=1000000.0)

# 查看结果
print(result["performance"])
```

### 示例 2: 自定义策略

```python
from backtest_engine_v2 import BacktestEngine, Order
from backtest_core import DataFetcher

def my_strategy(engine, date, stock_data_cache, current_prices):
    """自定义策略"""
    orders = []
    
    # 买入逻辑
    if engine.cash > 100000:
        for code in stock_data_cache.keys():
            fin = DataFetcher.get_financial_data(code)
            if fin.get("roe", 0) > 20:
                price = current_prices.get(code, 0)
                if price > 0:
                    shares = 1000  # 买 1000 股
                    orders.append(Order(
                        code=code, name="", order_type=Order.BUY,
                        shares=shares, price=price, date=date,
                        reason="ROE>20%"
                    ))
    
    return orders

# 创建引擎
engine = BacktestEngine(initial_capital=1000000.0)
engine.set_strategy(my_strategy)

# 运行回测
result = engine.run_backtest(
    stock_pool=["300015", "300760"],
    start_date="2023-01-01",
    end_date="2023-12-31"
)
```

### 示例 3: 运行多策略对比

```bash
# 运行示例脚本（自动对比 3 个策略）
python backtest_example.py
```

## 📊 查看可视化报告

1. 运行回测后生成 `backtest_report.json`
2. 在浏览器打开 `templates/backtest_report.html`
3. 自动加载 JSON 数据并显示图表

或者启动本地服务器：

```bash
# 进入模板目录
cd templates

# 启动简单 HTTP 服务器
python -m http.server 8000

# 浏览器访问
http://localhost:8000/backtest_report.html
```

## 🎨 策略开发指南

### 策略函数签名

```python
def strategy_func(engine, date, stock_data_cache, current_prices) -> List[Order]:
    """
    :param engine: 回测引擎实例（可访问持仓、现金等）
    :param date: 当前交易日期 YYYY-MM-DD
    :param stock_data_cache: 股票池历史数据
    :param current_prices: 当前价格字典 {code: price}
    :return: 订单列表
    """
```

### 可用 API

```python
# 访问持仓
engine.positions  # Dict[code, Position]
engine.cash       # 可用现金
engine.portfolio_value  # 组合总价值

# 创建订单
order = Order(
    code="300015",
    name="爱尔眼科",
    order_type=Order.BUY,  # 或 Order.SELL
    shares=1000,
    price=28.5,
    date="2024-01-01",
    reason="ROE>20% 买入"
)

# 访问财务数据
fin = DataFetcher.get_financial_data(code)
roe = fin["roe"]
rev_growth = fin["rev_growth"]
```

### 策略开发建议

1. **分散投资**：单只股票不超过 20%
2. **定期调仓**：建议月度/季度调仓
3. **止盈止损**：设置明确的卖出条件
4. **风控优先**：控制回撤在可接受范围

## ⚙️ 配置参数

### 交易成本配置

```python
# 在 backtest_core.py 中
BacktestConfig.STAMP_DUTY = 0.001      # 印花税 0.1%
BacktestConfig.COMMISSION = 0.00025    # 佣金万 2.5
BacktestConfig.MIN_COMMISSION = 5      # 最低佣金 5 元
BacktestConfig.SLIPPAGE = 0.001        # 滑点 0.1%
```

### 涨跌停配置

```python
BacktestConfig.PRICE_LIMIT_10 = 0.10   # 普通股票 10%
BacktestConfig.PRICE_LIMIT_20 = 0.20   # 创业板/科创板 20%
```

## 📈 回测结果解读

### 优秀策略标准

| 指标 | 优秀 | 良好 | 一般 |
|------|------|------|------|
| 年化收益 | >30% | 20-30% | 10-20% |
| 夏普比率 | >2.0 | 1.5-2.0 | 1.0-1.5 |
| 最大回撤 | <15% | 15-25% | 25-35% |
| 胜率 | >70% | 55-70% | 45-55% |

### 常见问题

**Q: 回测收益很高，实盘很差？**
- 检查是否过度拟合
- 考虑冲击成本（大资金影响价格）
- 验证样本外数据表现

**Q: 最大回撤过大？**
- 增加止损条件
- 降低单票仓位
- 增加股票数量分散风险

**Q: 胜率很低但收益不错？**
- 可能是盈亏比高（赚大赔小）
- 检查是否有幸存者偏差

## 🔧 高级功能

### 1. 自定义绩效指标

```python
from backtest_core import PerformanceEvaluator

# 添加自定义指标
def my_custom_metric(portfolio_values):
    # 计算索提诺比率（只考虑下行波动）
    ...

# 在回测后调用
custom = my_custom_metric(engine.portfolio_history)
```

### 2. 多周期回测

```python
# 同时回测多个时间段
periods = [
    ("2021-01-01", "2021-12-31"),
    ("2022-01-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
]

for start, end in periods:
    result = engine.run_backtest(stocks, start, end)
    print(f"{start}~{end}: 年化{result['performance']['annualized_return']:.2f}%")
```

### 3. 参数优化

```python
# 网格搜索最优参数
best_sharpe = 0
best_params = {}

for roe_threshold in [15, 20, 25]:
    for pe_max in [20, 30, 40]:
        # 修改策略参数
        # 运行回测
        # 记录夏普比率
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_params = {"roe": roe_threshold, "pe": pe_max}
```

## 📝 注意事项

1. **数据质量**：回测准确性依赖历史数据质量
2. **未来函数**：避免使用未来数据（如当日收盘价决定当日买入）
3. **幸存者偏差**：使用当时的股票池，而非当前的
4. **流动性**：假设所有股票都能按收盘价成交
5. **复权处理**：建议使用前复权数据

## 🎓 学习资源

- [量化交易入门](https://www.quantstart.com/)
- [A 股交易规则](http://www.sse.com.cn/)
- [财务指标详解](http://data.eastmoney.com/)

## 📞 技术支持

如有问题，请查看：
1. `backtest_example.py` - 完整示例代码
2. `templates/backtest_report.html` - 可视化报告源码
3. `backtest_core.py` - 核心 API 文档

---

**版本**: v2.0  
**最后更新**: 2026-04-02  
**作者**: 价值投资之王团队
