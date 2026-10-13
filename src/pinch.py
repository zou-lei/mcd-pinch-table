"""
pinch.py — 麦麦拼桌核心逻辑：多人拼单 / 请客（对接真实麦当劳 MCP）

已按真实 API 校准（到店自取场景 orderType=1 / beType=1）：
    query-nearby-stores -> query-meals -> query-meal-detail
    -> calculate-price -> create-order

注意：麦当劳 MCP 的价格单位是「分」，本模块对外统一换算为「元」输出。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from mcd_client import McdMcpClient


@dataclass
class Member:
    """一位拼单成员。items 可填餐品名称或 productCode。"""

    name: str
    items: list[str] = field(default_factory=list)
    share: float = 1.0  # 1=正常分摊，0=被请客


@dataclass
class PinchResult:
    store: dict[str, Any]
    order_items: list[dict[str, Any]]  # [{productCode, productName, quantity, subtotal_yuan}]
    price_yuan: float  # 应付总额（元）
    discount_yuan: float  # 优惠金额（元）
    take_way_list: list[dict[str, Any]]
    split: dict[str, float]  # 成员 -> 应付金额（元）
    unmatched: list[tuple[str, str]]  # [(成员, 未匹配餐品)]
    order: Optional[dict[str, Any]] = None


class PinchTable:
    """到店自取（orderType=1 / beType=1）场景下的拼单助手。"""

    def __init__(self, client: McdMcpClient, order_type: int = 1, be_type: int = 1) -> None:
        self.client = client
        self.order_type = order_type
        self.be_type = be_type

    # ---------------------------------------------------------------- 门店
    def find_store(self, city: str, keyword: str) -> Optional[dict[str, Any]]:
        r = self.client.call_tool_json(
            "query-nearby-stores",
            {"beType": self.be_type, "searchType": 2, "city": city, "keyword": keyword},
        )
        stores = self._data_list(r)
        return stores[0] if stores else None

    # ---------------------------------------------------------------- 菜单
    def menu_codes(self, store_code: str) -> list[str]:
        r = self.client.call_tool_json(
            "query-meals",
            {"storeCode": store_code, "orderType": self.order_type, "beType": self.be_type},
        )
        data = r.get("data") if isinstance(r, dict) else None
        codes: list[str] = []
        seen: set[str] = set()
        for cat in (data or {}).get("categories", []) or []:
            for meal in cat.get("meals", []) or []:
                code = meal.get("code")
                if code and code not in seen:
                    seen.add(code)
                    codes.append(str(code))
        return codes

    def detail(self, store_code: str, code: str) -> dict[str, Any]:
        r = self.client.call_tool_json(
            "query-meal-detail",
            {"storeCode": store_code, "orderType": self.order_type, "beType": self.be_type, "code": code},
        )
        return (r or {}).get("data") or {}

    def resolve_menu(self, store_code: str, max_items: int = 60) -> dict[str, str]:
        """把「只有 code」的菜单补全为 code -> 名称 的索引。"""
        index: dict[str, str] = {}
        for code in self.menu_codes(store_code)[:max_items]:
            name = self.detail(store_code, code).get("name")
            if name:
                index[code] = str(name)
        return index

    # ---------------------------------------------------------------- 算价
    def calculate(self, store_code: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        r = self.client.call_tool_json(
            "calculate-price",
            {
                "storeCode": store_code,
                "orderType": self.order_type,
                "beType": self.be_type,
                "items": items,
                "needTableware": False,
            },
        )
        return (r or {}).get("data") or {}

    # ---------------------------------------------------------------- 下单
    def create_order(
        self,
        store_code: str,
        items: list[dict[str, Any]],
        take_way_code: str,
        remark: str = "",
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "storeCode": store_code,
            "orderType": self.order_type,
            "beType": self.be_type,
            "items": items,
            "takeWayCode": take_way_code,
        }
        if remark:
            args["remark"] = remark
        r = self.client.call_tool_json("create-order", args)
        return (r or {}).get("data") or {}

    # ---------------------------------------------------------------- 主流程
    def run(
        self,
        city: str,
        keyword: str,
        members: list[Member],
        dry_run: bool = True,
        take_way_code: str = "take-in-store",
        remark: str = "",
        max_menu: int = 60,
    ) -> PinchResult:
        store = self.find_store(city, keyword)
        if not store:
            raise RuntimeError(f"未找到门店：{city} {keyword}")
        store_code = str(store.get("storeCode"))

        code2name = self.resolve_menu(store_code, max_items=max_menu)
        name2code = {name: code for code, name in code2name.items()}

        # 汇总需求：成员 -> 该成员点选的 productCode 列表
        quantity: dict[str, int] = {}
        member_codes: dict[str, list[str]] = {m.name: [] for m in members}
        unmatched: list[tuple[str, str]] = []
        for member in members:
            for want in member.items:
                code = want if want in code2name else name2code.get(want)
                if not code:  # 名称模糊匹配
                    for name, cd in name2code.items():
                        if want in name:
                            code = cd
                            break
                if not code:
                    unmatched.append((member.name, want))
                    continue
                quantity[code] = quantity.get(code, 0) + 1
                member_codes[member.name].append(code)

        items = [{"productCode": c, "quantity": q} for c, q in quantity.items()]
        price = self.calculate(store_code, items)
        product_list = price.get("productList", []) or []
        price_cents = int(price.get("price") or 0)
        discount_cents = int(price.get("discount") or 0)

        # 每位成员的商品小计（分）：按「单价 × 该成员点选数量」计算
        subtotal_by_code = {str(p.get("productCode")): int(p.get("subtotal") or 0) for p in product_list}
        qty_by_code = {str(p.get("productCode")): int(p.get("quantity") or 1) for p in product_list}
        unit_by_code = {
            c: (subtotal_by_code[c] // q if q else subtotal_by_code[c])
            for c, q in qty_by_code.items()
        }
        member_subtotal = {
            m.name: sum(unit_by_code.get(c, 0) for c in member_codes[m.name]) for m in members
        }
        split = self._split_bill(members, member_subtotal, price_cents)

        order = None
        if not dry_run:
            order = self.create_order(store_code, items, take_way_code, remark)

        return PinchResult(
            store=store,
            order_items=[
                {
                    "productCode": str(p.get("productCode")),
                    "productName": p.get("productName"),
                    "quantity": p.get("quantity"),
                    "subtotal_yuan": round(int(p.get("subtotal") or 0) / 100, 2),
                }
                for p in product_list
            ],
            price_yuan=round(price_cents / 100, 2),
            discount_yuan=round(discount_cents / 100, 2),
            take_way_list=price.get("takeWayList", []) or [],
            split=split,
            unmatched=unmatched,
            order=order,
        )

    # ---------------------------------------------------------------- 工具
    @staticmethod
    def _split_bill(
        members: list[Member],
        member_subtotal: dict[str, int],
        price_cents: int,
    ) -> dict[str, float]:
        """按各人商品小计比例分摊「优惠后应付总额」。

        被请客者（share<=0）付 0，其消费由请客者按比例共同承担。
        """
        payer_base = sum(member_subtotal.get(m.name, 0) for m in members if m.share > 0)
        split: dict[str, float] = {}
        for member in members:
            if member.share <= 0 or payer_base <= 0:
                split[member.name] = 0.0
            else:
                split[member.name] = round(
                    price_cents * member_subtotal.get(member.name, 0) / payer_base / 100, 2
                )
        # 尾差挂到第一个非零分摊者
        diff = round(price_cents / 100 - sum(split.values()), 2)
        if abs(diff) >= 0.01:
            for member in members:
                if split.get(member.name, 0.0) > 0:
                    split[member.name] = round(split[member.name] + diff, 2)
                    break
        return split

    @staticmethod
    def _data_list(r: Any) -> list[dict[str, Any]]:
        if isinstance(r, list):
            return r
        if isinstance(r, dict):
            data = r.get("data")
            if isinstance(data, list):
                return data
        return []
