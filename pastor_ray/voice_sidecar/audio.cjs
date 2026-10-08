const {resolve} = require('node:path');
const {existsSync} = require('node:fs');
const prism = require('prism-media');
const {createAudioResource,StreamType} = require('@discordjs/voice');

function speechResource(input,offset=0) {
  const path=resolve(input);
  if (!existsSync(path) || !path.endsWith('.mp3')) throw Error('invalid-audio-file');
  if (!Number.isFinite(offset) || offset<0 || offset>7200) throw Error('invalid-offset');
  const stream=new prism.FFmpeg({args:['-nostdin','-loglevel','error','-ss',String(offset),'-i',path,'-f','s16le','-ar','48000','-ac','2']});
  const resource=createAudioResource(stream,{inputType:StreamType.Raw,inlineVolume:true});
  resource.transcoderClosed=new Promise(resolve=>stream.process.once('exit',resolve));
  resource.stopTranscoder=()=>stream.destroy();
  resource.volume.setVolume(1);
  resource.playStream.once('close',()=>stream.destroy());
  return resource;
}

module.exports={speechResource};

