"""
岗位搜索模块 — DrissionPage 版本
"""

from __future__ import annotations

import re
import time
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from DrissionPage import Chromium
from utils import clean_text, random_delay, extract_salary_range, get_logger

if TYPE_CHECKING:
    from DrissionPage._pages.chromium_tab import ChromiumTab

logger = get_logger("jobs")

_JOB_URL_RE = re.compile(r'/job_detail/|jobId=|/web/geek/job\?')
_SALARY_RE = re.compile(r'\d+K', re.IGNORECASE)
_GARBAGE_RE = re.compile(
    r'热线|举报|ICP|营业执照|经营许可|公网安备|网安\d+号',
    re.IGNORECASE,
)
_SCHEDULE_RE = re.compile(r'^\d+天/周$|^\d+个月$|^\d+小时$')
_PHONE_RE = re.compile(r'^[\d\s\-()（）]+$')
_BOSS_RE = re.compile(r'(先生|女士|在线|离线|活跃|新职位|回复率)')


def _is_salary(line: str) -> bool:
    return bool(_SALARY_RE.search(line)) or "元" in line

def _is_company(line: str) -> bool:
    if not line or len(line) < 2 or len(line) > 50:
        return False
    if _GARBAGE_RE.search(line): return False
    if _SCHEDULE_RE.match(line.strip()): return False
    if _PHONE_RE.match(line.strip()): return False
    if _is_salary(line): return False
    # HR名称模式：只有2-4字且包含"先生/女士/在线"
    if len(line) <= 4 and _BOSS_RE.search(line): return False
    return True

def _is_title(line: str) -> bool:
    if not line or len(line) < 2 or len(line) > 50: return False
    if _GARBAGE_RE.search(line): return False
    return True


@dataclass
class JobPosting:
    title: str = ""
    company: str = ""
    salary: str = ""
    salary_min: float = 0.0
    salary_max: float = 0.0
    location: str = ""
    experience: str = ""
    education: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""
    skills_required: list[str] = field(default_factory=list)
    url: str = ""
    company_size: str = ""
    company_industry: str = ""
    boss_name: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title, "company": self.company, "salary": self.salary,
            "salary_min": self.salary_min, "salary_max": self.salary_max,
            "location": self.location, "experience": self.experience,
            "education": self.education, "tags": self.tags,
            "description": self.description[:500] if self.description else "",
            "skills_required": self.skills_required, "url": self.url,
            "company_size": self.company_size, "company_industry": self.company_industry,
            "boss_name": self.boss_name,
        }


