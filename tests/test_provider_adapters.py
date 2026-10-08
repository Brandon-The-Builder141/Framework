import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from src.provider_adapters import AsyncAnthropicAdapter


@pytest.mark.asyncio
async def test_anthropic_adapter_translates_tools_and_messages(monkeypatch):
    # Mock AsyncAnthropic client
    mock_messages_api = MagicMock()
    mock_create = AsyncMock()
    mock_messages_api.create = mock_create
    
    # Mock Anthropic Response
    mock_response = MagicMock()
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = "Hello! I am calling a tool."
    
    mock_tool_use_block = MagicMock()
    mock_tool_use_block.type = "tool_use"
    mock_tool_use_block.id = "tc_999"
    mock_tool_use_block.name = "write_file"
    mock_tool_use_block.input = {"path": "test.txt", "content": "hello"}
    
    mock_response.content = [mock_text_block, mock_tool_use_block]
    mock_response.stop_reason = "tool_use"
    mock_response.id = "msg_123"
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 20
    
    mock_create.return_value = mock_response
    
    # Initialize adapter
    adapter = AsyncAnthropicAdapter(api_key="mock_key", base_url="https://api.anthropic.com")
    adapter._client.messages = mock_messages_api
    
    # OpenAI style messages
    openai_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Please write hello to test.txt."},
        {"role": "assistant", "content": "I am about to call write_file.", "tool_calls": [
            {
                "id": "tc_001",
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": '{"path": "test.txt", "content": "hello"}'
                }
            }
        ]},
        {"role": "tool", "tool_call_id": "tc_001", "content": "Success"}
    ]
    
    # OpenAI style tools
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write text content to path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["path", "content"]
                }
            }
        }
    ]
    
    # Call completions.create
    resp = await adapter.chat.completions.create(
        model="claude-3-5-sonnet-20241022",
        messages=openai_messages,
        tools=openai_tools,
        tool_choice="auto",
        temperature=0.7
    )
    
    # Verify client create kwargs
    mock_create.assert_called_once()
    kwargs = mock_create.call_args[1]
    
    assert kwargs["model"] == "claude-3-5-sonnet-20241022"
    assert kwargs["system"] == "You are a helpful assistant."
    assert kwargs["temperature"] == 0.7
    
    # Verify tool translation
    assert len(kwargs["tools"]) == 1
    t = kwargs["tools"][0]
    assert t["name"] == "write_file"
    assert "input_schema" in t
    assert t["input_schema"]["properties"]["path"]["type"] == "string"
    
    # Verify messages translation & consolidation
    anthropic_msgs = kwargs["messages"]
    # The messages should alternate between user and assistant
    assert len(anthropic_msgs) == 3 # user, assistant, user (tool result)
    assert anthropic_msgs[0]["role"] == "user"
    assert anthropic_msgs[1]["role"] == "assistant"
    # Assistant has content blocks
    assert isinstance(anthropic_msgs[1]["content"], list)
    assert anthropic_msgs[1]["content"][1]["type"] == "tool_use"
    assert anthropic_msgs[2]["role"] == "user"
    assert anthropic_msgs[2]["content"][0]["type"] == "tool_result"
    
    # Verify mock OpenAI response output
    assert resp.id == "msg_123"
    assert resp.usage.total_tokens == 30
    assert len(resp.choices) == 1
    choice = resp.choices[0]
    assert choice.message.content == "Hello! I am calling a tool."
    assert choice.finish_reason == "tool_use"
    assert len(choice.message.tool_calls) == 1
    tc = choice.message.tool_calls[0]
    assert tc.id == "tc_999"
    assert tc.function.name == "write_file"
    assert json.loads(tc.function.arguments)["path"] == "test.txt"


@pytest.mark.asyncio
async def test_switch_backend_anthropic(monkeypatch, tmp_path):
    # Isolate data directory
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    
    import config.settings
    monkeypatch.setattr(config.settings, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(config.settings, "USER_PROFILES_DIR", test_data_dir / "profiles")
    
    import src.backend_switching
    monkeypatch.setattr(src.backend_switching, "USER_PROFILES_DIR", test_data_dir / "profiles")
    
    # Enable Anthropic in config/settings
    monkeypatch.setattr(config.settings, "ANTHROPIC_API_KEY", "mock_anthropic_key")
    monkeypatch.setattr(src.backend_switching, "ANTHROPIC_API_KEY", "mock_anthropic_key")
    
    # Mock health check for Anthropic and OpenAI (life support fallback)
    async def mock_health_check(backend_id, **kwargs):
        return {"healthy": True, "reason": "ok", "message": "healthy"}
        
    monkeypatch.setattr(src.backend_switching, "health_check_backend", mock_health_check)
    
    # Run switch_backend_provider
    res = await src.backend_switching.switch_backend_provider(
        target="anthropic",
        user_id="default"
    )
    
    # Verify success
    assert res["success"] is True
    assert "anthropic" in res["active_backend"]
    assert res["fallback_used"] is False
    
    # Verify saved state
    state = src.backend_switching.load_state("default")
    assert "anthropic" in state["active_backend"]
