# MCP 接入说明 · MCP_INTEGRATION

本文说明「麦麦拼桌」实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

## 1. 使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | 麦当劳中国 MCP 服务（`mcd-mcp`） |
| 接入地址 | `https://mcp.mcd.cn/mcp-servers/mcd-mcp` |
| 传输协议 | Streamable HTTP |
| 鉴权方式 | 请求头 `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| Token 获取 | https://open.mcd.cn/mcp（手机号登录 → 控制台 → 激活） |
| 客户端实现 | `src/mcd_client.py`（零依赖，标准库实现 JSON-RPC 2.0 + SSE 解析） |

## 2. 使用的 MCP Tool

### 2.1 拼单主流程（`src/pinch.py`）

| 顺序 | Tool 名 | 用途 |
|---:|---|---|
| 1 | `query-nearby-stores` | 按关键词/地址查可点餐门店 |
| 2 | `query-meals` | 拉取门店在售餐品菜单 |
| 3 | `query-meal-detail` | 查套餐组成，校验可替换项 |
| 4 | `query-store-coupons` | 查该门店可用优惠券 |
| 5 | `calculate-price` | 算价：商品金额、配送费、优惠抵扣、应付总额 |
| 6 | `create-order` | 创建订单，返回订单详情与支付链接 |
| 7 | `query-order` | 查订单状态（可选） |

### 2.2 自动化管家（`src/autopilot.py`）

| Tool 名 | 用途 |
|---|---|
| `auto-bind-coupons` | 一键领取「麦麦省」全部可领优惠券 |
| `available-coupons` | 查当前可领取券列表 |
| `query-my-coupons` | 查我的卡包券 |
| `campaign-calendar` | 播报当月活动日历 |
| `query-my-account` | 查积分账户（可用 / 即将过期） |

### 2.3 通用

| Tool 名 | 用途 |
|---|---|
| `now-time-info` | 获取服务器时间，避免模型"凭记忆猜日期" |

## 3. 调用流程

```
用户/定时任务
     │
     ▼
cli.py  ──►  McdMcpClient（initialize → tools/call）
     │            │  POST https://mcp.mcd.cn/mcp-servers/mcd-mcp
     │            │  Header: Authorization: Bearer <token>
     │            ▼
     │      麦当劳 MCP Server
     │
     ├─ pinch 流程:  stores → meals → meal-detail → coupons → calculate-price → create-order
     └─ report 流程: auto-bind-coupons → campaign-calendar → query-my-account → query-my-coupons
```

**协议细节**：客户端先发送 `initialize`（protocolVersion `2025-06-18`），从响应头 `Mcp-Session-Id` 维护会话，随后发送 `notifications/initialized`，再通过 `tools/call` 调用业务工具。响应兼容 `application/json` 与 `text/event-stream` 两种格式。

## 4. 业务价值

1. **把"群聊拼单"的结构化成本降到接近零**：从"几十条消息 + 手工记账"变为"一条命令"。
2. **优惠不浪费**：算价阶段自动代入门店可用券，避免"忘了用券"。
3. **积分与券不过期**：自动化管家定时领券 + 临期提醒，把沉睡权益唤醒。
4. **真实闭环**：不是"问答式建议"，而是**真实下单并返回支付链接**的完整链路。

## 5. 安全与合规

- 代码中**不含任何真实 Token**，仅从环境变量 `MCD_MCP_TOKEN` 读取；示例配置使用占位符。
- 默认 **dry-run**：`pinch` 子命令不带 `--confirm` 时只算价、不下单，避免误操作。
- 严格遵守麦当劳 MCP 服务规则与调用频率限制（每 Token 每分钟 ≤ 600 次请求）。
