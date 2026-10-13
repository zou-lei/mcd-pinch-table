"""
autopilot.py — 麦麦自动化管家（无人值守）

适合挂定时任务（crontab / Windows 计划任务 / WorkBuddy 自动化）：
    - 自动领取「麦麦省」全部可用优惠券      auto-bind-coupons
    - 播报当月活动日历                      campaign-calendar
    - 盯积分账户与即将过期积分              query-my-account
    - 汇总我的卡包券                        query-my-coupons
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mcd_client import McdMcpClient, McpError


class AutoPilot:
    def __init__(self, client: McdMcpClient) -> None:
        self.client = client

    # 各步骤独立兜底：单个工具失败不影响整体日报
    def _safe(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        try:
            return self.client.call_tool_json(tool, args or {})
        except McpError as exc:
            return {"__error__": str(exc)}

    def claim_coupons(self) -> Any:
        """一键领取麦麦省全部可领优惠券。"""
        return self._safe("auto-bind-coupons")

    def available_coupons(self) -> Any:
        return self._safe("available-coupons")

    def my_coupons(self) -> Any:
        return self._safe("query-my-coupons", {"page": "1", "pageSize": "50"})

    def campaign_calendar(self) -> Any:
        return self._safe("campaign-calendar")

    def my_account(self) -> Any:
        return self._safe("query-my-account")

    def daily_report(self, do_claim: bool = True) -> str:
        """生成「麦麦每日日报」文本，用于飞书 / 邮件 / 终端推送。"""
        lines: list[str] = []
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines.append(f"🍟 麦麦自动日报 · {stamp}")

        if do_claim:
            claimed = self.claim_coupons()
            lines.append(self._fmt_claim(claimed))

        calendar = self.campaign_calendar()
        lines.append(self._fmt_calendar(calendar))

        account = self.my_account()
        lines.append(self._fmt_account(account))

        coupons = self.my_coupons()
        lines.append(self._fmt_coupon_count(coupons))

        return "\n".join(lines)

    # ------------------------------------------------------------- 格式化
    @staticmethod
    def _fmt_claim(data: Any) -> str:
        if isinstance(data, dict) and data.get("__error__"):
            return f"🎫 领券：失败（{data['__error__'][:60]}）"
        count = 0
        if isinstance(data, dict):
            count = data.get("count") or data.get("total") or len(data.get("coupons", []) or [])
        elif isinstance(data, list):
            count = len(data)
        return f"🎫 领券：本次领取 {count} 张"

    @staticmethod
    def _fmt_calendar(data: Any) -> str:
        if isinstance(data, dict) and data.get("__error__"):
            return f"📅 活动：获取失败（{data['__error__'][:60]}）"
        if isinstance(data, dict):
            actives = data.get("ongoing") or data.get("current") or data.get("activities") or []
            if isinstance(actives, list) and actives:
                names = [
                    str(a.get("name") or a.get("title") or a)[:20]
                    for a in actives[:3]
                    if isinstance(a, (dict, str))
                ]
                return "📅 活动：" + "、".join(names)
        return "📅 活动：本月暂无（或需查看完整日历）"

    @staticmethod
    def _fmt_account(data: Any) -> str:
        if isinstance(data, dict) and data.get("__error__"):
            return f"💎 积分：获取失败（{data['__error__'][:60]}）"
        if isinstance(data, dict):
            avail = data.get("availablePoints") or data.get("points") or data.get("balance")
            expiring = data.get("expiringPoints") or data.get("soonExpirePoints")
            parts = []
            if avail is not None:
                parts.append(f"可用 {avail}")
            if expiring is not None:
                parts.append(f"即将过期 {expiring}")
            if parts:
                return "💎 积分：" + "，".join(str(p) for p in parts)
        return "💎 积分：暂无法解析"

    @staticmethod
    def _fmt_coupon_count(data: Any) -> str:
        if isinstance(data, dict) and data.get("__error__"):
            return f"👝 卡包：获取失败（{data['__error__'][:60]}）"
        if isinstance(data, dict):
            total = data.get("total") or len(data.get("coupons", []) or [])
            return f"👝 卡包：共 {total} 张"
        if isinstance(data, list):
            return f"👝 卡包：共 {len(data)} 张"
        return "👝 卡包：暂无数据"
