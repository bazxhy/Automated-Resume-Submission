# 🤖 BOSS直聘 AI 自动投递

基于 DeepSeek 大模型的 BOSS直聘 全自动简历投递工具。AI 分析简历 → 推荐搜索关键词 → 联网评估公司风险 → 实时匹配岗位适合度 → 一键投递。

## ✨ 功能

| 模块 | 功能 |
|------|------|
| 🧠 AI 简历分析 | DeepSeek 分析简历内容，自动推荐最匹配的搜索关键词 |
| 🔍 岗位搜索 | API 批量拉取（公司名/学历/经验完整数据）+ DOM 滚动回退 |
| 🛡️ 公司风险评估 | DeepSeek **联网搜索**企业工商信息、经营状况、劳动纠纷 |
| 🎯 AI 岗位匹配 | 实时对照简历分析岗位适合度（技术栈/经验/方向匹配） |
| 📋 规则匹配 | 技能 + 经验 + 学历 + 薪资 + 关键词 五维打分 (0-100) |
| 🚫 学历过滤 | 可配置最高学历限制，自动跳过硕博岗位 |
| 🔄 每日计数 | 文件持久化每日投递数，跨天自动归零，多次运行不超限 |
| 📝 投递记录 | CSV + JSON 双重记录，防重复投递 |

## 🚀 快速开始

```bash
git clone https://github.com/bazxhy/Automated-Resume-Submission.git
cd Automated-Resume-Submission
pip install -r requirements.txt
```

### 配置 `config.yaml`

```yaml
search:
  keywords: ["嵌入式", "STM32", "单片机"]  # AI 模式下会自动推荐，留空即可
  city: "杭州"
  experience: "应届生"

filter:
  exclude_titles: ["实习", "外包", "培训"]
  max_education: "本科"        # 自动跳过硕士/博士岗位
  ai_fit_check: true           # 开启 AI 岗位匹配
  ai_fit_min_score: 40         # AI 匹配分 < 40 跳过

risk_check:
  mode: "api"                  # api=DeepSeek联网评估, rule=本地规则
  api:
    provider: "deepseek"
    token: "sk-xxx"            # DeepSeek API Key

submit:
  daily_limit: 150             # 每日最大投递数
  interval:
    min: 8
    max: 20
```

### 运行

```bash
# 完整流程
python main.py

# 预览模式（不实际投递）
python main.py --search-only

# 指定简历
python main.py --resume ./我的简历.pdf

# 自定义配置
python main.py --config my_config.yaml
```

### 打包为 exe

```bash
build.bat
# 输出: dist/BOSS自动投递.exe
```

## 🧠 AI 工作流

```
简历解析 → AI 分析推荐搜索关键词
     ↓
API 批量拉取岗位（公司名/学历/经验完整数据）
     ↓
逐个岗位:
  ├─ 标题排除 / 学历过滤 / 技能过滤
  ├─ 🌐 DeepSeek 联网搜索公司风险（查工商/纠纷/经营异常）
  ├─ 🎯 DeepSeek 实时对照简历判断岗位适合度
  └─ ✅ 点击立即沟通 → 每日计数 +1
```

## 🛡️ 公司风险评估

DeepSeek **联网搜索**（非凭名字猜测）：
- 查询企业工商注册信息、经营状态
- 检测是否有劳动纠纷、拖欠工资记录
- 识别外包/中介/培训贷/皮包公司

风险等级：`SAFE(0-14)` → `LOW(15-34)` → `MEDIUM(35-59)` → `HIGH(60-100)`

## 🎯 AI 岗位匹配

四个维度实时分析：
- **技术栈匹配** — 岗位技能是否在简历中出现
- **经验匹配** — 经验/学历是否满足
- **岗位真实性** — 描述是否笼统空泛/刷KPI
- **方向匹配** — 是否在候选人专业方向上

评分：`≥75` 高度匹配 → `50-74` 部分匹配 → `<35` 完全不匹配

## 📊 每日计数

- 每次投递成功写入 `daily_count.json`
- 同一天多次运行自动累加，达到 150 上限自动停止
- 跨天自动归零，第二天重新计算

## 🗂️ 项目结构

```
auto-boss/
├── main.py            # 主入口（CLI）
├── config.yaml        # 配置文件
├── build.bat          # 打包脚本
├── boss_login.py      # BOSS直聘扫码登录
├── job_search.py      # 岗位搜索（API + DOM）
├── job_matcher.py     # 规则匹配打分
├── company_risk.py    # AI 风险评估 + 岗位匹配 + 关键词推荐
├── submitter.py       # 投递执行 + 每日计数
├── recorder.py        # 投递记录
├── resume_parser.py   # 简历解析
└── utils.py           # 工具函数
```

## 🔧 技术栈

- Python 3.10+
- DrissionPage（浏览器自动化，无 Selenium 痕迹）
- DeepSeek API（联网搜索 + 风险评估 + 岗位匹配）
- PyMuPDF / pdfplumber / python-docx（简历解析）
- PyYAML / requests / tkinter
- PyInstaller（打包）

## 📄 License

MIT
