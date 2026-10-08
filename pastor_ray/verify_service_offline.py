"""Offline full-service acceptance check; never connects to Discord."""
import asyncio,json,time,subprocess
from pathlib import Path
from pastor_ray.brain import Brain
from pastor_ray.settings import load_config,ROOT
from pastor_ray.pastoral import plan_service
from pastor_ray.services import build_service
from pastor_ray.sermons import synthesize,audio_duration

async def main():
    folder=ROOT/'data'/'service-acceptance'
    folder.mkdir(exist_ok=True)
    brain=Brain(load_config());started=time.monotonic();results=[]
    try:
        plan=await asyncio.wait_for(plan_service(brain,'Lead a 20-minute morning service titled Built on Rock. Choose three related verses and explain their meaning with concrete everyday applications.'),120)
        (folder/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
        print('PLAN',plan['title'],len(plan['sources']),'verses',round(time.monotonic()-started,1),'seconds',flush=True)
        async def section(text,index):
            path=folder/f'{index}.mp3'
            (folder/f'{index}.txt').write_text(text,encoding='utf-8')
            await asyncio.wait_for(synthesize(text,path),180)
            duration=await audio_duration(path)
            proc=await asyncio.create_subprocess_exec('ffmpeg','-v','error','-i',str(path),'-f','null','-',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            await asyncio.wait_for(proc.communicate(),30)
            if proc.returncode: raise RuntimeError('Audio decoding failed')
            result={'section':index,'ready_seconds':round(time.monotonic()-started,1),'duration_seconds':round(duration,1),'words':len(text.split())}
            results.append(result);print(json.dumps(result),flush=True)
        await build_service(brain,json.dumps(plan),20,on_section=section,verified_sources=plan['sources'])
        finish=0;gaps=[]
        for item in results:
            gap=max(0,item['ready_seconds']-finish) if finish else 0
            gaps.append(round(gap,1))
            finish=max(finish,item['ready_seconds'])+item['duration_seconds']
        report={'sections':results,'total_audio_minutes':sum(x['duration_seconds'] for x in results)/60,'inter_section_gaps_seconds':gaps,'first_audio_seconds':results[0]['ready_seconds']}
        (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('REPORT',json.dumps(report),flush=True)
    finally: await brain.close()

if __name__=='__main__':asyncio.run(main())
