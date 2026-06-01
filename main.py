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

from utils import load_config, setup_logger, get_logger, find_resume_file

from resume_parser import ResumeParser, ResumeData
from boss_login import BossLogin
from job_search import JobSearcher, JobPosting
from company_risk import CompanyRiskChecker, RiskLevel, RiskResult
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

    def run(self, search_only: bool = False, resume_only: bool = False,
            resume_path: Optional[str] = None):
        try:
            # 1. 简历 — CLI 参数 > 配置文件 > 自动扫描
            self.logger.info("解析简历...")
            path = resume_path or self.config["resume"].get("file_path", "")
            if not path:
                found = find_resume_file()
                if not found:
                    raise FileNotFoundError("未找到简历文件！请用 --resume 指定")
                path = str(found)
                self.logger.info(f"  自动检测到简历: {found.name}")
            parser = ResumeParser(path)
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

            self.logger.info(f"今日已投 {submitter.get_today_count()}/{submitter.daily_limit}")
            if submitter.get_today_count() >= submitter.daily_limit:
                self.logger.warning(f"今日已达上限 {submitter.daily_limit}，退出")
                return

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
            experience = cfg["search"].get("experience", "")
            exp_code = searcher.EXPERIENCE_CODES.get(experience, "")

            # 搜索关键词：AI 模式根据简历自动推荐 → 配置文件回退
            if filter_cfg.get("ai_fit_check") and self.resume:
                ai_keywords = risk_checker.suggest_search_keywords(
                    self.resume.raw_text)
                if ai_keywords:
                    keywords = ai_keywords
                else:
                    self.logger.info("  AI关键词推荐失败，使用配置文件关键词")
                    keywords = cfg["search"]["keywords"]
            else:
                keywords = cfg["search"]["keywords"]

            risk_cache: dict[str, RiskResult] = {}

            ai_fit_check = filter_cfg.get("ai_fit_check", False)
            ai_fit_min = filter_cfg.get("ai_fit_min_score", 40)

            stats = {"success": 0, "fail": 0, "risk": 0, "kpi": 0, "fit": 0,
                     "match": 0, "dup": 0, "excl": 0, "already": 0}

            # ---- 主循环：每个关键词依次全量处理 ----
            for keyword in keywords:
                self.logger.info(f"\n{'='*40}")
                self.logger.info(f"🔍 {keyword}")

                url = f"https://www.zhipin.com/web/geek/job?query={quote(keyword)}&city={searcher.city_code}"
                if exp_code:
                    url += f"&experience={exp_code}"
                tab = self.browser.latest_tab
                tab.get(url)
                tab.wait(3)

                all_jobs: list[JobPosting] = []
                seen = set()

                # 优先 API 模式（完整公司名/学历数据）
                page1 = searcher._fetch_api_jobs(tab, keyword, 1)
                if page1:
                    for p in range(1, 11):
                        pjobs = searcher._fetch_api_jobs(tab, keyword, p)
                        if not pjobs: break
                        new = [j for j in pjobs if j.url and j.url not in seen]
                        if not new: break
                        for j in new: seen.add(j.url)
                        all_jobs.extend(new)
                        self.logger.info(f"  第{p}页: +{len(new)} (累计{len(all_jobs)})")
                        time.sleep(0.5)
                else:
                    # 回退到 DOM 滚动模式
                    self.logger.info("  API 不可用，回退滚动DOM模式...")
                    tab.wait(2)
                    self._scroll(tab)
                    for _ in range(10):
                        tab.wait(2)
                        self._scroll_bottom(tab)
                        pjobs = searcher._parse_page(tab)
                        new = [j for j in pjobs if j.url and j.url not in seen]
                        if not new: break
                        for j in new: seen.add(j.url)
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

                    # 学历过滤：根据配置的最高学历限制
                    max_edu = filter_cfg.get("max_education", "")
                    if max_edu:
                        edu = (job.education or "").strip()
                        # 标题中也检测学历关键词（兜底卡片解析不到的情况）
                        if not edu:
                            edu = job.title or ""
                        if self._education_too_high(edu, max_edu):
                            stats["excl"] += 1
                            self.logger.info(f"  🎓 学历不符({edu[:20]}): {job.title[:30]}")
                            continue

                    # 技能过滤：不投 C# / Java
                    skills_lower = [s.lower() for s in (job.skills_required or [])]
                    if any(k in skills_lower for k in ("c#", "java")):
                        stats["excl"] += 1
                        self.logger.info(f"  ☕ 技能不符(C#/Java): {job.title[:30]}")
                        continue

                    # 公司风险（缓存同一公司避免重复调 API）
                    risk = None
                    if job.company != "未知公司":
                        risk = risk_cache.get(job.company) or risk_checker.check(job.company, job.to_dict())
                        risk_cache[job.company] = risk
                    if risk and risk.level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
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

                    # 岗位匹配：AI 模式实时分析简历 → 规则模式关键词打分
                    score = 0
                    match = None
                    if ai_fit_check and self.resume:
                        # AI 匹配（DeepSeek 实时对照简历分析）
                        ai = risk_checker.match_job(self.resume.raw_text, job.to_dict())
                        if ai is not None:
                            score = ai["score"]
                            if not ai["fit"] or score < ai_fit_min:
                                stats["fit"] += 1
                                self.logger.info(
                                    f"  🎯 AI不匹配(score={score}): "
                                    f"{'; '.join(ai.get('reasons', [])[:2])[:60]}"
                                )
                                continue
                        else:
                            # AI 失败回退到规则匹配
                            match = matcher.match(job)
                            score = match.total_score
                            if not search_only and score < min_score:
                                recorder.record(job, match, None, SubmitResult.MATCH_LOW)
                                stats["match"] += 1
                                continue
                    else:
                        # 规则匹配
                        match = matcher.match(job)
                        score = match.total_score
                        if not search_only and score < min_score:
                            recorder.record(job, match, None, SubmitResult.MATCH_LOW)
                            stats["match"] += 1
                            continue

                    if search_only:
                        risk_label = risk.level.value if risk else "skip"
                        self.logger.info(
                            f"  [{i}] {job.title[:30]} | "
                            f"{job.salary} | 匹配{score:.0f} | 风险{risk_label}"
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

    _EDU_RANKS = {"学历不限":0,"不限":0,"高中":1,"中专":2,"大专":3,
                  "本科":4,"学士":4,"硕士":5,"研究生":5,"研":5,"硕":5,
                  "博士":6,"博":6,"博士后":6}

    @classmethod
    def _education_too_high(cls, job_edu: str, max_edu: str) -> bool:
        """岗位要求的学历是否超过限制"""
        if not job_edu: return False
        jr = max((cls._EDU_RANKS.get(k, 0) for k in cls._EDU_RANKS if k in job_edu), default=0)
        mr = cls._EDU_RANKS.get(max_edu, 4)
        return jr > mr

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
            f"🚫KPI{stats['kpi']} 🎯AI不适合{stats['fit']} "
            f"⏭️匹配{stats['match']} 📋已投{stats['dup']} "
            f"⚠️已沟通{stats['already']} 🔇过滤{stats['excl']} ❌失败{stats['fail']}"
        )


def main():
    p = argparse.ArgumentParser(description="BOSS直聘自动投递")
    p.add_argument("--config", "-c", default="config.yaml")
    p.add_argument("--resume", "-r", default=None, help="简历文件路径")
    p.add_argument("--search-only", "-s", action="store_true")
    p.add_argument("--resume-only", "-ro", action="store_true")
    args = p.parse_args()

    for name in ["app","resume","login","jobs","risk","matcher","submit","recorder"]:
        setup_logger(name, "INFO")

    app = AutoBossApp(args.config)
    app.run(search_only=args.search_only, resume_only=args.resume_only,
            resume_path=args.resume)


if __name__ == "__main__":
    main()
