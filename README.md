# 价值投资之王 · 智能选股系统 v14

基于五维价值评估模型的 A 股智能选股系统，支持实时选股、每日推荐和策略回测。

---

## 目录

- [功能特性](#功能特性)
- [环境要求](#环境要求)
- [安装部署](#安装部署)
- [运行说明](#运行说明)
- [使用指南](#使用指南)
- [项目结构](#项目结构)
- [API接口](#api接口)
- [常见问题](#常见问题)

---

## 功能特性

### 🎯 五维选股模型
| 维度 | 权重 | 指标 |
|-----|------|-----|
| 盈利能力 | 40% | ROE、毛利率、净利率 |
| 成长性 | 30% | 营收增速、净利增速 |
| 财务健康 | 15% | 资产负债率、现金流 |
| 估值 | 20% | PE、PB |
| 现金流 | 5% | 经营现金流 |

### 📊 核心功能
- ✅ **智能选股**: 全市场扫描，自动筛选优质标的
- ✅ **每日推荐**: 早盘 9:26、午盘 14:30 自动选股
- ✅ **实时行情**: 涨跌幅、成交量、换手率
- ✅ **个股详情**: 财务指标、历史走势、资金流向
- ✅ **策略回测**: 多种策略对比验证
- ✅ **板块行情**: 行业板块、概念板块涨跌

### 🔧 数据源
| 数据类型 | 数据源 | 接口地址 |
|---------|--------|---------|
| K线历史数据 | 新浪财经 | quotes.sina.cn |
| 实时行情 | 腾讯 API | qt.gtimg.cn |
| 财务数据 | 东方财富 | datacenter-web.eastmoney.com |

---

## 环境要求

### 系统要求
- **操作系统**: Windows 10/11、Linux、macOS
- **Python**: 3.8 或更高版本
- **网络**: 需要稳定的网络连接

### 必需依赖
```
flask>=2.0.0
requests>=2.25.0
urllib3>=1.26.0
```

---

## 安装部署

### 方式一：Windows 一键部署（推荐）

1. **下载项目**
   ```bash
   git clone https://github.com/kingsmokez/jztz_v12.git
   cd jztz_v12
   ```

2. **双击运行 `start_web.bat`**
   - 脚本会自动：
     - 检查 Python 是否安装
     - 创建虚拟环境 `.venv`
     - 安装所有依赖包
     - 启动 Web 服务

3. **打开浏览器访问**
   ```
   http://localhost:5557
   ```

### 方式二：手动部署

#### Step 1: 下载项目
```bash
git clone https://github.com/kingsmokez/jztz_v12.git
cd jztz_v12
```

#### Step 2: 创建虚拟环境
```bash
# Windows
python -m venv .venv

# Linux/macOS
python3 -m venv .venv
```

#### Step 3: 激活虚拟环境
```bash
# Windows CMD
.venv\Scripts\activate.bat

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Linux/macOS
source .venv/bin/activate
```

#### Step 4: 安装依赖
```bash
pip install -r requirements.txt
```

#### Step 5: 启动服务
```bash
python web_app.py
```

#### Step 6: 访问系统
```
本地访问: http://localhost:5557
局域网访问: http://<你的IP地址>:5557
```

### 方式三：Docker 部署（可选）

```bash
# 构建镜像
docker build -t jztz:v14 .

# 运行容器
docker run -d -p 5557:5557 --name jztz jztz:v14
```

---

## 运行说明

### 主程序运行

启动 Web 服务后，终端会显示：
```
==================================================
🏛️ 价值投资之王 · 智能选股可视化网站 v14
   访问 http://localhost:5557
   每日推荐: 自动选股 9:26(早盘) / 14:30(午盘)
==================================================
 * Serving Flask app 'web_app'
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5557
 * Running on http://192.168.x.x:5557
```

### 定时任务

系统内置定时选股功能：
- **早盘选股**: 每个交易日 9:26 自动执行
- **午盘选股**: 每个交易日 14:30 自动执行

### 回测程序运行

```bash
# 进入回测目录
cd backtest

# 运行策略对比示例
python backtest_example.py

# 运行演示报告（使用预设数据）
python backtest_demo.py
```

**回测输出示例：**
```
================================================================================
📊 策略对比
================================================================================
策略                     总收益         年化       夏普         回撤       胜率
--------------------------------------------------------------------------------
低 PE 策略             13.24%     20.63%     0.85 -     8.09%   66.67%
高成长策略               -4.84%     -7.22%    -0.07 -    25.05%   50.00%
五维价值策略              16.00%     25.09%     0.88 -     9.55%   66.67%
```

---

## 使用指南

### 1. 智能选股

**操作步骤：**
1. 打开首页 `http://localhost:5557`
2. 点击「开始选股」按钮
3. 等待系统扫描全市场（约 5-10 秒）
4. 查看按五维评分排序的股票列表
5. 点击股票代码查看详细信息

**筛选条件：**
- ROE > 8%
- PE > 0 且 PE < 200
- 排除 ST 股票
- 五维总分 ≥ 30 分

### 2. 每日推荐

**访问路径：** `/daily_pick` 或点击导航栏「每日推荐」

**功能说明：**
- 早盘推荐：9:26 自动生成，捕捉开盘机会
- 午盘推荐：14:30 自动生成，发现尾盘机会
- 支持手动刷新按钮

**推荐逻辑：**
- 综合五维评分前 10 名
- 考虑当日涨跌幅
- 排除已涨停股票

### 3. 个股详情

**查看方式：** 点击任意股票代码

**展示内容：**
- 基本行情：现价、涨跌幅、成交量、换手率
- 估值指标：PE、PB、市值
- 财务指标：ROE、毛利率、净利率、增速
- 历史走势：近 60 日 K 线图

### 4. 市场概览

**首页展示：**
- 上涨/下跌/平盘股票数量
- 平均涨跌幅
- 涨幅榜 Top 10
- 跌幅榜 Top 10

---

## 项目结构

```
jztz_v12/
│
├── web_app.py              # 主程序入口 (Flask 应用)
├── smart_stock_picker.py   # 选股核心逻辑
├── start_web.bat           # Windows 一键启动脚本
├── requirements.txt        # Python 依赖列表
├── README.md               # 项目说明文档
│
├── templates/              # HTML 模板目录
│   ├── index.html          # 首页 - 智能选股
│   ├── daily_pick.html     # 每日推荐页
│   └── backtest_report.html # 回测报告页
│
├── static/                 # 静态资源目录
│   └── test_stock_detail.html
│
├── backtest/               # 回测模块目录
│   ├── backtest_core.py    # 回测核心（数据获取、绩效评估）
│   ├── backtest_engine_v2.py # 回测引擎
│   ├── backtest_example.py # 策略示例脚本
│   ├── backtest_demo.py    # 演示脚本
│   └── backtest_*.json     # 回测结果文件
│
├── offline_stocks.json     # 离线股票财务数据 (90 只)
├── sector_codes.json       # 板块代码映射 (1010 个)
└── daily_pick_cache.json   # 每日推荐缓存
```

### 核心文件说明

| 文件 | 说明 | 行数 |
|-----|------|------|
| web_app.py | Flask 主应用，所有 API 接口 | ~2500 |
| smart_stock_picker.py | 五维选股算法实现 | ~800 |
| backtest/backtest_core.py | 回测核心模块 | ~800 |
| backtest/backtest_engine_v2.py | 回测引擎 | ~300 |

---

## API接口

### 选股相关

| 接口 | 方法 | 参数 | 说明 |
|-----|------|-----|------|
| `/api/pick` | GET | - | 获取智能选股结果 |
| `/api/daily_pick` | GET | - | 获取每日推荐 |
| `/api/daily_pick/refresh` | GET | session=morning/afternoon | 刷新推荐 |
| `/api/stock_detail` | GET | code=股票代码 | 获取个股详情 |
| `/api/search_stock` | GET | q=搜索词 | 搜索股票 |

### 市场数据

| 接口 | 方法 | 说明 |
|-----|------|------|
| `/api/market` | GET | 市场行情概览 |
| `/api/news` | GET | 财经资讯 |
| `/api/sector` | GET | 板块行情 |

### 接口示例

```bash
# 获取选股结果
curl http://localhost:5557/api/pick

# 获取个股详情
curl "http://localhost:5557/api/stock_detail?code=300015"

# 搜索股票
curl "http://localhost:5557/api/search_stock?q=爱尔"
```

---

## 常见问题

### Q1: 启动报错 "ModuleNotFoundError"
**解决方法：**
```bash
# 确保已激活虚拟环境
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS

# 重新安装依赖
pip install -r requirements.txt
```

### Q2: 无法访问网页
**检查步骤：**
1. 确认服务已启动，终端显示 "Running on..."
2. 检查防火墙是否放行 5557 端口
3. 尝试使用 `http://127.0.0.1:5557` 访问

### Q3: 选股结果为空
**可能原因：**
- 非交易时间，部分数据源可能无数据
- 网络连接问题
- 数据源 API 临时不可用

**解决方法：**
- 检查网络连接
- 稍后重试

### Q4: 回测程序报错 "无有效交易数据"
**原因：** K 线数据获取失败

**解决方法：**
- 检查网络是否能访问 `quotes.sina.cn`
- 确认股票代码正确

### Q5: 如何修改端口？
编辑 `web_app.py` 最后一行：
```python
app.run(host='0.0.0.0', port=你的端口)
```

### Q6: 如何自定义选股参数？
编辑 `smart_stock_picker.py` 中的配置：
```python
# 五维权重配置
WEIGHTS_V3 = {
    "profitability": 0.40,  # 盈利能力
    "growth": 0.30,         # 成长性
    "health": 0.15,         # 财务健康
    "valuation": 0.20,      # 估值
    "cashflow": 0.05,       # 现金流
}
```

---

## 更新日志

### v14 (2026-04-10)
- ✅ 修复资产负债率计算问题
- ✅ 更新数据源为腾讯API + 东方财富数据中心
- ✅ 优化回测引擎，支持新浪财经K线数据
- ✅ 添加离线数据缓存
- ✅ 改进错误处理和日志输出

### v13
- 添加每日推荐功能
- 优化五维评分算法
- 改进前端界面

### v12
- 重构选股逻辑
- 添加回测模块

---

## 技术栈

| 类别 | 技术 |
|-----|------|
| 后端框架 | Flask 2.x |
| HTTP 请求 | Requests |
| 数据格式 | JSON |
| 前端 | HTML5 + CSS3 + JavaScript |
| 图表 | Chart.js |
| 数据源 | 新浪财经、腾讯API、东方财富 |

---

## License

MIT License

---

## 免责声明

⚠️ **重要提示**

本系统仅供学习和研究使用，不构成任何投资建议。

- 股市有风险，投资需谨慎
- 历史数据不代表未来表现
- 使用本系统进行投资决策造成的任何损失，作者不承担相关责任
- 请遵守相关 API 的使用条款和频率限制

---

## 联系方式

- GitHub: https://github.com/kingsmokez/jztz_v12
- Issues: https://github.com/kingsmokez/jztz_v12/issues