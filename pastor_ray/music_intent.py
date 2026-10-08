"""Route explicit music requests to real controls before conversational inference."""
import re


def music_intent(text):
    text = re.sub(r"<@!?\d+>", " ", text.lower()).replace("’", "'").strip()
    text = re.sub(r"^\d+[.)]\s*", "", text)
    # Do not turn negation, anecdotes, or quoted examples into playback.
    if re.search(r"\b(don't|do not|never|can't|cannot|shouldn't|not now)\b", text):
        return None
    if re.search(r"\b(i told|i asked|he said|she said|yesterday|used to|how (?:do|can)|what happens)\b", text):
        return None
    if '"' in text or '`' in text:
        return None
    text = re.sub(r"^(?:(?:hey|okay|ok|please|bro)[, !]*\s*|(?:pastor\s+)?ray[, !]*\s*)+", "", text)
    text = re.sub(r"^(?:can|could|would|will) you\s+", "", text)
    text = re.sub(r"^(?:please\s+|go ahead and\s+)", "", text)
    text = re.sub(r"^(?:i want you to|i need you to|let's|lets)\s+", "", text)
    # Compound requests can omit the channel: 'join and play the choir'.
    if re.match(r"^(?:join|come|hop|jump|get|connect)\b", text) and re.search(r"\b(?:play|start|put on)\b.*\b(?:choir|music|worship|playlist|gospel|songs?)\b", text):
        return "play"
    if re.fullmatch(r"(?:join(?: us| me| the party)?|hop in|jump in|come on in)[.!?]*", text):
        return "play"
    patterns = [
        ("stop", r"^(?:stop|end)\s+(?:the\s+)?(?:choir|music|worship|playlist|songs?)\b|^(?:leave|disconnect)(?:\s+(?:from\s+)?(?:the\s+)?(?:voice|channel|meditation vibes|vc))?[.!?]*$"),
        ("pause", r"^pause(?:\s+(?:the\s+)?(?:choir|music|worship|playlist|song|it))?\b"),
        ("resume", r"^(?:resume|unpause)(?:\s+(?:the\s+)?(?:choir|music|worship|playlist|song|it))?\b|^keep playing\b"),
        ("skip", r"^skip(?:\s+(?:this|the))?(?:\s+(?:song|track|one))?\b|^next (?:song|track)\b|^change (?:the )?(?:song|track)\b"),
        ("playlist", r"^(?:show|list)(?: me)? (?:the |your )?(?:songs|playlist|music)\b|^what (?:songs|music) (?:do you have|can you play)\b"),
        ("play", r"^(?:join|hop into|hop in|come to|connect to)\s+(?:the\s+)?(?:meditation vibes|voice(?: channel)?|vc|channel)\b|^(?:play|start|put on|turn on)(?:\s+(?:the|some|your))?\s+(?:choir|music|worship|christian music|gospel|playlist|songs)\b"),
    ]
    for command, pattern in patterns:
        if re.search(pattern, text):
            return command
    if text.rstrip(" .!?") in {"play", "pause", "resume", "skip", "stop"}:
        return text.rstrip(" .!?")
    return None
