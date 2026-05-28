"""
投递执行模块 — DrissionPage 版本
BOSS直聘: 打开岗位详情 → 点击「立即沟通」→ 系统自动发送招呼语
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from DrissionPage import Chromium
from job_search import JobPosting
from utils import get_logger

if TYPE_CHECKING:
    from DrissionPage._pages.chromium_tab import ChromiumTab

logger = get_logger("submit")


class SubmitResult:
    SUCCESS = "success"
    SKIPPED = "skipped"
    ALREADY_APPLIED = "already_applied"
    LOGIN_REQUIRED = "login_required"
    DAILY_LIMIT = "daily_limit"
    FAILED = "failed"
    RISK_REJECTED = "risk_rejected"
    MATCH_LOW = "match_low"
    KPI_REJECTED = "kpi_rejected"


class JobSubmitter:

    def __init__(self, browser: Chromium, config: dict):
        self.browser = browser
        self.cfg = config
        submit_cfg = config.get("submit", {})
        self.greeting = submit_cfg.get(
            "greeting",
            "您好，我是2026届信息工程专业本科毕业生，比较匹配贵公司岗位的招聘要求，可以发个简历给您看看吗？"
        )
        self.daily_limit = submit_cfg.get("daily_limit", 50)
        self._today_count = 0

    def submit(self, job: JobPosting, match_score: float) -> str:
        """打开岗位 → 点立即沟通 → 系统自动发消息"""

        if self._today_count >= self.daily_limit:
            logger.warning(f"已达每日上限 ({self.daily_limit})")
            return SubmitResult.DAILY_LIMIT

        logger.info(
            f"  投递 [{self._today_count + 1}/{self.daily_limit}] "
            f"{job.title} @ {job.company}"
        )

        if not job.url:
            logger.warning("  ❌ 无岗位链接")
            return SubmitResult.FAILED

        # 用新标签页投递，不影响搜索页
        submit_tab = None
        try:
            submit_tab = self.browser.new_tab(job.url)
            submit_tab.wait(4)
            self._scroll(submit_tab)

            cur_url = str(submit_tab.url).lower()
            if "login" in cur_url:
                logger.warning("  ⚠️ 跳转登录页")
                return SubmitResult.LOGIN_REQUIRED

            if self._already_contacted(submit_tab):
                logger.info("  ⚠️ 已沟通过")
                return SubmitResult.ALREADY_APPLIED

            if not self._click_contact(submit_tab):
                return SubmitResult.FAILED

            time.sleep(1)
            self._today_count += 1
            logger.info(
                f"  ✅ 沟通已发起 ({self._today_count}/{self.daily_limit})"
            )
            return SubmitResult.SUCCESS

        except Exception as e:
            logger.error(f"  ❌ 投递异常: {e}")
            return SubmitResult.FAILED

        finally:
            if submit_tab:
                try:
                    submit_tab.close()
                except Exception:
                    pass

    # ==================== 页面状态检测 ====================

    def _already_contacted(self, tab) -> bool:
        try:
            html = tab.html[:3000]
            if any(s in html for s in ["已沟通过", "继续沟通", "已投递", "已发送"]):
                return True
        except Exception:
            pass
        return False

    # ==================== 点击沟通按钮 ====================

    def _click_contact(self, tab) -> bool:
        """多策略查找并点击「立即沟通」"""

        # 策略 1: 精确文本
        for text in ["立即沟通", "立即沟通", "聊一聊", "发消息", "投递简历"]:
            try:
                btn = tab.ele(f"text:{text}")
                if btn:
                    btn.click()
                    logger.info(f"  👆 点击「{text}」")
                    return True
            except Exception:
                continue

        # 策略 2: 包含文本（@@text() 是 DrissionPage 的模糊匹配）
        for text in ["沟通", "投递"]:
            try:
                btn = tab.ele(f"@@text():{text}")
                if btn:
                    btn.click()
                    logger.info(f"  👆 点击含「{text}」的按钮")
                    return True
            except Exception:
                continue

        # 策略 3: CSS 选择器
        for sel in [
            'a[class*="btn"][class*="chat"]',
            'span[class*="op-btn"]',
            '[class*="chat-btn"]',
            '[class*="contact-btn"]',
            'div[class*="op-btn"]',
            '[class*="start-chat"]',
        ]:
            try:
                btn = tab.ele(sel)
                if btn:
                    btn.click()
                    logger.info(f"  👆 CSS匹配: {sel}")
                    return True
            except Exception:
                continue

        # 策略 4: 全页扫描所有元素，找包含关键词的
        try:
            all_els = tab.eles("tag:span, tag:a, tag:button, tag:div")
            for el in (all_els or []):
                try:
                    t = (el.text or "").strip()
                    if any(w in t for w in ["立即沟通", "沟通"]) and len(t) <= 15:
                        el.click()
                        logger.info(f"  👆 全页扫描命中: 「{t}」")
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        logger.warning("  ❌ 未找到「立即沟通」按钮")
        self._debug_page(tab)
        return False

    def _debug_page(self, tab):
        """打印页面信息帮助排查"""
        try:
            body = tab.ele("tag:body")
            if body:
                txt = body.text[:400].replace("\n", " | ")
                logger.info(f"  页面内容: {txt}")
        except Exception:
            pass

    # ==================== 辅助 ====================

    def _scroll(self, tab):
        for _ in range(2):
            try:
                tab.run_js("window.scrollBy(0, 300)")
            except Exception:
                pass
            time.sleep(0.3)

    def get_today_count(self) -> int:
        return self._today_count
