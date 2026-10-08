from src.agent.core import _extract_user_task_for_escalation


def test_extracts_discord_message_after_contact_profile():
    wrapped = (
        "[Contact profile: Tier: best_friend\nName: Travis]\n\n"
        "## Current speaker (THIS MESSAGE)\nYou are talking to **Travis**\n\n"
        "Message from Travis (Discord, discord_id=550782786013757442) who just said: "
        "clone quote-ai and get it running locally"
    )
    assert _extract_user_task_for_escalation(wrapped) == "clone quote-ai and get it running locally"


def test_plain_user_message_passthrough():
    assert _extract_user_task_for_escalation("fix the vite config") == "fix the vite config"
