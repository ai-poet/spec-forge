from specforge.cli_commands import (
    DEFAULT_CLI_BINDINGS,
    build_cli_command,
    parse_cli_bindings,
    resolve_cli_provider,
    serialize_cli_bindings,
)


def test_resolve_cli_provider_defaults():
    assert resolve_cli_provider(None, "prd_planner") == DEFAULT_CLI_BINDINGS["prd_planner"]
    assert resolve_cli_provider(None, "code_tester") == "claude"


def test_resolve_cli_provider_override():
    bindings = {"code_tester": "claude", "prd_planner": "codex"}
    assert resolve_cli_provider(bindings, "code_tester") == "claude"
    assert resolve_cli_provider(bindings, "prd_planner") == "codex"
    assert resolve_cli_provider(bindings, "coder") == DEFAULT_CLI_BINDINGS["coder"]


def test_serialize_and_parse_cli_bindings_roundtrip():
    raw = serialize_cli_bindings({"code_tester": "claude", "coder": "codex"})
    assert raw is not None
    parsed = parse_cli_bindings(raw)
    assert parsed == {"code_tester": "claude", "coder": "codex"}


def test_build_cli_command_codex_vs_claude():
    prompt = "verify"
    schema_inline = "{}"
    schema_file = __import__("pathlib").Path("/tmp/code_tester.schema.json")
    codex_cmd = build_cli_command(provider="codex", prompt=prompt, schema_inline=schema_inline, schema_file=schema_file)
    claude_cmd = build_cli_command(provider="claude", prompt=prompt, schema_inline=schema_inline, schema_file=schema_file)
    assert codex_cmd[0] == "codex"
    assert claude_cmd[0] == "claude"
    assert "--include-hook-events" in claude_cmd
