---
name: 麦麦拼桌
description: 基于麦当劳中国 MCP 的多人拼单助手。当用户说"拼单""帮我带麦当劳""办公室点麦当劳""算一下每人多少钱""帮我领券""麦当劳有什么活动"时使用本 Skill。
---

# 麦麦拼桌（mcd-pinch-table）

办公室/朋友拼单助手，基于麦当劳中国 MCP，实现「多人需求 → 最优组合 → 自动分摊 → 一键下单」，
并提供定时领券、活动播报、临期积分提醒的自动化管家能力。

## 前置条件

- 已配置麦当劳 MCP 连接器（见 `mcp-config.example.json`），环境变量 `MCD_MCP_TOKEN` 可用。

## 使用方式

命令行：
```bash
python3 src/cli.py tools                      # 列工具
python3 src/cli.py pinch "<门店关键词>" --people "小明:巨无霸+可乐,小红:麦辣鸡腿堡+薯条*"   # 拼单(默认dry-run)
python3 src/cli.py pinch "<门店关键词>" --people "..." --confirm                            # 真实下单
python3 src/cli.py report                     # 麦麦自动日报（含自动领券）
```

## 工具调用约定

- 涉及日期一律调用 `now-time-info`，不依赖模型记忆。
- 算价与下单串行执行；查询类结果在同一会话内复用，避免重复调用触碰限流。
- **下单前必须向用户复述门店、餐品、金额并取得确认**，默认 dry-run。
- 领券等写操作仅在 `report`/`coupons` 流程内进行，避免误触发。

## 典型触发词

拼单、拼麦、帮我带麦当劳、办公室点麦当劳、算分摊、领券、麦当劳活动、积分快过期。
