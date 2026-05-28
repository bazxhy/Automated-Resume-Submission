"""
公司风险检测模块 — 含 KPI/诈骗公司识别

支持两种模式:
  - rule: 基于规则的关键词/规模/行业检测（免费离线）
  - api:  调用企查查/天眼查 API 获取企业风险数据（需配置 token）

返回 RiskLevel 枚举: SAFE / LOW / MEDIUM / HIGH
"""

from __future__ import annotations

import re
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

import requests
from utils import get_logger

logger = get_logger("risk")


class RiskLevel(Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class RiskResult:
    level: RiskLevel = RiskLevel.SAFE
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def is_safe(self) -> bool:
        return self.level in (RiskLevel.SAFE, RiskLevel.LOW)

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "score": self.score,
            "reasons": self.reasons,
            "safe": self.is_safe,
        }


# ==================== 风险关键词库 ====================

# 人力资源/外包/劳务公司 — 几乎100%是中介
HR_OUTSOURCE_INDICATORS = [
    "人力资源", "劳务派遣", "外包服务", "人才服务",
    "企业管理咨询", "信息技术服务", "网络科技", "信息科技",
]

# 公司名模式：XX科技/XX网络 — 需要结合其他信号判断
GENERIC_COMPANY_SUFFIX = [
    "科技有限公司", "网络科技有限公司", "信息技术有限公司",
    "电子商务有限公司", "贸易有限公司",
]

# 公司名含以下词 → 高风险
COMPANY_NAME_HIGH_RISK = [
    "劳务", "外包", "派遣", "中介", "猎头",
    "培训学校", "培训机构", "教育咨询", "辅导",
    "理财", "投资管理", "资产管理", "财富",
    "保险代理", "保险经纪",
    "融资租赁", "小额贷款", "担保",
    "文化传媒", "影视传媒", "直播",
]

# 岗位描述中的 KPI/诈骗 信号词
KPI_PHRASES = [
    "有较强的抗压能力", "抗压能力强", "能承受较大工作压力",
    "弹性工作制", "弹性工作",
    "适应高强度", "服从加班", "适应加班",
    "无底薪", "有责底薪", "责任底薪",
    "自带客户", "自带资源",
    "试用期不交社保", "试用期无社保",
    "入职后培训", "先培训", "岗前培训",
    "提供住宿", "包住宿",  # 可能是工厂/外地招聘
    "996", "007", "大小周",
]

# 刷 KPI 的典型特征
KPI_TITLE_KEYWORDS = [
    "急聘", "急招", "高薪急聘", "大量招聘", "诚聘",
    "月入过万", "轻松", "简单", "小白",
]

# 过于笼统的描述特征（可能是刷KPI的）
GENERIC_DESC_PATTERNS = [
    "负责日常", "完成领导", "完成上级",
    "协助部门", "配合团队", "参与项目",
]

# 高风险行业
RISKY_INDUSTRIES = [
    "培训", "保险", "理财", "P2P", "信贷",
    "教育", "房地产中介", "证券",
]


