"""Generate audition files only; does not connect to or send anything to Discord.

Uses Edge's online TTS with a fixed public script, never private memory.
Run: python -m pastor_ray.voice_prototype
"""
import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

import edge_tts

from pastor_ray.settings import ROOT
from pastor_ray.scripture import passages


async def main():
    output = ROOT / 'assets' / 'voice-audition'
    output.mkdir(parents=True, exist_ok=True)
    source = passages('Ephesians 4:32')
    if len(source) != 1:
        raise RuntimeError('Install local KJV source before making the audition.')
    verse = source[0].split('(KJV): ', 1)[1]
    sections = [
        "Hey, friends. Let's take a moment to talk about forgiveness. Sometimes the hardest person to forgive is the one you expected to protect your heart.",
        'Ephesians, chapter four, verse thirty-two, says: '+verse,
        "Here's what that means in everyday language. We practice forgiveness because God has shown us grace through Christ. That doesn't make the hurt imaginary. And it doesn't mean you must immediately trust someone who keeps harming you. Forgiveness and rebuilding trust are different things.",
        "So here's one small step for today. Bring that hurt honestly to God. You don't have to dress it up. Ask him for wisdom, for a heart free from revenge, and for the courage to keep healthy boundaries.",
        "Father, help us receive your grace and extend it with wisdom. Give us strength for the next faithful step. In Jesus' name, amen.",
        "What part of forgiveness feels hardest to you? You can put a question in the channel chat, and we can talk it through.",
    ]
    (output/'script.txt').write_text('\n\n'.join(sections),encoding='utf-8')
    manifest = []
    for label, voice, rate in [('A-andrew','en-US-AndrewNeural','-8%'),('B-brian','en-US-BrianNeural','-8%')]:
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            for i,text in enumerate(sections):
                await asyncio.wait_for(edge_tts.Communicate(text,voice,rate=rate).save(str(temp/f'{i}.mp3')),90)
            args = ['ffmpeg','-hide_banner','-loglevel','error','-y']
            for i in range(len(sections)):
                args += ['-i',str(temp/f'{i}.mp3')]
            filters = [f'[{i}:a]aresample=24000,apad=pad_dur=0.7[a{i}]' for i in range(len(sections))]
            filters.append(''.join(f'[a{i}]' for i in range(len(sections)))+f'concat=n={len(sections)}:v=0:a=1,loudnorm=I=-18:TP=-1.5:LRA=11[out]')
            target = output/f'pastor-ray-{label}.mp3'
            subprocess.run(args+['-filter_complex',';'.join(filters),'-map','[out]','-codec:a','libmp3lame','-b:a','128k',str(target)],check=True)
            info = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-of','json',str(target)],text=True))
            subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],check=True)
            entry = {'file':target.name,'voice':voice,'rate':rate,'seconds':round(float(info['format']['duration']),1),'bytes':target.stat().st_size}
            manifest.append(entry)
            print(json.dumps(entry),flush=True)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')


if __name__=='__main__':
    asyncio.run(main())
