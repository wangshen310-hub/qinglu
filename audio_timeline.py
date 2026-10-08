"""Place loopback samples on a clocked timeline, preserving silent intervals."""
import queue
import threading
import wave


class AudioTimeline:
    def __init__(self, path, rate, channels, origin):
        self.rate = rate
        self.frame_bytes = channels * 2
        self.origin = origin
        self.frames = 0
        self.error = None
        self.inserted_silence = 0
        self.trimmed_overlap = 0
        self.queue = queue.Queue(maxsize=256)
        self.wav = wave.open(str(path), 'wb')
        self.wav.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
        self.worker = threading.Thread(target=self._write, name='Audio timeline writer', daemon=False)
        self.worker.start()

    def submit(self, data, sample_time):
        if self.error:
            raise RuntimeError(self.error)
        self.queue.put_nowait((data, round((sample_time-self.origin)*self.rate)))

    def _write(self):
        silence = bytes(self.rate * self.frame_bytes)
        try:
            while True:
                block = self.queue.get()
                if block is None:
                    break
                if self.error:
                    continue
                try:
                    data, position = block
                    # A negative start is audio captured before the shared epoch.
                    if position < 0:
                        trim = min(len(data)//self.frame_bytes, -position)
                        data = data[trim*self.frame_bytes:]
                        position += trim
                    if not data:
                        continue
                    gap = position-self.frames
                    # PortAudio's block timestamps have small scheduling jitter.
                    # Do not insert/drop a few samples on every contiguous block.
                    if abs(gap) <= max(1, round(.003*self.rate)):
                        gap = 0
                    if gap > 0:
                        self.inserted_silence += gap
                        while gap:
                            count = min(gap, self.rate)
                            self.wav.writeframesraw(silence[:count*self.frame_bytes])
                            self.frames += count
                            gap -= count
                    elif gap < 0:
                        trim = min(-gap, len(data)//self.frame_bytes)
                        self.trimmed_overlap += trim
                        data = data[trim*self.frame_bytes:]
                    if data:
                        self.wav.writeframesraw(data)
                        self.frames += len(data)//self.frame_bytes
                except Exception as exc:
                    self.error = str(exc)
        finally:
            try:
                self.wav.close()
            except Exception as exc:
                self.error = str(exc)

    def close(self):
        self.queue.put(None)
        self.worker.join()
        if self.error:
            raise RuntimeError(self.error)
