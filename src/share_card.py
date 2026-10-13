"""
share_card.py — 麦麦拼桌「分享卡片」功能

把一次拼单的结果渲染成一张**可直接截图/转发**的 HTML 卡片，
用于微信群/朋友圈社交裂变——这正是本赛事「拼 Star」的关键动作。

用法：
    from pinch import PinchTable, Member
    from share_card import render_card
    result = PinchTable(client).run(city="上海", keyword="南京西路", members=[...])
    open("card.html", "w", encoding="utf-8").write(render_card(result))
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Optional

from pinch import PinchResult


def render_card(result: PinchResult, slogan: str = "办公室一键拼麦，AI 算好每一分钱") -> str:
    store = result.store or {}
    store_name = escape(str(store.get("storeName") or "麦当劳门店"))
    distance = store.get("distance")

    items_html = "\n".join(
        f'<li><span class="q">×{it["quantity"]}</span>'
        f'<span class="n">{escape(str(it["productName"]))}</span>'
        f'<span class="p">¥{it["subtotal_yuan"]:.2f}</span></li>'
        for it in result.order_items
    )

    payers_html = "\n".join(
        f'<div class="payer{" free-row" if amount == 0 else ""}">'
        f'<span class="pn">{escape(name)}</span>'
        + ('<span class="tag">被请客</span>' if amount == 0 else "")
        + f'<span class="pa">¥{amount:.2f}</span></div>'
        for name, amount in result.split.items()
    )

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>麦麦拼桌 · 拼单卡片</title>
<style>
  :root {{ --red:#DA291C; --yellow:#FFC72C; --ink:#2b2b2b; --dim:#8a8a8a; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:#f2f2f2; padding:28px 16px;
          font-family:-apple-system,"PingFang SC","Microsoft YaHei",Segoe UI,sans-serif;
          display:flex; justify-content:center; }}
  .card {{ width:390px; background:#fff; border-radius:22px; overflow:hidden;
           box-shadow:0 14px 40px rgba(0,0,0,.16); }}
  .head {{ background:linear-gradient(135deg,var(--red),#ff5a3c); color:#fff;
           padding:22px 22px 18px; }}
  .head .brand {{ font-size:13px; letter-spacing:2px; opacity:.9; }}
  .head h1 {{ font-size:21px; margin-top:6px; display:flex; align-items:center; gap:8px; }}
  .head .logo {{ flex:none; }}
  .head .slogan {{ font-size:12px; opacity:.9; margin-top:8px; }}
  .sec {{ padding:18px 22px; border-bottom:1px dashed #ececec; }}
  .sec h2 {{ font-size:12px; color:var(--dim); font-weight:600; letter-spacing:1px; margin-bottom:10px; }}
  .store {{ font-size:15px; font-weight:700; color:var(--ink); }}
  .store .dist {{ font-size:12px; color:var(--dim); font-weight:400; margin-left:6px; }}
  ul {{ list-style:none; }}
  li {{ display:flex; align-items:center; gap:10px; padding:7px 0; font-size:14px; color:var(--ink); }}
  li .q {{ color:var(--red); font-weight:700; min-width:26px; }}
  li .n {{ flex:1; }}
  li .p {{ color:var(--ink); font-variant-numeric:tabular-nums; }}
  .total {{ display:flex; align-items:baseline; justify-content:space-between; padding:16px 22px;
            background:linear-gradient(135deg,#fff8e1,#fff); }}
  .total .k {{ font-size:13px; color:var(--dim); }}
  .total .v {{ font-size:28px; font-weight:800; color:var(--red); font-variant-numeric:tabular-nums; }}
  .total .v small {{ font-size:14px; }}
  .payer {{ display:flex; align-items:center; padding:9px 0; font-size:14px; color:var(--ink);
            border-bottom:1px solid #f6f6f6; }}
  .payer:last-child {{ border-bottom:none; }}
  .payer .pn {{ flex:1; }}
  .payer .tag {{ font-size:11px; color:#b8860b; background:#fff3cd; border-radius:20px;
                 padding:1px 8px; margin-right:8px; }}
  .payer .pa {{ font-weight:700; font-variant-numeric:tabular-nums; }}
  .payer.free-row .pa {{ color:var(--dim); }}
  .foot {{ padding:14px 22px 20px; text-align:center; }}
  .foot .stamp {{ font-size:11px; color:#bbb; }}
  .foot .proj {{ font-size:12px; color:var(--dim); margin-top:6px; }}
  .foot .proj b {{ color:var(--red); }}
</style>
</head>
<body>
  <div class="card">
    <div class="head">
      <div class="brand">MCD PINCH TABLE</div>
      <h1><svg class="logo" width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3.2 10.2c0-3.4 3.9-6.2 8.8-6.2s8.8 2.8 8.8 6.2H3.2z" fill="#fff"/>
        <rect x="3.2" y="11" width="17.6" height="1.6" rx=".8" fill="#fff" opacity=".8"/>
        <rect x="3.2" y="13.2" width="17.6" height="2.6" rx="1.3" fill="#fff"/>
        <path d="M3.2 16.8h17.6c0 1.9-3.9 3.4-8.8 3.4s-8.8-1.5-8.8-3.4z" fill="#fff"/>
      </svg>麦麦拼桌 · 拼单卡片</h1>
      <div class="slogan">{escape(slogan)}</div>
    </div>

    <div class="sec">
      <h2>门店</h2>
      <div class="store">{store_name}
        <span class="dist">{'距您 ' + str(distance) + 'm' if distance else ''}</span>
      </div>
    </div>

    <div class="sec">
      <h2>餐品</h2>
      <ul>{items_html}</ul>
    </div>

    <div class="total">
      <span class="k">应付总额</span>
      <span class="v">¥{result.price_yuan:.2f}<small></small></span>
    </div>

    <div class="sec">
      <h2>每人分摊</h2>
      {payers_html}
    </div>

    <div class="foot">
      <div class="stamp">生成于 {stamp}</div>
      <div class="proj">本项目为「麦当劳程序员创意开发大赛」参赛作品 · <b>mcd-pinch-table</b></div>
    </div>
  </div>
</body>
</html>"""