class CompanyRiskChecker:

    def __init__(self, config: dict):
        risk_cfg = config.get("risk_check", {})
        self.mode = risk_cfg.get("mode", "rule")
        self.risk_keywords = risk_cfg.get("risk_keywords", [])
        self.api_cfg = risk_cfg.get("api", {})

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

        # 跟踪：同公司有多少岗位
        self._company_job_count: dict[str, int] = {}

        logger.info(f"风险检测模式: {self.mode}")

    def check(self, company_name: str, job: Optional[dict] = None) -> RiskResult:
        if self.mode == "api" and self.api_cfg.get("token"):
            return self._check_via_api(company_name)
        else:
            return self._check_via_rules(company_name, job)

    def check_kpi(self, job: dict, company_name: str = "") -> RiskResult:
        """专门检测岗位是否为 KPI 刷量岗位 (0=正常, 100=明显KPI)"""
        result = RiskResult(level=RiskLevel.SAFE)
        score = 0
        reasons = []

        title = job.get("title", "")
        desc = job.get("description", "")
        salary_min = job.get("salary_min", 0)
        salary_max = job.get("salary_max", 0)

        # KPI 1: 标题含 KPI 关键词
        for kw in KPI_TITLE_KEYWORDS:
            if kw in title:
                score += 15
                reasons.append(f"标题含 KPI 关键词: 「{kw}」")
                break

        # KPI 2: 薪资范围过大 (>5倍)
        if salary_min > 0 and salary_max > salary_min * 5:
            score += 20
            reasons.append(f"薪资范围过大 ({salary_min:.0f}-{salary_max:.0f})，疑似 KPI 岗")
        elif salary_min > 0 and salary_max > salary_min * 3:
            score += 8
            reasons.append(f"薪资范围偏大 ({salary_min:.0f}-{salary_max:.0f})")

        # KPI 3: 岗位描述含高压/坑人描述
        for phrase in KPI_PHRASES:
            if phrase in desc:
                score += 20
                reasons.append(f"描述含风险表述: 「{phrase}」")
                break

        # KPI 4: 描述过于笼统（可能是模板生成的）
        if desc:
            generic_count = sum(1 for p in GENERIC_DESC_PATTERNS if p in desc)
            if generic_count >= 3:
                score += 15
                reasons.append("岗位描述过于笼统，疑似复制模板")
            elif generic_count >= 2:
                score += 8
                reasons.append("岗位描述偏笼统")

            # KPI 5: 描述太短 (<80字)
            if len(desc) < 80:
                score += 10
                reasons.append(f"岗位描述过短({len(desc)}字)，可能为虚岗")
            elif len(desc) < 150:
                score += 5

        # KPI 6: 同公司挂多个岗位（累计跟踪）
        if company_name:
            self._company_job_count[company_name] = self._company_job_count.get(company_name, 0) + 1
            count = self._company_job_count[company_name]
            if count >= 10:
                score += 15
                reasons.append(f"该公司已挂 {count} 个岗位，疑似刷量")

        # KPI 7: "弹性工作" + "抗压" 组合
        if "弹性" in desc and ("抗压" in desc or "加班" in desc):
            score += 10
            reasons.append("「弹性工作」+「抗压/加班」组合，实为变相996")

        # KPI 8: 没有明确的技能要求
        skills = job.get("skills_required", [])
        if isinstance(skills, list) and len(skills) <= 1:
            score += 5

        score = max(0, min(100, score))
        result.score = score

        if score >= 60:
            result.level = RiskLevel.HIGH
        elif score >= 35:
            result.level = RiskLevel.MEDIUM
        elif score >= 15:
            result.level = RiskLevel.LOW
        else:
            result.level = RiskLevel.SAFE

        result.reasons = reasons
        return result

    # ==================== 规则模式 ====================

    def _check_via_rules(self, name: str, job: Optional[dict] = None) -> RiskResult:
        result = RiskResult()
        name_lower = name.lower()
        score = 0
        reasons = []

        # ———— 公司名维度 ————

        # 1. 人力资源/外包关键词
        for indicator in HR_OUTSOURCE_INDICATORS:
            if indicator in name:
                score += 35
                reasons.append(f"公司含「{indicator}」，可能为外包/中介")
                break

        # 2. 高风险公司名关键词
        for kw in COMPANY_NAME_HIGH_RISK:
            if kw in name:
                score += 30
                reasons.append(f"公司名含高风险词: 「{kw}」")
                break

        # 3. 配置中的自定义风险关键词
        for kw in self.risk_keywords:
            if kw in name_lower:
                score += 25
                reasons.append(f"匹配自定义风险关键词: {kw}")

        # 4. 过于通用的公司名后缀（XX科技有限公司）+ 无具体信息
        is_generic_name = any(name.endswith(suf) for suf in GENERIC_COMPANY_SUFFIX)
        if is_generic_name and job:
            has_industry = bool(job.get("company_industry", ""))
            has_size = bool(job.get("company_size", ""))
            if not has_industry and not has_size:
                score += 20
                reasons.append("公司名称过于通用且无行业/规模信息")
            elif not has_industry:
                score += 10
                reasons.append("公司名称通用且无行业信息")

        # ———— 岗位维度 ————

        if job:
            size = job.get("company_size", "")
            industry = job.get("company_industry", "")
            desc = job.get("description", "")
            salary_min = job.get("salary_min", 0)
            salary_max = job.get("salary_max", 0)

            # 5. 高风险行业
            for ri in RISKY_INDUSTRIES:
                if ri in industry:
                    score += 25
                    reasons.append(f"公司行业存在风险: {ri}")
                    break

            # 6. 小微 + 无信息 = 可疑
            if ("0-20" in size or "少于" in size) and not industry:
                score += 15
                reasons.append("小微企业且无行业信息")

            # 7. 大公司 = 加分（降低风险分）
            if "10000" in size or "1000" in size:
                score = max(0, score - 10)

            # 8. 岗位描述含明显坑
            for phrase in KPI_PHRASES:
                if phrase in desc:
                    score += 20
                    reasons.append(f"岗位描述含风险表述: 「{phrase}」")
                    break

            # 9. 薪资异常
            if salary_max > 0 and salary_max > salary_min * 5:
                score += 20
                reasons.append(f"薪资范围异常过大 ({salary_min:.0f}-{salary_max:.0f})")
            elif salary_max > 0 and salary_max > salary_min * 3:
                score += 10
                reasons.append(f"薪资范围偏大 ({salary_min:.0f}-{salary_max:.0f})")
            if salary_min > 80000:
                score += 8
                reasons.append("高薪资请自行核实")

        score = max(0, min(100, score))
        result.score = score

        if score >= 60:
            result.level = RiskLevel.HIGH
        elif score >= 35:
            result.level = RiskLevel.MEDIUM
        elif score >= 15:
            result.level = RiskLevel.LOW
        else:
            result.level = RiskLevel.SAFE

        result.reasons = reasons
        result.details = {"company": name, "mode": "rule"}

        if reasons:
            logger.info(f"  🔍 风险 [{result.level.value}] {name}: {'; '.join(reasons)}")
        else:
            logger.debug(f"  🔍 风险 [{result.level.value}] {name}: 无明显风险")
        return result

    # ==================== API 模式 ====================

    def _check_via_api(self, name: str) -> RiskResult:
        provider = self.api_cfg.get("provider", "")
        token = self.api_cfg.get("token", "")

        if not token:
            logger.warning("API token 未配置，回退到规则模式")
            return self._check_via_rules(name)

        try:
            if provider == "tianyancha":
                url = f"https://open.tianyancha.com/open/company/{name}/risk"
                headers = {"Authorization": token}
                resp = self._session.get(url, headers=headers, timeout=10)
                return self._parse_api_response(resp.json())
            elif provider == "qichacha":
                url = f"https://api.qichacha.com/CompanyRisk/GetRiskInfo?key={token}&company={name}"
                resp = self._session.get(url, timeout=10)
                return self._parse_api_response(resp.json())
            else:
                logger.warning(f"不支持的 API 提供商: {provider}")
                return self._check_via_rules(name)
        except Exception as e:
            logger.error(f"API 风险检测失败: {e}")
            return self._check_via_rules(name)

    def _parse_api_response(self, data: dict) -> RiskResult:
        result = RiskResult()
        risk_score = data.get("riskScore", 0) or data.get("score", 0)
        if isinstance(risk_score, (int, float)):
            result.score = min(100, max(0, int(risk_score)))
            if result.score >= 70:
                result.level = RiskLevel.HIGH
            elif result.score >= 40:
                result.level = RiskLevel.MEDIUM
            elif result.score >= 15:
                result.level = RiskLevel.LOW
            else:
                result.level = RiskLevel.SAFE

        reasons = data.get("riskItems", []) or data.get("reasons", [])
        result.reasons = reasons if isinstance(reasons, list) else [str(reasons)]
        result.details = data
        return result
