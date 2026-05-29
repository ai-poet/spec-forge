from specforge.cli_commands import (
    DEFAULT_CLI_BINDINGS,
    build_tester_command,
    parse_cli_bindings,
    resolve_cli_provider,
    serialize_cli_bindings,
)


def test_resolve_cli_provider_defaults():
    assert resolve_cli_provider(None, "planner") == DEFAULT_CLI_BINDINGS["planner"]
    assert resolve_cli_provider(None, "tester") == "claude"


def test_resolve_cli_provider_override():
    bindings = {"tester": "claude", "planner": "codex"}
    assert resolve_cli_provider(bindings, "tester") == "claude"
    assert resolve_cli_provider(bindings, "planner") == "codex"
    assert resolve_cli_provider(bindings, "coder") == DEFAULT_CLI_BINDINGS["coder"]


def test_serialize_and_parse_cli_bindings_roundtrip():
    raw = serialize_cli_bindings({"tester": "claude", "coder": "codex"})
    assert raw is not None
    parsed = parse_cli_bindings(raw)
    assert parsed == {"tester": "claude", "coder": "codex"}


def test_build_tester_command_codex_vs_claude():
    prompt = "verify"
    schema_inline = "{}"
    schema_file = __import__("pathlib").Path("/tmp/tester.schema.json")
    codex_cmd = build_tester_command(provider="codex", prompt=prompt, schema_inline=schema_inline, schema_file=schema_file)
    claude_cmd = build_tester_command(provider="claude", prompt=prompt, schema_inline=schema_inline, schema_file=schema_file)
    assert codex_cmd[0] == "codex"
    assert claude_cmd[0] == "claude"
