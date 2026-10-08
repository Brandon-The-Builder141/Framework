const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const Opus=require('opusscript');
const {speechResource}=require('./audio.cjs');

test('resumed MP3 starts at the requested position and produces decodable Opus',async()=>{
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'ray-seek-test-'));
  const file=path.join(folder,'tones.mp3');
  try {
    execFileSync('ffmpeg',['-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=2','-f','lavfi','-i','sine=frequency=880:duration=2','-filter_complex','[0:a][1:a]concat=n=2:v=0:a=1','-codec:a','libmp3lame',file],{windowsHide:true});
    async function frequency(offset) {
      const resource=speechResource(file,offset);
      const decoder=new Opus(48000,2,Opus.Application.AUDIO);
      let crossings=0,samples=0,previous=0,count=0;
      try {
        await new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>reject(Error('audio decode timeout')),5000);
        resource.playStream.on('error',reject);
        resource.playStream.on('data',packet=>{
          const pcm=decoder.decode(packet);
          if(count++<5) return;
          for(let i=0;i<pcm.length;i+=4) {
            const value=pcm.readInt16LE(i);
            if(previous<=0 && value>0) crossings++;
            previous=value;samples++;
          }
          if(count>=15) {clearTimeout(timeout);resource.playStream.pause();resolve();}
        });
        });
      } finally {resource.playStream.destroy();resource.stopTranscoder();decoder.delete();await resource.transcoderClosed;}
      return crossings/samples*48000;
    }
    const start=await frequency(0);
    const resumed=await frequency(2.5);
    assert.ok(start>400 && start<480,`start frequency ${start}`);
    assert.ok(resumed>820 && resumed<940,`resumed frequency ${resumed}`);
  } finally {
    fs.rmSync(folder,{recursive:true,force:true});
  }
});
