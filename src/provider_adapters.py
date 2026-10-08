"""Adapter for Anthropic API using AsyncOpenAI interface."""
import json
from typing import Any

from anthropic import AsyncAnthropic


class MockToolCallFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class MockToolCall:
    def __init__(self, id: str, type: str, function: MockToolCallFunction):
        self.id = id
        self.type = type
        self.function = function


class MockMessage:
    def __init__(self, content: str, tool_calls: list = None, role: str = "assistant"):
        self.content = content
        self.tool_calls = tool_calls or []
        self.role = role


class MockChoice:
    def __init__(self, message: MockMessage, finish_reason: str = "stop"):
        self.message = message
        self.finish_reason = finish_reason


class MockUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int, total_tokens: int):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class MockCompletion:
    def __init__(self, choices: list[MockChoice], usage: MockUsage, id: str):
        self.choices = choices
        self.usage = usage
        self.id = id


class AsyncAnthropicAdapter:
    """A wrapper around AsyncAnthropic that mocks the AsyncOpenAI interface.
    
    Translates OpenAI tool calls, messages, and schemas to Anthropic's format dynamically.
    """
    
    def __init__(self, api_key: str, base_url: str):
        # We strip trailing /v1 because anthropic sdk adds it or expects base url without it
        clean_url = base_url.replace("/v1", "").strip() if base_url else None
        self._client = AsyncAnthropic(api_key=api_key, base_url=clean_url)
        self.chat = self.Chat(self._client)

    class Chat:
        def __init__(self, client):
            self.completions = self.Completions(client)

        class Completions:
            def __init__(self, client):
                self._client = client

            async def create(self, model: str, messages: list[dict], **kwargs):
                system_prompt = ""
                anthropic_messages = []
                
                # 1. Convert messages from OpenAI format to Anthropic format
                for msg in messages:
                    role = msg.get("role")
                    content = msg.get("content", "")
                    
                    if role == "system":
                        system_prompt += content + "\n\n"
                    elif role == "user":
                        anthropic_messages.append({"role": "user", "content": content or " "})
                    elif role == "assistant":
                        tool_calls = msg.get("tool_calls")
                        if tool_calls:
                            content_blocks = []
                            if content:
                                content_blocks.append({"type": "text", "text": content})
                            for tc in tool_calls:
                                tc_func = tc.get("function", {})
                                tc_args_str = tc_func.get("arguments", "{}")
                                try:
                                    tc_args = json.loads(tc_args_str)
                                except Exception:
                                    tc_args = {}
                                content_blocks.append({
                                    "type": "tool_use",
                                    "id": tc.get("id"),
                                    "name": tc_func.get("name"),
                                    "input": tc_args
                                })
                            anthropic_messages.append({"role": "assistant", "content": content_blocks})
                        else:
                            anthropic_messages.append({"role": "assistant", "content": content or " "})
                    elif role == "tool":
                        tc_id = msg.get("tool_call_id")
                        anthropic_messages.append({
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tc_id,
                                    "content": content
                                }
                            ]
                        })

                # 2. Consolidate consecutive messages of the same role (Anthropic requirement)
                consolidated = []
                for msg in anthropic_messages:
                    if consolidated and consolidated[-1]["role"] == msg["role"]:
                        old_content = consolidated[-1]["content"]
                        new_content = msg["content"]
                        
                        if isinstance(old_content, str):
                            old_blocks = [{"type": "text", "text": old_content}]
                        elif isinstance(old_content, list):
                            old_blocks = list(old_content)
                        else:
                            old_blocks = [old_content]
                            
                        if isinstance(new_content, str):
                            new_blocks = [{"type": "text", "text": new_content}]
                        elif isinstance(new_content, list):
                            new_blocks = list(new_content)
                        else:
                            new_blocks = [new_content]
                            
                        consolidated[-1]["content"] = old_blocks + new_blocks
                    else:
                        consolidated.append(msg)
                        
                # Ensure first message is 'user'
                if consolidated and consolidated[0]["role"] == "assistant":
                    consolidated.insert(0, {"role": "user", "content": " "})

                create_kwargs = {
                    "model": model,
                    "max_tokens": kwargs.get("max_tokens") or kwargs.get("max_completion_tokens") or 4096,
                    "system": system_prompt.strip(),
                    "messages": consolidated,
                }
                
                if "temperature" in kwargs:
                    create_kwargs["temperature"] = kwargs["temperature"]
                
                # 3. Translate tool definitions (OpenAI to Anthropic format)
                if "tools" in kwargs:
                    anthropic_tools = []
                    for t in kwargs["tools"]:
                        if t.get("type") == "function":
                            f = t.get("function", {})
                            anthropic_tools.append({
                                "name": f.get("name"),
                                "description": f.get("description", ""),
                                "input_schema": f.get("parameters", {"type": "object", "properties": {}})
                            })
                    if anthropic_tools:
                        create_kwargs["tools"] = anthropic_tools
                        
                        # Translate tool choice
                        tool_choice = kwargs.get("tool_choice")
                        if tool_choice == "auto":
                            create_kwargs["tool_choice"] = {"type": "auto"}
                        elif tool_choice == "required":
                            create_kwargs["tool_choice"] = {"type": "any"}
                        elif isinstance(tool_choice, dict) and "function" in tool_choice:
                            create_kwargs["tool_choice"] = {
                                "type": "tool",
                                "name": tool_choice["function"]["name"]
                            }

                response = await self._client.messages.create(**create_kwargs)
                
                # 4. Extract content and tool calls from response
                output_text = ""
                tool_calls = []
                for block in response.content:
                    if block.type == "text":
                        output_text += block.text
                    elif block.type == "tool_use":
                        tool_calls.append(
                            MockToolCall(
                                id=block.id,
                                type="function",
                                function=MockToolCallFunction(
                                    name=block.name,
                                    arguments=json.dumps(block.input, ensure_ascii=False)
                                )
                            )
                        )
                
                # Build mock OpenAI completion
                msg_obj = MockMessage(content=output_text, tool_calls=tool_calls)
                choice = MockChoice(message=msg_obj, finish_reason=response.stop_reason or "stop")
                
                usage = MockUsage(
                    prompt_tokens=response.usage.input_tokens,
                    completion_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                )
                
                return MockCompletion(choices=[choice], usage=usage, id=response.id)
