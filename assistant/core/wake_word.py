"""Wake phrase matching after a complete utterance, preserving its command."""
import re

class WakeWordDetector:
    def __init__(self, wake_word="джарвис", aliases=None):
        words = [wake_word, *(aliases or [])]
        self.pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in words if w) + r")(?!\w)", re.I)

    def extract_command(self, text):
        match = self.pattern.search(text)
        if match is None:
            return None
        return text[match.end():].lstrip(" ,.!?:;—-")
