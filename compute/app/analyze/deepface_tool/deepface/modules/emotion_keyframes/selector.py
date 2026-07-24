class KeyframeSelector:
    def __init__(self):
        # 保存已经保存过的帧编号
        self.saved_frames = set()
    def select(self, transition):
        old_segment, new_segment = transition
        keyframes = []

        before = old_segment.best_frame()
        if before is not None:
            if before.frame_idx not in self.saved_frames:
                keyframes.append(before)

                self.saved_frames.add(
                    before.frame_idx
                )
        return keyframes