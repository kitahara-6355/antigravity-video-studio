"""
mcp_server.py — MCP プロトコル対応サーバー（U-12）

Antigravity の状態を外部AIツール（Claude Desktop等）から
照会可能にするMCPサーバー。

提供ツール:
  - get_pipeline_status: パイプラインの現在の状態
  - get_quality_score:   最新の品質スコア
  - get_evolution_log:   演出哲学と成長記録

提供リソース:
  - evolution_log:  evolution_log.json の内容
  - constitution:   constitution.json の内容

起動方法:
  python mcp_server.py

設計思想:
  MCPプロトコル（Model Context Protocol）は、外部AIアプリケーションが
  ローカルツールやデータにアクセスするための標準プロトコル。
  本モジュールは FastAPI バックエンドとは独立したスタンドアロンサーバーとして
  動作し、stdio/SSE 経由で外部ツールと通信する。

  依存: mcp パッケージ未インストール時はスタブモードで動作
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

BRANDING_DIR = Path(__file__).parent / "branding"
EVOLUTION_LOG_PATH = BRANDING_DIR / "evolution_log.json"
CONSTITUTION_PATH = BRANDING_DIR / "constitution.json"


# ============================================================
# データアクセス層
# ============================================================

def _load_json_safely(file_path: Path) -> Dict[str, Any]:
    """JSONファイルを安全にロード"""
    try:
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                logger.warning(f"Loaded JSON from {file_path.name} is not a dictionary")
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load {file_path.name} due to {type(e).__name__}: {e}", exc_info=True)
    return {}


def _format_pipeline_status(state_data: Dict[str, Any]) -> Dict[str, Any]:
    """パイプライン状態データをフォーマット"""
    if not state_data:
        return {
            "status": "idle",
            "message": "パイプラインは待機中です",
            "last_run": None,
        }

    return {
        "status": state_data.get("status", "unknown"),
        "current_stage": state_data.get("current_stage"),
        "progress": state_data.get("progress", 0),
        "video_file": state_data.get("video_file"),
        "started_at": state_data.get("started_at"),
        "stages_completed": state_data.get("stages_completed", 0),
    }


def get_pipeline_status() -> Dict[str, Any]:
    """パイプラインの現在のステータスを取得"""
    pipeline_state_path = Path(__file__).parent / "pipeline_state.json"
    state_data = _load_json_safely(pipeline_state_path)
    return _format_pipeline_status(state_data)


def _calculate_quality_score(review_data: Dict[str, Any]) -> Dict[str, Any]:
    """レビューログデータから品質スコアを算出"""
    if not isinstance(review_data, dict):
        return {"score": None, "message": "無効なデータ形式"}
    stages = review_data.get("stages") or []
    if not isinstance(stages, list):
        stages = []
    completed_stages_count = sum(1 for s in stages if isinstance(s, dict) and s.get("completed"))
    return {
        "score": round(completed_stages_count / max(len(stages), 1) * 100),
        "stages_total": len(stages),
        "stages_completed": completed_stages_count,
        "approved_at": review_data.get("approved_at"),
    }


def get_quality_score() -> Dict[str, Any]:
    """最新の品質スコアを取得"""
    logs_dir = Path(__file__).parent / "logs"
    review_log_path = logs_dir / "review_approvals.jsonl"

    if not review_log_path.exists():
        return {
            "score": None,
            "message": "品質スコアはまだ記録されていません",
        }

    try:
        with open(review_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if lines:
            last_log_entry = json.loads(lines[-1])
            return _calculate_quality_score(last_log_entry)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"品質スコア取得失敗 ({type(e).__name__}): {e}", exc_info=True)

    return {"score": None, "message": "解析エラー"}


def _summarize_evolution_log(evo_data: Dict[str, Any]) -> Dict[str, Any]:
    """演出哲学と成長記録データのサマリーを作成"""
    if not isinstance(evo_data, dict):
        return {
            "philosophy": "未確立",
            "total_entries": 0,
            "total_philosophies": 0,
            "latest_entries": [],
            "last_updated": None,
        }
    entries = evo_data.get("entries") or []
    philosophies = evo_data.get("philosophies") or []
    if not isinstance(entries, list):
        entries = []
    if not isinstance(philosophies, list):
        philosophies = []

    return {
        "philosophy": philosophies[-1] if philosophies else "未確立",
        "total_entries": len(entries),
        "total_philosophies": len(philosophies),
        "latest_entries": entries[-5:] if entries else [],
        "last_updated": evo_data.get("last_updated"),
    }


def get_evolution_log() -> Dict[str, Any]:
    """演出哲学と成長記録を取得"""
    evo_data = _load_json_safely(EVOLUTION_LOG_PATH)
    return _summarize_evolution_log(evo_data)


# ============================================================
# MCP ツール定義
# ============================================================

MCP_TOOLS = {
    "get_pipeline_status": {
        "description": "Antigravityパイプラインの現在の状態を取得します。ステージ進捗、処理中の動画、完了状況を返します。",
        "handler": get_pipeline_status,
        "parameters": {},
    },
    "get_quality_score": {
        "description": "最新の品質スコアを取得します。段階的レビューの完了状況と承認日時を返します。",
        "handler": get_quality_score,
        "parameters": {},
    },
    "get_evolution_log": {
        "description": "演出哲学と成長記録（Soul Passport）を取得します。最新の哲学、エントリー数、直近の学びを返します。",
        "handler": get_evolution_log,
        "parameters": {},
    },
}

MCP_RESOURCES = {
    "evolution_log": {
        "description": "演出哲学・成長記録の全データ",
        "uri": str(EVOLUTION_LOG_PATH),
        "mime_type": "application/json",
        "loader": lambda: _load_json_safely(EVOLUTION_LOG_PATH),
    },
    "constitution": {
        "description": "ブランド憲法（ブランド個性・コンテンツポリシー・デザイントークン）",
        "uri": str(CONSTITUTION_PATH),
        "mime_type": "application/json",
        "loader": lambda: _load_json_safely(CONSTITUTION_PATH),
    },
}


# ============================================================
# MCP Server 実装
# ============================================================

class AntigravityMCPServer:
    """
    Antigravity MCP Server

    MCPプロトコルでツールとリソースを公開する。
    mcp パッケージが利用可能な場合はネイティブモード、
    未インストール時はHTTPスタブモードで動作。
    """

    def __init__(self):
        self.tools = MCP_TOOLS
        self.resources = MCP_RESOURCES
        self._mcp_available = False

        try:
            from mcp.server import Server
            self._mcp_available = True
            logger.info("MCP SDK detected — native mode")
        except ImportError:
            logger.info("MCP SDK not installed — stub mode (HTTP API only)")

    def list_tools(self) -> list:
        """利用可能なツール一覧"""
        return [
            {
                "name": tool_name,
                "description": tool_info["description"],
                "parameters": tool_info.get("parameters", {}),
            }
            for tool_name, tool_info in self.tools.items()
        ]

    def call_tool(self, tool_name: str, arguments: Dict = None) -> Dict[str, Any]:
        """ツールを実行"""
        if tool_name not in self.tools:
            return {"error": f"Unknown tool: {tool_name}"}

        handler = self.tools[tool_name]["handler"]
        try:
            return handler(**(arguments or {}))
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.error(f"Failed to call tool {tool_name} with arguments {arguments}: {e}")
            return {"error": f"Tool execution failed: {type(e).__name__} - {e}"}

    def list_resources(self) -> list:
        """利用可能なリソース一覧"""
        return [
            {
                "name": resource_name,
                "description": resource_info["description"],
                "uri": resource_info["uri"],
                "mime_type": resource_info["mime_type"],
            }
            for resource_name, resource_info in self.resources.items()
        ]

    def read_resource(self, resource_name: str) -> Dict[str, Any]:
        """リソースを読み込み"""
        if resource_name not in self.resources:
            return {"error": f"Unknown resource: {resource_name}"}

        loader = self.resources[resource_name]["loader"]
        try:
            return loader()
        except (TypeError, ValueError, KeyError, AttributeError, OSError) as e:
            logger.error(f"Failed to read resource {resource_name}: {e}")
            return {"error": f"Resource read failed: {type(e).__name__} - {e}"}

    def get_server_info(self) -> Dict[str, Any]:
        """サーバー情報"""
        return {
            "name": "antigravity-mcp",
            "version": "1.0.0",
            "description": "Antigravity Video Studio MCP Server",
            "tools": len(self.tools),
            "resources": len(self.resources),
            "mcp_native": self._mcp_available,
        }


# シングルトン
mcp_server = AntigravityMCPServer()


# ============================================================
# FastAPI ルーター（HTTP スタブモード）
# ============================================================

def create_mcp_router():
    """MCP機能をHTTP APIとして公開するルーターを生成"""
    from fastapi import APIRouter, HTTPException

    mcp_router = APIRouter(prefix="/mcp", tags=["mcp"])

    @mcp_router.get("/info")
    async def mcp_info():
        return mcp_server.get_server_info()

    @mcp_router.get("/tools")
    async def mcp_list_tools():
        return {"tools": mcp_server.list_tools()}

    @mcp_router.post("/tools/{tool_name}")
    async def mcp_call_tool(tool_name: str, arguments: Dict[str, Any] = None):
        if tool_name not in mcp_server.tools:
            raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
        res = mcp_server.call_tool(tool_name, arguments or {})
        if isinstance(res, dict) and "error" in res:
            raise HTTPException(status_code=400, detail=res["error"])
        return res

    @mcp_router.get("/resources")
    async def mcp_list_resources():
        return {"resources": mcp_server.list_resources()}

    @mcp_router.get("/resources/{resource_name}")
    async def mcp_read_resource(resource_name: str):
        if resource_name not in mcp_server.resources:
            raise HTTPException(status_code=404, detail=f"Resource not found: {resource_name}")
        res = mcp_server.read_resource(resource_name)
        if isinstance(res, dict) and "error" in res:
            raise HTTPException(status_code=400, detail=res["error"])
        return res

    return mcp_router


# ============================================================
# スタンドアロン起動
# ============================================================

def main():
    print("=" * 50)
    print("Antigravity MCP Server")
    print("=" * 50)

    server = AntigravityMCPServer()
    info = server.get_server_info()
    print(f"Version: {info['version']}")
    print(f"Tools:   {info['tools']}")
    print(f"Resources: {info['resources']}")
    print(f"MCP Native: {info['mcp_native']}")
    print()

    # テスト実行
    print("--- Tool Test ---")
    for tool_item in server.list_tools():
        tool_name = tool_item["name"]
        result = server.call_tool(tool_name)
        print(f"  {tool_name}: {json.dumps(result, ensure_ascii=False, indent=2)[:200]}")
    print()
    print("--- Resource Test ---")
    for resource_item in server.list_resources():
        resource_name = resource_item["name"]
        data = server.read_resource(resource_name)
        print(f"  {resource_name}: {len(json.dumps(data))} bytes")


if __name__ == "__main__":  # pragma: no cover
    main()
