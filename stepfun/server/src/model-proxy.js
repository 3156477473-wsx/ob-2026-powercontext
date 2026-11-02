import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

import { config } from './config.js';

// 浏览器直连模型源经常被 CORS 拦住（hf-mirror 不返回 Access-Control-Allow-Origin），
// 因此统一由 Node 桥代取：浏览器只访问同源的 /api/model/*，不存在跨域问题。
let mirror = config.modelMirror.replace(/\/+$/, '');

export const upstream = () => mirror;

export const setUpstream = (value) => {
  if (typeof value !== 'string' || !value.trim()) {
    throw Object.assign(new Error('model source must be a non-empty string'), { status: 400 });
  }
  const parsed = new URL(value.trim());
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw Object.assign(new Error('model source must be an http(s) URL'), { status: 400 });
  }
  mirror = `${parsed.origin}${parsed.pathname}`.replace(/\/+$/, '');
  return mirror;
};

const FORWARDED_HEADERS = ['content-type', 'content-length', 'etag', 'last-modified'];

export async function proxyModel(rest, res) {
  const target = `${mirror}/${rest}`;
  const response = await fetch(target, { redirect: 'follow', headers: { accept: '*/*' } });
  if (!response.ok || !response.body) {
    throw Object.assign(new Error(`upstream ${target} responded ${response.status}`), {
      status: response.status === 404 ? 404 : 502,
    });
  }
  for (const header of FORWARDED_HEADERS) {
    const value = response.headers.get(header);
    if (value) {
      res.setHeader(header, value);
    }
  }
  res.setHeader('access-control-allow-origin', '*');
  res.setHeader('cache-control', 'public, max-age=86400');
  res.status(200);
  await pipeline(Readable.fromWeb(response.body), res);
}