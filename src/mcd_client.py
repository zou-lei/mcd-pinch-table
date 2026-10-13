"""
mcd_client.py — 麦当劳中国 MCP (Streamable HTTP) 极简客户端

零第三方依赖，仅使用 Python 标准库。
支持 JSON 与 SSE(text/event-stream) 两种响应解析，自动维护 Mcp-Session-Id。

用法：
    export MCD_MCP_TOKEN="你的 Token"      # Windows: set MCD_MCP_TOKEN=...
    from mcd_client import McdMcpClient
    c = McdMcpClient()
    c.initialize()
    print(c.list_tools())
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

DEFAULT_URL = "https://mcp.mcd.cn/mcp-servers/mcd-mcp"
PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    """MCP 调用相关错误。"""


class McdMcpClient:
    def __init__(
        self,
        token: Optional[str] = None,
        url: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.token = token or os.environ.get("MCD_MCP_TOKEN", "").strip()
        self.url = url or os.environ.get("MCD_MCP_URL", DEFAULT_URL)
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._id = 0

    # ------------------------------------------------------------------ 内部
    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:  # 4xx/5xx
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise McpError(f"HTTP {exc.code} 调用 MCP 失败：{detail}") from exc
        except urllib.error.URLError as exc:
            raise McpError(f"网络错误：{exc.reason}") from exc
        return self._parse(body)

    @staticmethod
    def _parse(body: str) -> Optional[dict[str, Any]]:
        """兼容 JSON 与 SSE 两种返回格式。"""
        text = (body or "").strip()
        if not text:
            return None
        if text.startswith("data:") or "data:" in text[:16] or text.startswith("event:"):
            result = None
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        result = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
            return result
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------ 公开
    def initialize(self) -> Optional[dict[str, Any]]:
        res = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "mcd-pinch-table", "version": "0.1.0"},
                },
            }
        )
        # 发送 initialized 通知（无需响应，失败可忽略）
        try:
            self._post(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            )
        except McpError:
            pass
        return res

    def list_tools(self) -> list[dict[str, Any]]:
        res = self._post(
            {"jsonrpc": "2.0", "id": self._next_id(), "method": "tools/list", "params": {}}
        )
        if not res:
            return []
        return res.get("result", {}).get("tools", []) or []

    def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> Any:
        res = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        if res and res.get("error"):
            raise McpError(f"工具 {name} 调用失败：{res['error']}")
        result = res.get("result") if res else None
        # 麦当劳 MCP 的业务错误不在 JSON-RPC 的 error 字段，而在业务体里：
        #   {"success": false, "code": 60006, "message": "商品已售罄...", "traceId": "..."}
        # 若不拦截，调用方会拿到空 data 并静默算出 ¥0，因此这里统一抛错。
        payload = self.extract_json(result)
        if isinstance(payload, dict) and payload.get("success") is False:
            raise McpError(
                f"{name} 业务失败（code={payload.get('code')}）：{payload.get('message')}"
            )
        return result

    @staticmethod
    def extract_json(result: Any) -> Any:
        """把 tools/call 的 result 中 content[].text 尽力解析为 JSON/文本。"""
        if not result:
            return None
        contents = result.get("content") if isinstance(result, dict) else None
        if not contents:
            return result
        parts: list[str] = []
        for item in contents:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        joined = "\n".join(parts).strip()
        if not joined:
            return result
        try:
            return json.loads(joined)
        except json.JSONDecodeError:
            pass
        # 麦当劳 MCP 常在 JSON 前附带一段给 LLM 的说明文字（markdown），
        # 说明里可能出现 `data[]` 之类的空方括号，因此优先解析 JSON 对象。
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(joined):
            if ch == "{":
                try:
                    obj, _ = decoder.raw_decode(joined[idx:])
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    continue
        for idx, ch in enumerate(joined):
            if ch == "[":
                try:
                    obj, _ = decoder.raw_decode(joined[idx:])
                    if isinstance(obj, list) and obj:  # 跳过空的 []
                        return obj
                except json.JSONDecodeError:
                    continue
        return joined

    def call_tool_json(self, name: str, arguments: Optional[dict[str, Any]] = None) -> Any:
        return self.extract_json(self.call_tool(name, arguments))


if __name__ == "__main__":  # 快速自检
    client = McdMcpClient()
    if not client.token:
        raise SystemExit("请先设置环境变量 MCD_MCP_TOKEN")
    client.initialize()
    tools = client.list_tools()
    print(f"已连接麦当劳 MCP，共 {len(tools)} 个工具：")
    for tool in tools:
        print(" -", tool.get("name"), ":", (tool.get("description") or "")[:60])
