// A private stdio bridge. Python owns the Discord gateway; this process owns voice.
const readline = require('node:readline');
const {createAudioPlayer, joinVoiceChannel, entersState,
  VoiceConnectionStatus, AudioPlayerStatus, EndBehaviorType} = require('@discordjs/voice');
const {speechResource}=require('./audio.cjs');
const {verifyTransport}=require('./transport.cjs');
const prism = require('prism-media');
let connection, adapter;
let allowed = new Set(), listening = false, epoch = 0;
let baseOffset=0;
const captures = new Map();
const player = createAudioPlayer();
const emit = data => process.stdout.write(JSON.stringify(data)+'\n');

function discardCaptures() {
  epoch++;
  for (const item of captures.values()) item.cancel();
  captures.clear();
}

function receive(userId) {
  if (!listening || !allowed.has(userId) || captures.has(userId) || captures.size >= 4) return;
  const generation = epoch;
  const stream = connection.receiver.subscribe(userId, {end:{behavior:EndBehaviorType.AfterSilence,duration:1200}});
  const decoder = new prism.opus.Decoder({rate:48000,channels:2,frameSize:960});
  const chunks = [];
  let size=0, finished=false;
  const finish = (deliver) => {
    if (finished) return;
    finished=true;
    clearTimeout(timer);
    captures.delete(userId);
    stream.destroy(); decoder.destroy();
    if (deliver && listening && generation===epoch && size>=48000 && size<=5760000) {
      emit({event:'utterance',userId,epoch:generation,pcm:Buffer.concat(chunks).toString('base64')});
    }
  };
  const timer=setTimeout(()=>finish(true),30000);
  captures.set(userId,{cancel:()=>finish(false)});
  decoder.on('data',chunk=>{
    size+=chunk.length;
    if (size>5760000) return finish(false);
    chunks.push(chunk);
  });
  decoder.on('end',()=>finish(true));
  decoder.on('error',()=>{emit({event:'receive_error',kind:'decode'});finish(false);});
  stream.on('error',()=>{emit({event:'receive_error',kind:'decrypt-or-stream'});finish(false);});
  stream.pipe(decoder);
}

player.on('stateChange',(old,state)=>{
  if(old.resource && old.resource!==state.resource) old.resource.stopTranscoder?.();
  emit({event:'player',state:state.status});
});
player.on('error',()=>emit({event:'playback_error'}));

async function command(m) {
  switch(m.command) {
    case 'connect': {
      if (connection) throw Error('already-connected');
      connection=joinVoiceChannel({guildId:m.guildId,channelId:m.channelId,selfDeaf:false,selfMute:false,
        adapterCreator: callbacks=>{
          adapter=callbacks;
          return {sendPayload:payload=>{emit({event:'gateway',payload});return true;},destroy:()=>{adapter=undefined;}};
        }});
      connection.on('stateChange',(old,state)=>emit({event:'connection',state:state.status}));
      connection.on('error',()=>emit({event:'receive_error',kind:'connection'}));
      connection.receiver.speaking.on('start',receive);
      connection.subscribe(player);
      await entersState(connection,VoiceConnectionStatus.Ready,30000);
      return {connected:true};
    }
    case 'voice_state': adapter?.onVoiceStateUpdate(m.data);return {};
    case 'voice_server': adapter?.onVoiceServerUpdate(m.data);return {};
    case 'listen':
      if (listening!==Boolean(m.enabled)) discardCaptures();
      listening=Boolean(m.enabled);
      allowed=new Set(m.users || []);
      for (const [userId,item] of captures) {
        if (!allowed.has(userId)) item.cancel();
      }
      return {listening,epoch};
    case 'play': {
      if (!connection || connection.state.status!==VoiceConnectionStatus.Ready) throw Error('not-connected');
      const voiceState=connection.packets.state;
      if (voiceState?.mute || voiceState?.self_mute || voiceState?.suppress) throw Error('voice-muted-or-suppressed');
      if (!listening) discardCaptures();
      baseOffset=Number(m.offset || 0);
      const resource=speechResource(m.path,baseOffset);
      player.play(resource);
      await entersState(player,AudioPlayerStatus.Playing,20000);
      try {
        const packetsSent=await verifyTransport(connection);
        return {playing:true,packetsSent};
      } catch(error) {
        player.stop(true);
        throw error;
      }
    }
    case 'position': return {seconds:baseOffset+(player.state.resource?.playbackDuration || 0)/1000};
    case 'pause': player.pause();discardCaptures();return {};
    case 'resume': player.unpause();return {};
    case 'stop': player.stop(true);discardCaptures();return {};
    case 'disconnect':
      listening=false;discardCaptures();player.stop(true);
      if (connection && connection.state.status!==VoiceConnectionStatus.Destroyed) connection.destroy();
      connection=undefined;
      return {};
    default: throw Error('unknown-command');
  }
}

const lines=readline.createInterface({input:process.stdin});
lines.on('line',line=>{
  let m;
  try { m=JSON.parse(line); } catch { return; }
  // Gateway updates must run while the connect request is waiting for Ready.
  command(m).then(result=>{if(m.id) emit({id:m.id,result});})
    .catch(error=>{if(m.id) emit({id:m.id,error:'Voice sidecar '+m.command+' failed: '+
      (['voice-muted-or-suppressed','voice-transport-unavailable','voice-transport-changed','voice-transport-no-packets'].includes(error.message)?error.message:error.name),
      diagnostic: String(error.stack || '').split('\n').slice(1,4).map(s=>s.trim())});});
});
lines.on('close',()=>{
  listening=false;discardCaptures();player.stop(true);
  if(connection && connection.state.status!==VoiceConnectionStatus.Destroyed) connection.destroy();
  process.exit(0);
});
