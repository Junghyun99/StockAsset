from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "run-forced-dip-stage.yml"
)


def test_forced_dip_stage_workflow_is_limited_and_token_cache_enabled():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "      stage:" in workflow
    assert "type: choice" in workflow
    assert "          - '1'" in workflow
    assert "          - '2'" in workflow
    assert "          - '3'" in workflow
    assert "      reason:" in workflow
    assert "      account:" not in workflow
    assert "group: live-trading-domestic" in workflow
    assert "name: Check Korean holiday" in workflow
    assert "skip_holiday_check" not in workflow
    assert "name: Restore KIS token cache" in workflow
    assert "name: Decrypt KIS token cache" in workflow
    assert "name: Encrypt KIS token cache" in workflow
    assert "name: Save KIS token cache" in workflow
    assert "id: encrypt-token-cache" in workflow
    assert "cache_saved=true" in workflow
    assert "steps.encrypt-token-cache.outputs.cache_saved == 'true'" in workflow
    assert "KIS_TOKEN_CACHE_KEY" in workflow
    assert "kis-token-domestic-" in workflow
    assert "MY_TEST_KIS_APP_KEY" in workflow
    assert "MY_TEST_KIS_APP_SECRET" in workflow
    assert "MY_TEST_KIS_ACC_NO" in workflow
    assert "--account my_test" in workflow
    assert "STAGE: ${{ inputs.stage }}" in workflow
    assert "REASON: ${{ inputs.reason }}" in workflow
    assert "--stage \"$STAGE\"" in workflow
    assert "--reason \"$REASON\"" in workflow
    assert 'file_pattern: "docs/data/*.json docs/data/**/*.json logs/ci/*.log"' in workflow
