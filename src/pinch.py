"""
pinch.py — 麦麦拼桌核心逻辑：多人拼单 / 请客（对接真实麦当劳 MCP）

已按真实 API 校准（到店自取场景 orderType=1 / beType=1）：
    query-nearby-stores -> query-meals -> calculate-price -> create-order

注意 1：query-meals 返回的 data.meals 已含全部餐品的名称与价格，无需逐个查详情。
注意 2：calculate-price 的 price 是【优惠前】原价合计，discount 是优惠额且未从 price 扣减，
        真实应付 = price - discount；而 productList[].subtotal 是【优惠后】小计。
注意 3：价格单位是「分」，本模块对外统一换算为「元」输出。
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
    def menu_index(self, store_code: str) -> dict[str, dict[str, Any]]:
        """一次调用取回门店**全部**餐品：code -> {name, currentPrice, originalPrice, ...}

        query-meals 的 data.meals 是一个 dict，已包含全部餐品名称与价格
        （实测门店 1450118 共 115 个），无需再逐个 query-meal-detail。
        """
        r = self.client.call_tool_json(
            "query-meals",
            {"storeCode": store_code, "orderType": self.order_type, "beType": self.be_type},
        )
        data = (r or {}).get("data") or {}
        meals = data.get("meals") or {}
        return {str(code): (info or {}) for code, info in meals.items()}

    def menu_codes(self, store_code: str) -> list[str]:
        return list(self.menu_index(store_code).keys())

    def resolve_menu(self, store_code: str) -> dict[str, str]:
        """code -> 名称 索引（全量，无截断）。"""
        return {
            code: str(info.get("name"))
            for code, info in self.menu_index(store_code).items()
            if info.get("name")
        }

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
    ) -> PinchResult:
        store = self.find_store(city, keyword)
        if not store:
            raise RuntimeError(f"未找到门店：{city} {keyword}")
        store_code = store.get("storeCode")
        if not store_code:
            raise RuntimeError(f"门店数据异常（缺少 storeCode）：{store}")
        store_code = str(store_code)

        code2name = self.resolve_menu(store_code)
        name2code = {name: code for code, name in code2name.items()}

        # 汇总需求：成员 -> 该成员点选的 productCode 列表
        quantity: dict[str, int] = {}
        member_codes: dict[str, list[str]] = {m.name: [] for m in members}
        unmatched: list[tuple[str, str]] = []
        for member in members:
            for want in member.items:
                code = want if want in code2name else name2code.get(want)
                if not code:  # 名称模糊匹配（取最长公共子串，避免命中「三件套」等长名称）
                    code = self._fuzzy_match(want, code2name)
                if not code:
                    unmatched.append((member.name, want))
                    continue
                quantity[code] = quantity.get(code, 0) + 1
                member_codes[member.name].append(code)

        items = [{"productCode": c, "quantity": q} for c, q in quantity.items()]
        price = self.calculate(store_code, items)
        product_list = price.get("productList", []) or []
        # price 是【优惠前】原价合计，discount 是优惠额且未从 price 中扣减，
        # 因此真实应付 = price - discount。（实测：买 N 个折扣商品时 price == discount）
        price_cents = int(price.get("price") or 0)
        discount_cents = int(price.get("discount") or 0)
        payable_cents = max(price_cents - discount_cents, 0)

        # 每位成员的商品小计（分）：productList[].subtotal 已是【优惠后】小计
        subtotal_by_code = {str(p.get("productCode")): int(p.get("subtotal") or 0) for p in product_list}
        qty_by_code = {str(p.get("productCode")): int(p.get("quantity") or 1) for p in product_list}
        unit_by_code = {
            c: (subtotal_by_code[c] // q if q else subtotal_by_code[c])
            for c, q in qty_by_code.items()
        }
        member_subtotal = {
            m.name: sum(unit_by_code.get(c, 0) for c in member_codes[m.name]) for m in members
        }
        split = self._split_bill(members, member_subtotal, payable_cents)

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
            price_yuan=round(payable_cents / 100, 2),
            discount_yuan=round(discount_cents / 100, 2),
            take_way_list=price.get("takeWayList", []) or [],
            split=split,
            unmatched=unmatched,
            order=order,
        )

    @staticmethod
    def _fuzzy_match(want: str, code2name: dict[str, str]) -> Optional[str]:
        """模糊匹配餐品名，避免「鸡腿堡」误命中「龙焰鸡腿堡三件套」。

        打分规则（分数越高越优，0 表示不匹配）：
          1. 完全相等        -> 1000
          2. 用户输入是餐品名子串 -> 900 + 长度接近度（越接近越长）
          3. 否则按最长公共子串占比 -> 最高 500
        只有分数 >= 800（即「输入是餐品名子串」及以上）才认为可信，
        避免「鸡」这类泛化输入随便命中一个商品。
        """
        if not want:
            return None
        best_code: Optional[str] = None
        best_score = 0.0
        for code, name in code2name.items():
            if want == name:
                score = 1000.0
            elif want in name:
                # 用户输入是餐品名的一部分：越接近完整名称越优；
                # 同分时取名称更短者（更可能是单点商品而非「三件套」）
                score = 900.0 + len(want) * 100.0 / len(name)
            else:
                common = PinchTable._lcs_len(want, name)
                score = (common * 500.0 / len(name)) if common >= 2 else 0.0
            if score > best_score or (
                score == best_score
                and best_code is not None
                and len(name) < len(code2name[best_code])
            ):
                best_score = score
                best_code = code
        return best_code if best_score >= 800.0 else None

    @staticmethod
    def _lcs_len(a: str, b: str) -> int:
        """最长公共子串长度（滚动数组，O(min(len))空间）。"""
        if not a or not b:
            return 0
        prev = [0] * (len(b) + 1)
        best = 0
        for i in range(1, len(a) + 1):
            cur = [0] * (len(b) + 1)
            for j in range(1, len(b) + 1):
                if a[i - 1] == b[j - 1]:
                    cur[j] = prev[j - 1] + 1
                    best = max(best, cur[j])
            prev = cur
        return best

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
