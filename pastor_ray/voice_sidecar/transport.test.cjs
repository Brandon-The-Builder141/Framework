const test=require('node:test');
const assert=require('node:assert/strict');
const {verifyTransport}=require('./transport.cjs');
function connection(){return {state:{networking:{state:{connectionData:{packetsPlayed:0}}}}};}
test('a ready player with stalled transport fails',async()=>{
  await assert.rejects(verifyTransport(connection(),40),/no-packets/);
});
test('transport packet dispatch is observed',async()=>{
  const conn=connection();
  setTimeout(()=>conn.state.networking.state.connectionData.packetsPlayed++,5);
  assert.equal(await verifyTransport(conn,100),1);
});
test('a disconnected transport fails',async()=>{
  const conn=connection();
  setTimeout(()=>conn.state.networking=undefined,5);
  await assert.rejects(verifyTransport(conn,100),/changed/);
});
