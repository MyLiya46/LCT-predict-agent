from app.services.chat_envelope import build_envelope


def test_all_response_types_and_compat_intent_mapping():
    for kind, intent in {
        "history": "history",
        "forecast": "forecast",
        "attribution": "attribution",
        "simulation": "whatif",
        "optimization": "whatif",
    }.items():
        result = build_envelope(
            "最终文字",
            [{"name": kind, "status": "ok", "output": {"response_type": kind}}],
            [],
            "completed",
        )
        assert result["response_type"] == kind
        assert result["intent"] == intent
        assert "input" not in result


def test_rows_are_projected_to_sorted_table_and_final_text_wins():
    result = build_envelope(
        "engine text",
        [{
            "name": "get_history",
            "status": "ok",
            "output": {
                "response_type": "history",
                "rows": [{"z": 1, "a": 2}],
                "envelope": {"text": {"markdown": "tool text"}},
            },
        }],
        [str(i) for i in range(50)],
        "completed",
    )
    assert result["text"]["markdown"] == "engine text"
    assert [column["key"] for column in result["table"]["columns"]] == ["a", "z"]
    assert len(result["process_steps"]) == 40


def test_explain_and_plain_text_fall_back_to_report():
    explain = build_envelope(
        "解释",
        [{"name": "explain", "status": "ok", "output": {"response_type": "explain"}}],
        [],
        "completed",
    )
    plain = build_envelope("报告", [], [], "failed")
    assert explain["response_type"] == "attribution"
    assert plain["response_type"] == "report"
    assert plain["intent"] is None
    assert plain["meta"]["status"] == "failed"
