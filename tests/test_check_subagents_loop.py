# -*- coding: utf-8 -*-
import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

# backend/agents/orchestration/check_subagents_loop をインポート
from backend.agents.orchestration.check_subagents_loop import check_subagent_transcript, main

@pytest.fixture
def mock_brain_dir(tmp_path):
    """
    ダミーの .gemini/antigravity/brain ディレクトリ構造を作成するフィクスチャ。
    os.path.expanduser をモックして tmp_path にリダイレクトします。
    """
    app_data_path = os.path.join(str(tmp_path), ".gemini", "antigravity")
    with patch("os.path.expanduser", return_value=str(tmp_path)), \
         patch.dict(os.environ, {"ANTIGRAVITY_APP_DATA": app_data_path}):
        brain_dir = tmp_path / ".gemini" / "antigravity" / "brain"
        brain_dir.mkdir(parents=True, exist_ok=True)
        yield brain_dir

def test_check_subagent_transcript_not_found(mock_brain_dir):
    """
    トランスクリプトが存在しない場合は None を返すことを確認します。
    """
    res = check_subagent_transcript("dummy-conv-id")
    assert res is None

def test_check_subagent_transcript_pass(mock_brain_dir):
    """
    トランスクリプトに 'pass' が含まれる場合に、ステータスが 'pass' になることを確認します。
    """
    conv_id = "test-pass-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    
    transcript_file = conv_dir / "transcript.jsonl"
    
    steps = [
        {
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "content": "planner msg",
            "tool_calls": [
                {
                    "name": "send_message",
                    "args": {"Message": "結果: pass", "Recipient": "parent"}
                }
            ]
        }
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
            
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "pass"

def test_check_subagent_transcript_fail(mock_brain_dir):
    """
    トランスクリプトに 'fail' が含まれる場合に、ステータスが 'fail' になることを確認します。
    """
    conv_id = "test-fail-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    
    transcript_file = conv_dir / "transcript.jsonl"
    
    steps = [
        {
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "content": "planner msg",
            "tool_calls": [
                {
                    "name": "send_message",
                    "args": {"Message": "結果: fail", "Recipient": "parent"}
                }
            ]
        }
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
            
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "fail"

def test_check_subagent_transcript_with_send_message(mock_brain_dir):
    """
    send_message の引数 Message 内に 'pass' が含まれる場合にも、ステータスが 'pass' になることを確認します。
    """
    conv_id = "test-send-msg-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    
    transcript_file = conv_dir / "transcript.jsonl"
    
    steps = [
        {
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "content": "some explanation",
            "tool_calls": [
                {
                    "name": "send_message",
                    "args": {"Message": "Here is the result: pass", "Recipient": "parent"}
                }
            ]
        }
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
            
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "pass"

@patch("backend.agents.orchestration.check_subagents_loop.OrchestrationHub")
@patch("backend.agents.orchestration.check_subagents_loop.check_subagent_transcript")
@patch("builtins.open")
@patch("pathlib.Path.exists", return_value=True)
def test_main_loop_with_assigned_agent(mock_exists, mock_open, mock_check_transcript, mock_hub_class):
    """
    main() が task_queue.json の 'assigned_agent' から動的に会話IDを取得し、
    完了したタスクに対して mark_task_done を呼び出すことを確認します。
    """
    mock_hub = MagicMock()
    mock_hub_class.return_value = mock_hub
    
    # task_queue.json のダミー内容
    dummy_queue = {
        "current_batch_id": "test_batch_123",
        "tasks": [
            {
                "id": "T-test_batch_123-bug_hunter-000",
                "status": "running",
                "assigned_agent": "conv-uuid-1111"
            },
            {
                "id": "T-test_batch_123-bug_hunter-001",
                "status": "running",
                "assigned_agent": None  # アサインされていないタスク
            }
        ]
    }
    
    # 2回 open() が呼ばれるのを模倣（1回目：キュー読み込み、2回目：再読込して未完了確認）
    mock_file = MagicMock()
    mock_file.__enter__.return_value = mock_file
    mock_open.return_value = mock_file
    
    with patch("json.load", side_effect=[dummy_queue, dummy_queue]):
        # transcriptチェック結果の設定
        mock_check_transcript.side_effect = lambda conv_id: {
            "status": "pass",
            "report": {"message": "done"}
        } if conv_id == "conv-uuid-1111" else None
        
        main()
        
        # 期待される呼び出し:
        # conv-uuid-1111 のタスク T-test_batch_123-bug_hunter-000 に対してのみ mark_task_done が呼ばれていること
        mock_hub.mark_task_done.assert_called_once_with(
            "T-test_batch_123-bug_hunter-000", "pass", {"message": "done"}
        )

def test_check_subagent_transcript_unicode_decode_replace(mock_brain_dir):
    """
    無効な UTF-8 バイトが含まれている場合でも、errors='replace' により
    クラッシュせず処理され、正常な行が読み込めることを確認します。
    """
    conv_id = "test-unicode-err-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    
    transcript_file = conv_dir / "transcript.jsonl"
    
    # 1行目に無効な UTF-8 バイト (0x80) を混入させ、2行目に正常な結果を書く
    with open(transcript_file, "wb") as f:
        # 1行目: 壊れた UTF-8 バイト
        f.write(b"{\"source\": \"MODEL\", \"content\": \"" + b"\x80" + b"\"}\n")
        # 2行目: 正常な結果 pass
        step2 = {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "結果: pass", "tool_calls": []}
        f.write(json.dumps(step2).encode("utf-8") + b"\n")
        
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "pass"

def test_check_subagent_transcript_os_error(mock_brain_dir):
    """
    ファイル読み込み時に OSError が発生した場合に安全に None を返すことを確認します。
    """
    conv_id = "test-os-err-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    
    transcript_file = conv_dir / "transcript.jsonl"
    transcript_file.touch()
    
    # open() をモックして OSError を発生させる
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        res = check_subagent_transcript(conv_id)
        assert res is None

@patch("backend.agents.orchestration.check_subagents_loop.OrchestrationHub")
@patch("backend.agents.orchestration.check_subagents_loop.check_subagent_transcript")
@patch("builtins.open")
@patch("pathlib.Path.exists", return_value=True)
def test_main_loop_resilient_to_task_errors(mock_exists, mock_open, mock_check_transcript, mock_hub_class):
    """
    一部のタスクで例外（OSErrorなど）が発生しても、他のタスクの処理（mark_task_doneなど）
    が正常に行われ、ループ全体がクラッシュしないことを確認します。
    """
    mock_hub = MagicMock()
    mock_hub_class.return_value = mock_hub
    
    dummy_queue = {
        "current_batch_id": "test_batch_err",
        "tasks": [
            {
                "id": "T-test_batch_err-bug_hunter-000",
                "status": "running",
                "assigned_agent": "conv-uuid-error"
            },
            {
                "id": "T-test_batch_err-bug_hunter-001",
                "status": "running",
                "assigned_agent": "conv-uuid-ok"
            }
        ]
    }
    
    mock_file = MagicMock()
    mock_file.__enter__.return_value = mock_file
    mock_open.return_value = mock_file
    
    with patch("json.load", side_effect=[dummy_queue, dummy_queue]):
        # 1つ目の agent 読み込み時に OSError を擬似発生させ、2つ目は正常終了
        def mock_check(conv_id):
            if conv_id == "conv-uuid-error":
                raise OSError("Simulated disk error")
            return {"status": "pass", "report": {"message": "ok"}}
            
        mock_check_transcript.side_effect = mock_check
        
        # 例外が発生するが、メインループはクラッシュしないはず
        main()
        
        # 正常なタスク T-test_batch_err-bug_hunter-001 に対してのみ mark_task_done が呼ばれていること
        mock_hub.mark_task_done.assert_called_once_with(
            "T-test_batch_err-bug_hunter-001", "pass", {"message": "ok"}
        )

def test_check_subagent_transcript_skip(mock_brain_dir):
    """
    トランスクリプトに 'skip' または 'skipped' が含まれる場合に、ステータスが 'skipped' にマッピングされることを確認します。
    """
    # skip のケース
    conv_id = "test-skip-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = conv_dir / "transcript.jsonl"
    steps = [
        {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "結果: skip", "tool_calls": []}
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "skipped"

    # skipped のケース
    conv_id = "test-skipped-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = conv_dir / "transcript.jsonl"
    steps = [
        {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "結果: skipped", "tool_calls": []}
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "skipped"

def test_check_subagent_transcript_failed(mock_brain_dir):
    """
    トランスクリプトに 'failed' が含まれる場合に、ステータスが 'fail' にマッピングされることを確認します。
    """
    conv_id = "test-failed-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = conv_dir / "transcript.jsonl"
    steps = [
        {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "結果: failed", "tool_calls": []}
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "fail"

def test_check_subagent_transcript_fallback_skip(mock_brain_dir):
    """
    フォールバック処理で 'skip' または 'skipped' が含まれる場合に、ステータスが 'skipped' にマッピングされることを確認します。
    """
    # send_message のフォールバック
    conv_id = "test-fallback-skip-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = conv_dir / "transcript.jsonl"
    steps = [
        {
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "content": "some explanation",
            "tool_calls": [
                {
                    "name": "send_message",
                    "args": {"Message": "Here is the result: skipped", "Recipient": "parent"}
                }
            ]
        }
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "skipped"

    # combined_text のフォールバック
    conv_id = "test-fallback-skip-combined"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = conv_dir / "transcript.jsonl"
    steps = [
        {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "結果: skip", "tool_calls": []}
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "skipped"


def test_check_subagent_transcript_windows_path(mock_brain_dir):
    # Windowsのパス区切り文字が含まれる場合に、正しく抽出され '/' に正規化されることを確認します。
    conv_id = "test-win-path-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = conv_dir / "transcript.jsonl"
    
    # メッセージ中に Windows 形式のバックスラッシュを含むパスを書く
    steps = [
        {
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "content": "結果: pass",
            "tool_calls": [
                {
                    "name": "send_message",
                    "args": {"Message": "結果: pass\nModified file 'backend\\agents\\orchestration\\check_subagents_loop.py'", "Recipient": "parent"}
                }
            ]
        }
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
            
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert "backend/agents/orchestration/check_subagents_loop.py" in res["report"]["changed_files"]


def test_check_subagent_transcript_mixed_precedence(mock_brain_dir):
    # メッセージ内に pass と fail が混在している場合に、優先順位に従って fail が選択されることを確認します。
    conv_id = "test-mixed-precedence-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = conv_dir / "transcript.jsonl"
    
    # pass と fail が混在するメッセージ
    steps = [
        {
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "content": "some explanation",
            "tool_calls": [
                {
                    "name": "send_message",
                    "args": {"Message": "結果: fail\nHere is the result: 10 tests passed, but 1 failed.", "Recipient": "parent"}
                }
            ]
        }
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
            
    res = check_subagent_transcript(conv_id)
    assert res is not None
    assert res["status"] == "fail"


def test_check_subagent_transcript_truncation(mock_brain_dir):
    # 非常に長いメッセージの場合に、頭と末尾が残る形で切り詰められていることを確認します。
    conv_id = "test-truncation-id"
    conv_dir = mock_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = conv_dir / "transcript.jsonl"
    
    long_msg = "A" * 1500 + "RESULTS_SUMMARY" + "B" * 1500 + "結果: pass"
    steps = [
        {
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "content": "結果: pass",
            "tool_calls": [
                {
                    "name": "send_message",
                    "args": {"Message": long_msg, "Recipient": "parent"}
                }
            ]
        }
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
            
    res = check_subagent_transcript(conv_id)
    assert res is not None
    raw_out = res["report"]["raw_output"]
    assert len(raw_out) < len(long_msg)
    assert "... [TRUNCATED] ..." in raw_out
    # 最初と最後の部分が含まれていること
    assert raw_out.startswith("A" * 1000)
    assert raw_out.endswith("結果: pass")


def test_check_subagent_transcript_env_app_data(tmp_path):
    # ANTIGRAVITY_APP_DATA 環境変数が設定されている場合に、そのパスが優先されることを確認します。
    custom_app_dir = tmp_path / "custom_app_data"
    custom_brain_dir = custom_app_dir / "brain"
    conv_id = "test-env-path-id"
    conv_dir = custom_brain_dir / conv_id / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True, exist_ok=True)
    transcript_file = conv_dir / "transcript.jsonl"
    
    steps = [
        {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "結果: pass", "tool_calls": []}
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")
            
    # 環境変数をセットしてテスト実行
    os.environ["ANTIGRAVITY_APP_DATA"] = str(custom_app_dir)
    try:
        res = check_subagent_transcript(conv_id)
        assert res is not None
        assert res["status"] == "pass"
    finally:
        del os.environ["ANTIGRAVITY_APP_DATA"]