class JobSearcher:

    TECH_KEYWORDS = [
        "C", "C++", "Python", "RTOS", "FreeRTOS", "Linux", "ARM", "STM32",
        "单片机", "嵌入式", "驱动", "I2C", "SPI", "UART", "CAN", "TCP/IP",
        "DSP", "FPGA", "ZigBee", "BLE", "Keil", "IAR", "GCC", "Git",
    ]

    CITY_CODES = {
        "北京": "101010100", "上海": "101020100",
        "广州": "101280100", "深圳": "101280600",
        "杭州": "101210100", "成都": "101270100",
        "南京": "101190100", "武汉": "101200100",
        "西安": "101110100", "长沙": "101250100",
        "重庆": "101040100", "苏州": "101190400",
        "天津": "101030100",
    }

    EXPERIENCE_CODES = {
        "应届生": "102", "在校生": "108", "经验不限": "101",
        "1年以内": "103", "1-3年": "104",
        "3-5年": "105", "5-10年": "106", "10年以上": "107",
    }

    def __init__(self, browser: Chromium, config: dict):
        self.browser = browser
        self.cfg = config
        search_cfg = config["search"]
        self.keywords = search_cfg.get("keywords", ["嵌入式"])
        self.city = search_cfg.get("city", "杭州")
        self.city_code = self.CITY_CODES.get(self.city, self.city)
        self.experience = search_cfg.get("experience", "")
        self.exp_code = self.EXPERIENCE_CODES.get(self.experience, "")
        self.page_limit = search_cfg.get("page_limit", 5)
        self.jobs_per_page = search_cfg.get("jobs_per_page", 15)
        self.filter_cfg = config.get("filter", {})

    # ==================== 卡片查找 ====================

    def _find_card_elements(self, tab) -> list:
        """通过 a 标签链接向上找卡片容器，按 DOM 元素去重"""
        card_set: set[int] = set()
        results: list = []

        # 多语法兜底
        all_links = tab.eles("tag:a")
        if not all_links:
            all_links = tab.eles("a")
        if not all_links:
            all_links = tab.eles("t:a")
        if not all_links:
            logger.warning("  页面未找到任何 a 标签")
            return results

        for a in all_links:
            try:
                href = a.link
            except Exception:
                continue
            if not href or not _JOB_URL_RE.search(str(href)):
                continue

            for level in (2, 3, 4):
                try:
                    card = a.parent(level)
                    if card is None:
                        continue
                    cid = id(card)
                    if cid in card_set:
                        continue
                    txt = card.text or ""
                    if len(txt) < 15:
                        continue
                    if len(txt) > 2000:  # 太大=列表容器
                        continue
                    if _GARBAGE_RE.search(txt[:200]):
                        continue
                    card_set.add(cid)
                    results.append(card)
                    break
                except Exception:
                    continue

        logger.info(f"  定位到 {len(results)} 个独立卡片")
        return results

    # ==================== 页面解析 ====================

    def _parse_page(self, tab) -> list[JobPosting]:
        cards = self._find_card_elements(tab)
        if not cards:
            return []

        jobs = []
        seen_urls: set[str] = set()
        for card in cards:
            try:
                job = self._parse_card(card)
                if not job or not job.title:
                    continue
                if job.url and job.url in seen_urls:
                    continue
                if job.url:
                    seen_urls.add(job.url)
                if not job.company:
                    job.company = "未知公司"
                jobs.append(job)
            except Exception:
                continue
        return jobs

    def _parse_card(self, card) -> Optional[JobPosting]:
        job = JobPosting()

        try:
            text = card.text
        except Exception:
            return None
        if not text or len(text) < 15:
            return None
        if _GARBAGE_RE.search(text[:100]):
            return None

        # ---- URL + 标题：从 a 标签直接拿 ----
        for a in (card.eles("tag:a") or []):
            try:
                href = a.link
            except Exception:
                continue
            if href and _JOB_URL_RE.search(str(href)):
                if not job.url:
                    job.url = href if href.startswith("http") else f"https://www.zhipin.com{href}"
                if not job.title:
                    t = (a.text or "").strip()
                    if _is_title(t):
                        job.title = t

        if not job.title:
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            for line in lines:
                if _is_title(line) and not _is_salary(line):
                    job.title = line
                    break
            if not job.title and lines:
                job.title = lines[0]

        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # ---- 薪资 ----
        for line in lines:
            if _is_salary(line):
                job.salary = line
                job.salary_min, job.salary_max = extract_salary_range(line)
                break
        if not job.salary:
            job.salary = "面议"

        # ---- 公司名：找薪资行后或标题行后的第一个合法行 ----
        passed_salary = False
        for line in lines:
            if _is_salary(line):
                passed_salary = True
                continue
            if passed_salary and _is_company(line) and line != job.title:
                job.company = line
                break
        # 无薪资时，从标题后找
        if not job.company:
            for line in lines:
                if line == job.title:
                    continue
                if _is_company(line):
                    job.company = line
                    break

        # ---- 地点/经验/学历 ----
        for line in lines:
            if "·" in line or "经验" in line or "应届" in line or "年" in line:
                for p in line.replace(" ", "").split("·"):
                    p = p.strip()
                    if any(c in p for c in self.CITY_CODES):
                        job.location = p
                    elif any(w in p for w in ("经验", "应届", "年", "在校")):
                        job.experience = p
                    elif any(d in p for d in ("本科", "大专", "硕士", "博士", "学历")):
                        job.education = p

        # ---- 技能：从全文本 + 标题提取 ----
        job.skills_required = self._extract_skills(text + " " + job.title)
        return job

    # ==================== 滚动 ====================

    def _scroll_page(self, tab):
        for _ in range(4):
            try:
                tab.run_js("window.scrollBy(0, 600)")
            except Exception:
                pass
            time.sleep(0.4)

    # ==================== 搜索入口（备用） ====================

    def search_all(self) -> list[JobPosting]:
        all_jobs: dict[str, JobPosting] = {}
        for keyword in self.keywords:
            jobs = self._search_one(keyword)
            for job in jobs:
                key = job.url or (job.title + job.company)
                if key not in all_jobs:
                    all_jobs[key] = job
        return list(all_jobs.values())

    def _search_one(self, keyword: str) -> list[JobPosting]:
        results = []
        tab = self.browser.latest_tab
        url = f"https://www.zhipin.com/web/geek/job?query={quote(keyword)}&city={self.city_code}"
        if self.exp_code:
            url += f"&experience={self.exp_code}"
        tab.get(url)
        tab.wait(4)
        self._scroll_page(tab)
        for _ in range(self.page_limit):
            tab.wait(2)
            self._scroll_page(tab)
            jobs = self._parse_page(tab)
            if not jobs:
                break
            results.extend(jobs)
        return results

    def _extract_skills(self, text: str) -> list[str]:
        if not text: return []
        lower = text.lower()
        return [s for s in self.TECH_KEYWORDS if s.lower() in lower]
