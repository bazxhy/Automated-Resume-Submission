# Automated Resume Submission (BOSS直聘自动投递)

一键自动搜索、筛选、投递 BOSS直聘 岗位，支持简历解析 + 公司风险检测 + KPI 岗位识别。

## 功能

| 模块 | 功能 |
|------|------|
| 简历解析 | 支持 PDF / DOCX / TXT 格式，提取姓名、技能、工作经历 |
| 岗位搜索 | 多关键词滚动搜索，按城市 + 工作经验筛选 |
| 公司风险检测 | 识别外包/劳务派遣/诈骗公司，标记 MEDIUM/HIGH 风险 |
| KPI 刷量识别 | 检测薪资异常、描述笼统、同公司大量岗位等特征 |
| 岗位匹配 | 技能 + 经验 + 学历 + 薪资 + 关键词 五维打分 (0-100) |
| 一键投递 | 自动点击"立即沟通"，防重复投递，实时保存记录 |

## 安装

```bash
git clone https://github.com/bazxhy/Automated-Resume-Submission.git
cd Automated-Resume-Submission
pip install -r requirements.txt
```

## 使用

### 命令行

```bash
# 完整流程（需要扫码登录 BOSS直聘）
python main.py

# 仅搜索不投递（预览模式）
python main.py --search-only

# 仅测试简历解析
python main.py --resume-only

# 使用自定义配置
python main.py --config my_config.yaml
```

### GUI 桌面版

```bash
python gui.py
```

或打包为 exe：

```bash
build.bat
# 输出: dist/BOSS自动投递.exe
```

## 配置

编辑 `config.yaml`：

```yaml
search:
  keywords: ["嵌入式", "单片机", "STM32"]  # 搜索关键词
  city: "杭州"                              # 城市
  experience: "应届生"                      # 工作经验筛选

filter:
  min_match_score: 70                      # 最低匹配分
  skip_kpi: true                           # 过滤 KPI 刷量岗位
  exclude_titles: ["实习", "外包", "培训"]  # 标题排除

submit:
  daily_limit: 50                          # 每日最大投递数
  interval:
    min: 8                                  # 投递间隔(秒)
    max: 20
```

BOSS直聘工作经验代码：
| 选项 | 代码 |
|------|------|
| 经验不限 | 101 |
| 应届生 | 102 |
| 1年以内 | 103 |
| 1-3年 | 104 |
| 3-5年 | 105 |
| 5-10年 | 106 |
| 10年以上 | 107 |
| 在校生 | 108 |

## 项目结构

```
auto-boss/
├── main.py           # 主程序入口（命令行）
├── gui.py            # GUI 桌面版入口
├── config.yaml       # 配置文件
├── requirements.txt  # Python 依赖
├── build.bat         # 打包脚本
├── .gitignore
├── boss_login.py     # BOSS直聘登录（扫码/Cookie）
├── job_search.py     # 岗位搜索 + 卡片解析
├── job_matcher.py    # 岗位匹配度分析
├── company_risk.py   # 公司风险 + KPI 检测
├── submitter.py      # 投递执行（点击"立即沟通"）
├── recorder.py       # 投递记录（CSV + JSON）
├── resume_parser.py  # 简历解析（PDF/DOCX/TXT）
└── utils.py          # 工具函数
```

## 匹配度说明

| 维度 | 权重 | 满分 | 说明 |
|------|------|------|------|
| 技能匹配 | 40% | 40 | 简历技能 vs 岗位要求 |
| 经验匹配 | 20% | 20 | 工作年限对比 |
| 学历匹配 | 15% | 15 | 学历要求对比 |
| 薪资匹配 | 10% | 10 | 薪资范围重合度 |
| 关键词匹配 | 15% | 15 | JD 关键词 vs 简历文本 |
| 标题加分 | - | +15 | 岗位标题含嵌入式关键词 |

## 风险检测

### 公司风险

- 公司名含"人力资源/劳务派遣" → +35分
- 含"培训/理财/保险" → +30分
- 无行业/规模信息的泛化公司名 → +20分
- 薪资异常（max > min*5）→ +20分

风险等级：0-14=SAFE, 15-34=LOW, 35-59=MEDIUM(跳过), 60+=HIGH(跳过)

### KPI 刷量

- 标题含"急聘/大量招聘" → +15分
- 薪资范围 >5倍 → +20分
- 描述 <80字 → +10分
- 描述过于笼统 → +15分
- "弹性工作"+"抗压"组合 → +10分

KPI 得分 ≥60 自动跳过

## 技术栈

- Python 3.10+
- DrissionPage (浏览器自动化，无 Selenium 痕迹)
- PyMuPDF / pdfplumber (PDF 简历解析)
- python-docx (DOCX 简历解析)
- PyYAML (配置管理)
- tkinter (GUI)
- PyInstaller (打包)

## License

MIT
