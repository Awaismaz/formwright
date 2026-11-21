/** Board thumbnails: fetch each part snapshot's line-art SVG once (per snapshot key), parse it into feature groups,
 * and share it between every card and the drawer. The server draws a thumbnail on first request and answers 202
 * meanwhile (src/aicad/office/thumbs.py); a card waits with a neutral silhouette. */
import { useEffect, useState } from "react";
import { apiHeaders } from "@/lib/api";
import { BASE } from "./api";
import { FEATURE_KINDS, type FeatureKind } from "./model";

export interface ThumbGroup { g: number; feature: FeatureKind; d: number | null; vis: string; hid: string }
export interface Thumb { viewBox: string; groups: ThumbGroup[] }

const PATH_D = /^[ML0-9.\- ]*$/;
const GROUP = /<g data-feature="(\w+)" data-g="(\d+)"(?: data-d="([\d.]+)")?>(.*?)<\/g>/g;
const PATH = /<path([^>]*?) d="([^"]*)"\s*\/>/g;

/** Our own SVG format only (drawing/thumb.py): groups of path data, nothing else is kept. */
export function parseThumb(svg: string): Thumb | null {
  const vb = /viewBox="([\d.\s-]+)"/.exec(svg)?.[1];
  if (!vb || !svg.includes("data-fw-thumb")) return null;
  const groups: ThumbGroup[] = [];
  for (const m of svg.matchAll(GROUP)) {
    const feature = m[1] as FeatureKind;
    if (!FEATURE_KINDS.includes(feature)) continue;
    let vis = "", hid = "";
    for (const p of (m[4] ?? "").matchAll(PATH)) {
      const d = p[2] ?? "";
      if (!PATH_D.test(d)) continue;
      if ((p[1] ?? "").includes('data-hidden="1"')) hid += (hid ? " " : "") + d; else vis += (vis ? " " : "") + d;
    }
    groups.push({ g: Number(m[2]), feature, d: m[3] ? Number(m[3]) : null, vis, hid });
  }
  return { viewBox: vb.trim(), groups };
}

export function thumbUrl(pid: string, item: string, state: "ghost" | "real", key: string): string {
  return `${BASE}/programs/${encodeURIComponent(pid)}/items/${encodeURIComponent(item)}/thumb?state=${state}&k=${encodeURIComponent(key)}`;
}

// one fetch per URL (the URL carries the snapshot key), at most a few at a time so cards never starve the API
const done = new Map<string, Thumb | null>();
const pending = new Map<string, Promise<Thumb | null>>();
const queue: (() => void)[] = [];
let running = 0;
const MAX_PARALLEL = 3;
// the first drawing of a session can wait for the drawing engine to start (tens of seconds on a busy machine)
const GIVE_UP_MS = 120_000;
const wait = (i: number) => Math.min(500 * 1.4 ** i, 4000);

function slot<T>(fn: () => Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const go = () => { running += 1; fn().then(resolve, reject).finally(() => { running -= 1; queue.shift()?.(); }); };
    if (running < MAX_PARALLEL) go(); else queue.push(go);
  });
}
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

export function cachedThumb(url: string): Thumb | null | undefined {
  return done.get(url);
}

export function loadThumb(url: string): Promise<Thumb | null> {
  if (done.has(url)) return Promise.resolve(done.get(url) ?? null);
  const inflight = pending.get(url);
  if (inflight) return inflight;
  const p = (async () => {
    const t0 = Date.now();
    for (let i = 0; ; i++) {
      const res = await slot(() => fetch(url, { headers: apiHeaders("GET"), credentials: "same-origin" }));
      if (res.status === 202 && Date.now() - t0 < GIVE_UP_MS) { await sleep(wait(i)); continue; }
      if (!res.ok || res.status === 202) {
        if (res.status !== 202) done.set(url, null); // missing for this key: never asked again this session
        return null;
      }
      const t = parseThumb(await res.text());
      done.set(url, t);
      return t;
    }
  })().catch(() => null).finally(() => pending.delete(url));
  pending.set(url, p);
  return p;
}

/** The parsed thumbnail for a URL once ``enabled`` (the card scrolled into view): undefined while loading, null
 * when there is none. */
export function useThumb(url: string | null, enabled: boolean): Thumb | null | undefined {
  const [, bump] = useState(0);
  const have = url ? cachedThumb(url) : null;
  useEffect(() => {
    if (!url || !enabled || done.has(url)) return;
    let live = true;
    loadThumb(url).then(() => { if (live) bump(n => n + 1); });
    return () => { live = false; };
  }, [url, enabled]);
  return url ? have : null;
}

/** Has this card been seen on screen? (IntersectionObserver; once true it stays true.) */
export function useSeen<T extends Element>(): [(el: T | null) => void, boolean] {
  const [el, setEl] = useState<T | null>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    if (!el || seen) return;
    if (typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { setSeen(true); io.disconnect(); } },
      { rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [el, seen]);
  return [setEl, seen];
}

/** The cross-fade from placeholder to real part plays once per part per browser session. */
export function fadeOnce(realKey: string): boolean {
  try {
    const k = `fw_thumb_fade_${realKey}`;
    if (sessionStorage.getItem(k)) return false;
    sessionStorage.setItem(k, "1");
  } catch { /* storage unavailable: still play it once for this card */ }
  return true;
}

export function reducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}
