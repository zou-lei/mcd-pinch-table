# workbuddy.md · WorkBuddy 开发上下文

> 本文件记录「麦麦拼桌」在 **腾讯 WorkBuddy** 中完成构思、开发与调试的对话上下文，
> 用于核验是否符合大赛的 WorkBuddy 专项奖励条件。

## 使用 WorkBuddy 做了什么

1. **需求构思**：在 WorkBuddy 中描述"办公室拼单痛点"，由 WorkBuddy 梳理功能边界与用户故事。
2. **MCP 接入**：通过 WorkBuddy 的【自定义连接器 → 配置 MCP】接入麦当劳 MCP（`mcd-mcp`），
   并在对话中验证 `query-nearby-stores`、`query-meals`、`calculate-price` 等工具可正常返回。
3. **代码生成与调试**：让 WorkBuddy 生成 `mcd_client.py` 的 JSON-RPC / SSE 解析逻辑，
   并调试 `tools/list` 返回、`calculate-price` 参数格式。
4. **文档撰写**：由 WorkBuddy 协助产出 README、MCP_INTEGRATION 等文档。

## 关键对话摘要（示例）

- **用户**：我要做一个"办公室拼单"工具，基于麦当劳 MCP，帮一群同事拼单并自动算分摊。
- **WorkBuddy**：建议流程为 查门店 → 取菜单 → 组单 → 算价 → 下单，并给出 `calculate-price` 的入参结构（storeCode + orderType + products）。
- **用户**：算分摊时优惠券怎么处理？
- **WorkBuddy**：建议按各人商品金额比例分摊"优惠后应付总额"，并处理四舍五入尾差。
- **用户**：帮我验证 MCP 连接。
- **WorkBuddy**：调用 `tools/list`，确认麦当劳 MCP 共返回 35 个工具，连接成功。

## 配置方式（WorkBuddy 连接器）

在 WorkBuddy 左侧【专家·技能·连接器】→【连接器】→【自定义连接器】→【配置 MCP】中填入
`mcp-config.example.json` 的内容（将 `${MCD_MCP_TOKEN}` 替换为真实 Token），保存并【启用】即可。

## 声明

本文件由参赛者使用 WorkBuddy 开发过程中整理，内容真实反映上述开发流程。
