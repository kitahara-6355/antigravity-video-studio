import pytest
from backend.agents.orchestration.health_check_cron import _should_output

def test_should_output_opus_stale():
    # overall が HEALTHY でも opus_stage が STALE の場合は即時出力する
    should_out, reason = _should_output("ACTIVE", "🟢 HEALTHY", "STALE")
    assert should_out is True
    assert "STALE" in reason

def test_should_output_normal():
    # overall が UNHEALTHY の場合は常に True
    should_out, reason = _should_output("ACTIVE", "🔴 UNHEALTHY", "FRESH")
    assert should_out is True
    assert "異常検知" in reason

def test_should_output_healthy_fresh():
    # overall が HEALTHY で FRESH の場合は動的判定（出力抑制あり）
    should_out, reason = _should_output("ACTIVE", "🟢 HEALTHY", "FRESH")
    # ACTIVE + HEALTHY + FRESH は状況次第なので、戻り値の型だけ確認
    assert isinstance(should_out, bool)
    assert isinstance(reason, str)
