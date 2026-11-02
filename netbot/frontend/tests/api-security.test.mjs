import test from 'node:test';
import assert from 'node:assert/strict';
import {createApi} from '../modules/api.mjs';

test('tokens stay in memory; old persistent credentials and mutable URL are discarded', async () => {
  const storage = new Map([
    ['netbot_tokens', JSON.stringify({access_token:'legacy',refresh_token:'legacy-refresh'})],
    ['netbot_api_url', 'https://untrusted.invalid'],
  ]);
  const localStorage = {getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
  const requests=[];
  const options={localStorage,state:{session:0},fetch:async (url, init)=>{
    requests.push({url,init});return {status:200,ok:true,json:async()=>({})};
  }};
  const api=createApi(options);
  assert.equal(api.getStoredTokens(),null);
  api.setTokens({access_token:'test-access',refresh_token:'test-refresh'});
  assert.equal(storage.size,0);
  const snapshot=api.getStoredTokens(); snapshot.access_token='tampered';
  await api.authedRequest('/auth/me');
  assert.equal(requests[0].init.headers.Authorization,'Bearer test-access');
  assert.ok(!requests[0].url.includes('untrusted.invalid'));
  assert.equal(createApi(options).getStoredTokens(),null);
  api.clearTokens();
  assert.equal(api.getStoredTokens(),null);
});
