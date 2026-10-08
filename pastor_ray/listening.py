"""Ephemeral local transcription for public sermon Q&A. No disk recordings."""
import base64
import re
import threading


def addressed_question(text):
    match=re.match(r'^\s*(?:(?:hey|okay|ok|so)[,!. ]+)?(?:pastor\s+)?(?:ray|rae|rey)[,!.: ]+(.+)',text,re.I)
    if not match:
        return None
    question=match[1].strip()
    return question if len(question)>=3 else None


class Transcriber:
    def __init__(self):
        self.model=None
        self.lock=threading.Lock()

    def ready(self):
        with self.lock:
            if self.model is None:
                from faster_whisper import WhisperModel
                self.model=WhisperModel('base',device='cpu',compute_type='int8',cpu_threads=2,local_files_only=True)

    def transcribe(self,encoded):
        if len(encoded)>7_680_000:
            return ''
        import numpy as np
        raw=base64.b64decode(encoded,validate=True)
        if not 48000<=len(raw)<=5_760_000 or len(raw)%4:
            return ''
        # Discord PCM: 48 kHz stereo s16; average channels and low-pass before 3:1 decimation.
        samples=np.frombuffer(raw,dtype='<i2').reshape(-1,2).mean(axis=1)/32768.0
        count=len(samples)//3*3
        audio=samples[:count].reshape(-1,3).mean(axis=1).astype(np.float32)
        if np.sqrt(np.mean(audio**2))<.002:
            return ''
        self.ready()
        with self.lock:
            segments,_=self.model.transcribe(audio,language='en',beam_size=1,vad_filter=True,
                condition_on_previous_text=False,temperature=0)
            return ' '.join(s.text.strip() for s in segments if s.no_speech_prob<.6 and s.avg_logprob>-1.0 and s.compression_ratio<2.4)[:1000]
