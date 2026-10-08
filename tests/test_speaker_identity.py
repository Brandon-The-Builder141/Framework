"""Discord speaker identity must not treat contacts as the owner."""
from src.contacts import format_current_speaker_for_prompt, is_owner_discord_id


def test_travis_is_not_owner():
    travis = "550782786013757442"
    brandon = "531896743063846943"
    assert not is_owner_discord_id(travis)
    block = format_current_speaker_for_prompt(travis, display_name="Travis")
    assert "Travis" in block
    assert "NOT" in block
    assert brandon not in block or "discord_id=" in block


def test_owner_id_normalization():
    assert is_owner_discord_id("531896743063846943")
    assert is_owner_discord_id("531896743063846943_id")
