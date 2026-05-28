"""
BOSS直聘 自动简历投递 — 精简版
搜一个关键词 → 全量滚动 → 全量投递 → 下一个关键词
"""

from __future__ import annotations

import argparse
import time
import random
from urllib.parse import quote
from datetime import datetime
from typing import Optional

from utils import load_config, setup_logger, get_logger

from resume_parser import ResumeParser, ResumeData
from boss_login import BossLogin
from job_search import JobSearcher, JobPosting
from company_risk import CompanyRiskChecker, RiskLevel
from job_matcher import JobMatcher
from submitter import JobSubmitter, SubmitResult
from recorder import ApplyRecorder


class AutoBossApp:

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.logger = get_logger("app")
        self.browser = None
        self.resume: Optional[ResumeData] = None
        self.logger.info(f"启动 {datetime.now():%Y-%m-%d %H:%M:%S}")

    def run(self, search_only: bool = False, resume_only: bool = False):
        try:
            # 1. 简历
            self.logger.info("解析简历...")
            parser = ResumeParser(self.config["resume"]["file_path"])
            self.resume = parser.parse()
            if resume_only:
                return

            # 2. 登录
            self.logger.info("登录 BOSS直聘...")
            login = BossLogin(self.config)
            self.browser = login.login()

            # 3. 初始化模块
            searcher = JobSearcher(self.browser, self.config)
            risk_checker = CompanyRiskChecker(self.config)
            matcher = JobMatcher(self.resume)
            submitter = JobSubmitter(self.browser, self.config)
            recorder = ApplyRecorder(self.config)

            # 加载历史成功URL（跨运行去重）
            old_success = set()
            for r in recorder._records:
                if r.get("result") == "投递成功" and r.get("url"):
                    old_success.add(r["url"])
            self.logger.info(f"历史已投递 {len(old_success)} 个")

            cfg = self.config
            filter_cfg = cfg.get("filter", {})
            min_score = filter_cfg.get("min_match_score", 40)
            skip_kpi = filter_cfg.get("skip_kpi", True)
            kpi_threshold = filter_cfg.get("skip_kpi_score", 60)
            exclude_titles = [k.lower() for k in filter_cfg.get("exclude_titles", [])]
            keywords = cfg["search"]["keywords"]
            experience = cfg["search"].get("experience", "")
            exp_code = searcher.EXPERIENCE_CODES.get(experience, "")

            stats = {"success": 0, "fail": 0, "risk": 0, "kpi": 0,
                     "match": 0, "dup": 0, "excl": 0, "already": 0}

            # ---- 主循环：每个关键词依次全量处理 ----
            for keyword in keywords:
                self.logger.info(f"\n{'='*40}")
                self.logger.info(f"🔍 {keyword}")

                # 导航到搜索页
                url = f"https://www.zhipin.com/web/geek/job?query={quote(keyword)}&city={searcher.city_code}"
                if exp_code:
                    url += f"&experience={exp_code}"
                tab = self.browser.latest_tab
                tab.get(url)
                tab.wait(4)
                self._scroll(tab)

                # 滚动加载 + 收集所有岗位
                all_jobs: list[JobPosting] = []
                seen = set()
                for _ in range(10):  # 最多滚10轮
                    tab.wait(2)
                    self._scroll_bottom(tab)
                    page_jobs = searcher._parse_page(tab)
                    new = [j for j in page_jobs if j.url and j.url not in seen]
                    if not new:
                        break
                    for j in new:
                        seen.add(j.url)
                    all_jobs.extend(new)
                    self.logger.info(f"  滚动: +{len(new)} (累计{len(all_jobs)})")

                self.logger.info(f"  共 {len(all_jobs)} 个岗位，开始投递...")

                # 逐个投递
                for i, job in enumerate(all_jobs, 1):
                    title_lower = job.title.lower()

                    # 跳过历史已投递
                    if job.url in old_success:
                        stats["dup"] += 1
                        self.logger.info(f"  ⏭️ 已投过: {job.title[:30]}")
                        continue

                    # 标题过滤
                    if any(k in title_lower for k in exclude_titles):
                        stats["excl"] += 1
                        continue

                    # 学历过滤：本科只投本科及以下
                    edu = (job.education or "").strip()
                    if any(d in edu for d in ("硕士", "博士", "研究生")):
                        stats["excl"] += 1
                        self.logger.info(f"  🎓 学历不符({edu}): {job.title[:30]}")
                        continue

                    # 技能过滤：不投 C# / Java
                    skills_lower = [s.lower() for s in (job.skills_required or [])]
                    if any(k in skills_lower for k in ("c#", "java")):
                        stats["excl"] += 1
                        self.logger.info(f"  ☕ 技能不符(C#/Java): {job.title[:30]}")
                        continue

                    # 公司风险
                    risk = risk_checker.check(job.company, job.to_dict())
                    if risk.level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
                        recorder.record(job, None, risk, SubmitResult.RISK_REJECTED)
                        stats["risk"] += 1
                        continue

                    # KPI
                    if skip_kpi:
                        kpi = risk_checker.check_kpi(job.to_dict(), job.company)
                        if kpi.score >= kpi_threshold:
                            recorder.record(job, None, None, SubmitResult.KPI_REJECTED)
                            stats["kpi"] += 1
                            continue

                    # 匹配
                    match = matcher.match(job)
                    score = match.total_score
                    if not search_only and score < min_score:
                        recorder.record(job, match, None, SubmitResult.MATCH_LOW)
                        stats["match"] += 1
                        continue

                    if search_only:
                        self.logger.info(
                            f"  [{i}] {job.title[:30]} | "
                            f"{job.salary} | 匹配{score:.0f} | 风险{risk.level.value}"
                        )
                        continue

                    # 投递
                    self.logger.info(
                        f"  🚀 [{i}/{len(all_jobs)}] {job.title[:35]} 匹配{score:.0f}"
                    )
                    result = submitter.submit(job, score)
                    recorder.record(job, match, None, result)
                    recorder.save_json()

                    if result == SubmitResult.SUCCESS:
                        old_success.add(job.url)
                        stats["success"] += 1
                        d = random.uniform(*[cfg["submit"]["interval"][k] for k in ("min", "max")])
                        self.logger.info(f"  ✅ 等待 {d:.0f}s")
                        time.sleep(d)
                    elif result == SubmitResult.DAILY_LIMIT:
                        self.logger.warning("⚠️ 已达每日投递上限，退出")
                        recorder.save_json()
                        self._print_stats(stats)
                        return
                    elif result == SubmitResult.ALREADY_APPLIED:
                        old_success.add(job.url)
                        stats["already"] += 1
                    else:
                        stats["fail"] += 1

            # 汇总
            self._print_stats(stats)
            recorder.save_json()

        except KeyboardInterrupt:
            self.logger.warning("用户中断")
        finally:
            if self.browser:
                try: self.browser.quit()
                except: pass

    def _scroll(self, tab):
        for _ in range(3):
            try: tab.run_js("window.scrollBy(0, 500)")
            except: pass
            time.sleep(0.3)

    def _scroll_bottom(self, tab):
        try: tab.run_js("window.scrollTo(0, document.body.scrollHeight)")
        except: pass
        time.sleep(2)

    def _print_stats(self, stats: dict):
        self.logger.info(f"\n{'='*40}")
        self.logger.info(
            f"✅投递{stats['success']} ⛔风险{stats['risk']} "
            f"🚫KPI{stats['kpi']} ⏭️匹配{stats['match']} "
            f"📋已投{stats['dup']} ⚠️已沟通{stats['already']} "
            f"🔇过滤{stats['excl']} ❌失败{stats['fail']}"
        )


def main():
    p = argparse.ArgumentParser(description="BOSS直聘自动投递")
    p.add_argument("--config", "-c", default="config.yaml")
    p.add_argument("--search-only", "-s", action="store_true")
    p.add_argument("--resume-only", "-r", action="store_true")
    args = p.parse_args()

    for name in ["app","resume","login","jobs","risk","matcher","submit","recorder"]:
        setup_logger(name, "INFO")

    app = AutoBossApp(args.config)
    app.run(search_only=args.search_only, resume_only=args.resume_only)


if __name__ == "__main__":
    main()
