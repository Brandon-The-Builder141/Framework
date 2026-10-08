"""Run the production service pipeline offline, including real planning, review and TTS."""
import asyncio,json,time,subprocess,sys,hashlib,traceback
from datetime import datetime
from types import SimpleNamespace
from pastor_ray.brain import Brain
from pastor_ray.settings import load_config,ROOT
from pastor_ray.sermons import SermonSession,audio_duration

class OpeningComplete(Exception):pass

async def main():
    folder=ROOT/'data'/('pipeline-check-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(exist_ok=True)
    hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('services.py','sermons.py','pastoral.py','speech.py','brain.py')}
    brain=Brain(load_config());started=time.monotonic();results=[]
    complete=brain.complete
    async def traced_complete(messages,tokens=650):
        begin=time.monotonic()
        result=await complete(messages,tokens)
        # This harness supplies synthetic public requests only, never member DMs.
        with (folder/'generation-trace.jsonl').open('a',encoding='utf-8') as output:
            output.write(json.dumps({'elapsed':round(time.monotonic()-started,1),'seconds':round(time.monotonic()-begin,1),'prompt':messages[0]['content'],'reply':result})+'\n')
        return result
    brain.complete=traced_complete
    teach=brain.teach
    async def traced_teach(messages,tokens=1200):
        begin=time.monotonic()
        result=await teach(messages,tokens)
        with (folder/'generation-trace.jsonl').open('a',encoding='utf-8') as output:
            output.write(json.dumps({'phase':'teaching','elapsed':round(time.monotonic()-started,1),'seconds':round(time.monotonic()-begin,1),'prompt':messages[0]['content'],'reply':result})+'\n')
        return result
    brain.teach=traced_teach
    review=brain.review
    async def traced_review(messages,tokens=400):
        begin=time.monotonic()
        result=await review(messages,tokens)
        with (folder/'generation-trace.jsonl').open('a',encoding='utf-8') as output:
            output.write(json.dumps({'phase':'independent-review','elapsed':round(time.monotonic()-started,1),'seconds':round(time.monotonic()-begin,1),'prompt':messages[0]['content'],'reply':result})+'\n')
        return result
    brain.review=traced_review
    async def context():return []
    session=SermonSession(SimpleNamespace(brain=brain,public_context=context))
    session.topic='Lead a morning service titled Built on Rock. Choose three related verses, explain their meaning and show how to live them out.'
    if '--generic' in sys.argv:
        session.topic='Lead a morning service. Choose the topic and three related verses yourself, explain their meaning, and show how to live them out.'
    async def announce(text):
        # Persist only this synthetic public test, never real private conversations.
        with (folder/'announcements.txt').open('a',encoding='utf-8') as file:file.write(text+'\n\n')
    async def no_listening(*args):pass
    async def play(path):
        duration=await audio_duration(path)
        proc=await asyncio.create_subprocess_exec('ffmpeg','-v','error','-i',str(path),'-f','null','-',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            await asyncio.wait_for(proc.communicate(),30)
            if proc.returncode:raise RuntimeError('Audio decoding failed')
        finally:
            if proc.returncode is None:proc.kill();await proc.wait()
        result={'file':path.name,'ready_seconds':round(time.monotonic()-started,1),'duration_seconds':round(duration,1)}
        results.append(result);print(json.dumps(result),flush=True)
        if '--opening-only' in sys.argv and len(results)==2:raise OpeningComplete()
        if '--through-first-teaching' in sys.argv and path.name.startswith('service-4-'):raise OpeningComplete()
    session.announce=announce;session.play=play;session.set_listening=no_listening
    failure=None
    try:
        await session.stream_service(20,folder)
    except OpeningComplete:
        pass
    except Exception as exc:
        failure=type(exc).__name__+': '+str(exc)
        (folder/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        await brain.close()
        (folder/'transcript.txt').write_text(session.transcript,encoding='utf-8')
        finish=0;gaps=[]
        for item in results:
            gaps.append(round(max(0,item['ready_seconds']-finish),1) if finish else 0)
            finish=max(finish,item['ready_seconds'])+item['duration_seconds']
        mode='opening-only' if '--opening-only' in sys.argv else 'through-first-teaching' if '--through-first-teaching' in sys.argv else 'full'
        report={'mode':mode,'request':session.topic,'code_sha256':hashes,'failure':failure,'sections':results,'total_audio_minutes':sum(x['duration_seconds'] for x in results)/60,'estimated_inter_section_gaps_seconds':gaps,'note':'Real model, review, TTS and decoding; simulated playback clock, no Discord connection.'}
        (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('REPORT',str(folder),json.dumps(report),flush=True)
    if failure:raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
