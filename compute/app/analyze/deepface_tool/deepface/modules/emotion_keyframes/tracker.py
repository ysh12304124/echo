from .models import EmotionSegment



class EmotionTracker:
    def __init__(self):
        self.current = None
    def update(self, frame):
        if self.current is None:
            self.current = EmotionSegment(
                frame.emotion
            )
            self.current.add(frame)
            return None
        if frame.emotion == self.current.emotion:
            self.current.add(frame)
            return None
        old = self.current
        self.current = EmotionSegment(
            frame.emotion
        )
        self.current.add(frame)
        return (
            old,
            self.current
        )