#!/usr/bin/env python3
"""
cli.py — 麦麦拼桌 命令行入口

子命令：
    tools                                 列出麦当劳 MCP 全部可用工具
    stores <关键词> --city 城市           查询附近门店
    pinch  <关键词> --city 城市 --people  多人拼单（默认 dry-run，只算价不下单）
    share  <关键词> --city 城市 --people  生成拼单分享卡片（HTML）
    coupons                               自动领券 + 查看卡包
    report                                生成麦麦自动日报
"""

from __future__ import annotations

import argparse
import json
import sys

from autopilot import AutoPilot
from mcd_client import McdMcpClient, McpError
from pinch import Member, PinchTable
from share_card import render_card


def _client() -> McdMcpClient:
    client = McdMcpClient()
    if not client.token:
        print("❌ 未检测到 MCD_MCP_TOKEN 环境变量。", file=sys.stderr)
        print("   请先设置：export MCD_MCP_TOKEN='你的 Token'（Windows: set MCD_MCP_TOKEN=...）", file=sys.stderr)
        raise SystemExit(2)
    client.initialize()
    return client


def _pp(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _parse_members(people: str) -> list[Member]:
    """解析 --people：'小明:巨无霸+可乐,小红:麦辣鸡腿堡*,小刚:板烧鸡腿堡'（末尾 * 表示被请客）。"""
    members: list[Member] = []
    for spec in people.split(","):
        if ":" not in spec:
            members.append(Member(name=spec.strip()))
            continue
        name, _, rest = spec.partition(":")
        share = 1.0
        if rest.endswith("*"):
            share = 0.0
            rest = rest[:-1]
        items = [x for x in rest.replace("，", "+").split("+") if x]
        members.append(Member(name=name.strip(), items=items, share=share))
    return members


def cmd_tools(_: argparse.Namespace) -> int:
    client = _client()
    tools = client.list_tools()
    print(f"麦当劳 MCP 共 {len(tools)} 个工具：\n")
    for tool in tools:
        print(f"- {tool.get('name')}")
        desc = (tool.get("description") or "").strip().replace("\n", " ")
        if desc:
            print(f"    {desc[:80]}")
    return 0


def cmd_stores(args: argparse.Namespace) -> int:
    client = _client()
    data = client.call_tool_json(
        "query-nearby-stores",
        {"beType": 1, "searchType": 2, "city": args.city, "keyword": args.keyword},
    )
    stores = data.get("data") if isinstance(data, dict) else data
    if not isinstance(stores, list) or not stores:
        print("未找到门店，请更换关键词或城市。")
        return 0
    print(f"共找到 {len(stores)} 家门店：")
    for s in stores:
        print(f"  - {s.get('storeName')}  [storeCode={s.get('storeCode')}, 距离 {s.get('distance')}m]")
    return 0


def cmd_pinch(args: argparse.Namespace) -> int:
    client = _client()
    members = _parse_members(args.people)
    table = PinchTable(client)
    print(f"正在解析门店「{args.city} {args.keyword}」与菜单（首次会逐个拉取餐品名称，请稍候）…")
    try:
        result = table.run(
            city=args.city,
            keyword=args.keyword,
            members=members,
            dry_run=not args.confirm,
            take_way_code=args.take_way,
            remark=args.remark or "",
        )
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    print("\n=== 拼单结果 ===")
    print(f"门店：{result.store.get('storeName')}  [storeCode={result.store.get('storeCode')}]")
    print("\n[餐品]")
    for it in result.order_items:
        print(f"  {it['quantity']} × {it['productName']}  ¥{it['subtotal_yuan']}")
    print(f"\n应付总额：¥{result.price_yuan}   优惠：¥{result.discount_yuan}")

    print("\n[分摊]")
    for name, amount in result.split.items():
        tag = "（被请客）" if amount == 0 else ""
        print(f"  {name}：¥{amount}{tag}")

    if result.unmatched:
        print("\n[未匹配餐品]（可换用菜单中的准确名称或 productCode）")
        for who, want in result.unmatched:
            print(f"  {who} 的「{want}」")

    if result.order:
        print("\n[订单]")
        _pp(result.order)
        print("\n⚠️ 请通过订单返回的支付链接完成付款。")
    else:
        ways = "/".join(t.get("code", "") for t in result.take_way_list) or "take-in-store"
        print(f"\n（dry-run 模式：未真实下单。加 --confirm 才会创建订单；用餐方式用 --take-way 选择，可选：{ways}）")
    return 0


def cmd_share(args: argparse.Namespace) -> int:
    client = _client()
    members = _parse_members(args.people)
    table = PinchTable(client)
    print("正在解析并生成分享卡片…")
    try:
        result = table.run(
            city=args.city, keyword=args.keyword, members=members, take_way_code=args.take_way
        )
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    html = render_card(result)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"✅ 已生成分享卡片：{args.out}")
    print(f"   门店：{result.store.get('storeName')} | 应付 ¥{result.price_yuan} | 分摊人数 {len(result.split)}")
    return 0


def cmd_coupons(_: argparse.Namespace) -> int:
    client = _client()
    pilot = AutoPilot(client)
    print("[一键领券]")
    _pp(pilot.claim_coupons())
    print("\n[我的卡包]")
    _pp(pilot.my_coupons())
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    client = _client()
    pilot = AutoPilot(client)
    print(pilot.daily_report(do_claim=not args.no_claim))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcd-pinch-table", description="麦麦拼桌 · 办公室一键拼麦（基于麦当劳中国 MCP）"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tools", help="列出 MCP 全部工具").set_defaults(func=cmd_tools)

    p_stores = sub.add_parser("stores", help="查询附近门店")
    p_stores.add_argument("keyword", help="门店关键词，如 南京西路")
    p_stores.add_argument("--city", required=True, help="城市名，如 上海")
    p_stores.set_defaults(func=cmd_stores)

    p_pinch = sub.add_parser("pinch", help="多人拼单（默认 dry-run）")
    p_pinch.add_argument("keyword", help="门店关键词，如 南京西路")
    p_pinch.add_argument("--city", required=True, help="城市名，如 上海")
    p_pinch.add_argument(
        "--people",
        required=True,
        help="格式：'小明:巨无霸+可乐,小红:麦辣鸡腿堡+薯条*,小刚:板烧鸡腿堡'（结尾*表示被请客）",
    )
    p_pinch.add_argument("--take-way", default="take-in-store", help="用餐方式：take-in-store外带 / eat-in堂食")
    p_pinch.add_argument("--remark", default="", help="订单备注")
    p_pinch.add_argument("--confirm", action="store_true", help="真实下单（默认仅算价）")
    p_pinch.set_defaults(func=cmd_pinch)

    p_share = sub.add_parser("share", help="生成拼单分享卡片（HTML）")
    p_share.add_argument("keyword", help="门店关键词，如 南京西路")
    p_share.add_argument("--city", required=True, help="城市名，如 上海")
    p_share.add_argument("--people", required=True, help="同 pinch 的 --people 格式")
    p_share.add_argument("--take-way", default="take-in-store", help="用餐方式：take-in-store / eat-in")
    p_share.add_argument("--out", default="pinch-card.html", help="输出 HTML 路径")
    p_share.set_defaults(func=cmd_share)

    sub.add_parser("coupons", help="自动领券+查看卡包").set_defaults(func=cmd_coupons)

    p_report = sub.add_parser("report", help="生成麦麦自动日报")
    p_report.add_argument("--no-claim", action="store_true", help="日报中不自动领券")
    p_report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except McpError as exc:
        print(f"❌ MCP 调用出错：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
