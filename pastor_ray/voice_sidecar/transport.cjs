// Player state alone does not prove the Discord transport sent audio.
async function verifyTransport(connection,timeout=2000) {
  const networking=connection.state.networking;
  const initial=networking?.state.connectionData?.packetsPlayed;
  if (!Number.isFinite(initial)) throw Error('voice-transport-unavailable');
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) {
    await new Promise(resolve=>setTimeout(resolve,20));
    if(connection.state.networking!==networking) throw Error('voice-transport-changed');
    const sent=networking.state.connectionData?.packetsPlayed-initial;
    if(sent>0) return sent;
  }
  throw Error('voice-transport-no-packets');
}
module.exports={verifyTransport};
