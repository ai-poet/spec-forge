#!/usr/bin/env python3
"""
Codex SDK 最小复现 Demo - 复现真实流水线中的调用方式

用法:
    python test_codex_repro.py                    # 复现 planner_discovery 调用
    python test_codex_repro.py --stage prd_planner # 复现 prd_planner 调用
    python test_codex_repro.py --raw-stream        # 打印所有流式事件
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


def load_prompt_from_log():
    """从真实日志中提取 prompt（简化版，使用固定测试 prompt）"""
    return """## SpecForge stage: planner_discovery

You are Planner for SpecForge in requirements discovery mode.

Iteration goal: 做一个本地 Web 控制台,可视化这条流水线的运行。

Return only JSON matching this shape:
{status:ask|ready, complexity:trivial|simple|moderate|complex, question?:string, options:[string], assumptions:[string], requirements_brief:string, rationale:string}

(first discovery turn — produce a question or mark ready based on the brief above)"""


def print_section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def test_codex_sdk_with_real_prompt(args):
    """使用真实 prompt 和 output_schema 测试 Codex SDK"""

    print_section("环境检查")
    print(f"  OPENAI_API_KEY env: {'已设置' if os.environ.get('OPENAI_API_KEY') else '未设置'}")

    # 检查 codex 认证文件
    auth_paths = [Path.home() / ".codex" / "auth.json", Path.home() / ".config" / "codex" / "auth.json"]
    for p in auth_paths:
        if p.exists():
            print(f"  codex auth.json: {p}")
            try:
                data = json.loads(p.read_text())
                key = data.get("OPENAI_API_KEY", "")
                if key:
                    os.environ["OPENAI_API_KEY"] = key
                    print(f"    已加载 API Key: {key[:8]}...{key[-4:]}")
            except Exception as e:
                print(f"    读取失败: {e}")
            break

    print_section("SDK 导入")
    try:
        from openai_codex import ApprovalMode, Codex, Sandbox
        print("  ✓ openai_codex 导入成功")
    except ImportError as e:
        print(f"  ✗ 导入失败: {e}")
        return 1

    # 构建真实的 output_schema（和流水线中一致）
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["ask", "ready"]},
            "complexity": {"type": "string", "enum": ["trivial", "simple", "moderate", "complex"]},
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "requirements_brief": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": ["status", "complexity", "assumptions", "requirements_brief", "rationale"],
    }

    prompt = load_prompt_from_log()

    print_section("开始 Codex 调用")
    print(f"  stage: {args.stage}")
    print(f"  prompt length: {len(prompt)} chars")
    print(f"  output_schema: {json.dumps(schema, ensure_ascii=False)[:100]}...")

    try:
        with Codex() as codex:
            print("  → Codex() 实例化成功")

            # 检查 client 配置
            client = getattr(codex, '_client', None)
            if client:
                print(f"  → client type: {type(client).__name__}")
                # 尝试获取 base_url
                oai_client = getattr(client, '_client', None)
                if oai_client:
                    base_url = getattr(oai_client, 'base_url', None)
                    print(f"  → API base_url: {base_url}")

            print("  → 创建 thread...")
            thread = codex.thread_start(
                approval_mode=ApprovalMode.auto_review,
                sandbox=Sandbox.full_access,
            )
            print(f"  ✓ thread 创建成功: {thread.id}")

            print("  → 启动 turn（带 output_schema）...")
            print("  → 等待响应（可能需要 10-60 秒）...")

            turn = thread.turn(
                prompt,
                approval_mode=ApprovalMode.auto_review,
                sandbox=Sandbox.full_access,
                output_schema=schema,
            )

            print("  → 消费流式输出...")
            event_count = 0
            error_events = []
            structured_output = None
            final_text = None

            for notification in turn.stream():
                event_count += 1
                payload = getattr(notification, 'payload', notification)

                # 提取关键信息
                if isinstance(payload, dict):
                    # 检查错误
                    if payload.get('type') == 'error' or 'error' in payload:
                        error_events.append(payload)
                        print(f"\n  ⚠ ERROR EVENT [{event_count}]:")
                        print(f"    {json.dumps(payload, ensure_ascii=False, default=str)[:500]}")

                    # 检查 turn 完成状态
                    turn_data = payload.get('turn')
                    if isinstance(turn_data, dict):
                        status = turn_data.get('status')
                        error = turn_data.get('error')
                        if error:
                            print(f"\n  ⚠ TURN ERROR [{event_count}]: status={status}, error={error}")

                    # 提取 item
                    item = payload.get('item')
                    if isinstance(item, dict):
                        item_type = item.get('type', '')
                        # 提取 structured_output
                        if 'structured_output' in item:
                            structured_output = item['structured_output']
                        # 提取 agent_message text
                        if item_type == 'agentMessage' and 'text' in item:
                            final_text = item['text']

                    # 原始流输出
                    if args.raw_stream:
                        print(f"\n  [{event_count}] {type(payload).__name__}:")
                        dump = json.dumps(payload, ensure_ascii=False, default=str)
                        print(f"    {dump[:500]}{'...' if len(dump) > 500 else ''}")

            print(f"\n  ✓ 流结束，共 {event_count} 个事件")

            if error_events:
                print(f"\n  ⚠ 共 {len(error_events)} 个错误事件")

            if structured_output:
                print(f"\n  ✓ structured_output:")
                print(f"    {json.dumps(structured_output, ensure_ascii=False, indent=2)[:500]}")
            else:
                print(f"\n  ✗ 未找到 structured_output")

            if final_text:
                print(f"\n  ✓ final_text:")
                print(f"    {final_text[:500]}{'...' if len(final_text) > 500 else ''}")

            return 0

    except Exception as e:
        print(f"\n  ✗ 调用失败")
        print(f"    错误类型: {type(e).__name__}")
        print(f"    错误信息: {e}")
        import traceback
        traceback.print_exc()
        return 1


def test_simple_no_schema():
    """不带 output_schema 的简单测试（排除 schema 问题）"""
    print_section("简单测试（无 output_schema）")

    auth_paths = [Path.home() / ".codex" / "auth.json", Path.home() / ".config" / "codex" / "auth.json"]
    for p in auth_paths:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                key = data.get("OPENAI_API_KEY", "")
                if key:
                    os.environ["OPENAI_API_KEY"] = key
            except:
                pass
            break

    try:
        from openai_codex import ApprovalMode, Codex, Sandbox
    except ImportError:
        print("  ✗ SDK 未安装")
        return 1

    try:
        with Codex() as codex:
            thread = codex.thread_start(
                approval_mode=ApprovalMode.auto_review,
                sandbox=Sandbox.full_access,
            )
            print(f"  thread: {thread.id}")

            turn = thread.turn(
                "Say 'hello from codex sdk test' and nothing else.",
                approval_mode=ApprovalMode.auto_review,
                sandbox=Sandbox.full_access,
            )

            print("  streaming...")
            for i, notification in enumerate(turn.stream()):
                payload = getattr(notification, 'payload', notification)
                if isinstance(payload, dict) and payload.get('type') == 'error':
                    print(f"  ⚠ error: {payload}")

            print("  ✓ done")
            return 0
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Codex SDK 复现 Demo")
    parser.add_argument("--stage", default="planner_discovery", help="stage name")
    parser.add_argument("--raw-stream", action="store_true", help="打印所有流式事件")
    parser.add_argument("--simple", action="store_true", help="只运行简单测试")
    args = parser.parse_args()

    print("Codex SDK 复现测试")
    print(f"Python: {sys.version}")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    if args.simple:
        return test_simple_no_schema()

    return test_codex_sdk_with_real_prompt(args)


if __name__ == "__main__":
    sys.exit(main())
