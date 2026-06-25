from backend.inference.client import parse_tool_calls

OPEN = "<|tool_call>"
CLOSE = "<tool_call|>"
Q = '<|"|>'


def test_gemma_native_through_parse_tool_calls():
    content = OPEN + "call:direct_scene{moods:[" + Q + "talkative" + Q + "],history-summary:" + Q + "x, y" + Q + "}" + CLOSE
    assert parse_tool_calls({"content": content}) == [
        {"name": "direct_scene", "arguments": {"moods": ["talkative"], "history-summary": "x, y"}}
    ]


def test_standard_tool_calls():
    msg = {"tool_calls": [{"function": {"name": "x", "arguments": '{"a": 1}'}}]}
    assert parse_tool_calls(msg) == [{"name": "x", "arguments": {"a": 1}}]


def test_hermes_tags():
    msg = {"content": '<tool_call>{"name": "x", "arguments": {"a": 1}}</tool_call>'}
    assert parse_tool_calls(msg) == [{"name": "x", "arguments": {"a": 1}}]


def test_json_in_content():
    msg = {"content": '{"name": "x", "arguments": {}}'}
    assert parse_tool_calls(msg) == [{"name": "x", "arguments": {}}]


def test_sanitize_strips_leaked_delimiter():
    # A server that parsed the DSL to JSON but left the <|"|> token inside a
    # string value: arguments decodes to {"k": 'a<|"|>b'}, sanitized to 'ab'.
    msg = {"tool_calls": [{"function": {"name": "x", "arguments": r'{"k":"a<|\"|>b"}'}}]}
    assert parse_tool_calls(msg) == [{"name": "x", "arguments": {"k": "ab"}}]


def test_empty_message():
    assert parse_tool_calls({"content": ""}) == []
    assert parse_tool_calls({}) == []


def test_editor_apply_patch_objects():
    content = OPEN + "call:editor_apply_patch{patches:[{search:" + Q + "foo" + Q + ",replace:" + Q + "bar" + Q + "}]}" + CLOSE
    assert parse_tool_calls({"content": content}) == [
        {"name": "editor_apply_patch", "arguments": {"patches": [{"search": "foo", "replace": "bar"}]}}
    ]
