"""Fish Audio speech adapter. Credentials and response bodies are never logged."""
import httpx
from dotenv import dotenv_values
from pastor_ray.settings import ROOT, load_config

async def fish_speech(text,path):
    cfg=load_config()
    key=dotenv_values(ROOT/'.env').get('FISH_AUDIO_API_KEY')
    voice=cfg.get('fish_voice_id')
    if not key or not voice:
        raise RuntimeError('Fish Audio key or voice is missing')
    async with httpx.AsyncClient(timeout=120,trust_env=False) as client:
        response=await client.post('https://api.fish.audio/v1/tts',
            headers={'Authorization':'Bearer '+key,'model':cfg.get('fish_model','s2.1-pro-free')},
            json={'text':text,'reference_id':voice,'format':'mp3','mp3_bitrate':128,
                  'latency':'balanced','prosody':{'speed':1.0,'volume':0}})
        if response.status_code!=200:
            raise RuntimeError(f'Fish Audio synthesis failed (HTTP {response.status_code})')
        if len(response.content)<500 or 'json' in response.headers.get('content-type',''):
            raise RuntimeError('Fish Audio returned no usable audio')
        path.write_bytes(response.content)
