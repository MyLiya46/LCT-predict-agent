from app.services.chat_bridge import native_event_to_status


def test_native_events_only_project_to_status_and_keep_last_40_steps():
    steps = []
    status = []
    for event, data in [
        ("agent.process", {"state": "starting"}),
        ("agent.status", {"state": "planning"}),
        ("tool.call", {"name": "get_history"}),
        ("tool.result", {"name": "get_history"}),
        ("done", {"status": "completed"}),
    ]:
        item = native_event_to_status(event, data, steps)
        if item:
            status.append(item)
    assert [item["stage"] for item in status] == ["starting", "planning", "executing", "executing", "done"]
    assert status[-1]["steps"][-1] == "处理完成"
    for i in range(50):
        native_event_to_status("agent.process", {"state": f"state-{i}"}, steps)
    assert len(steps) == 40

