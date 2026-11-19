import { lazy, Suspense, useRef } from "react";
import type { PartSceneProps } from "./PartScene";
import { useInView } from "./motion";

const PartScene = lazy(() => import("./PartScene"));

/** Very small devices (2 cores or fewer, or under 2 GB) get the poster instead of a WebGL scene. */
export function lowEndDevice(): boolean {
  if (typeof navigator === "undefined") return false;
  const n = navigator as Navigator & { deviceMemory?: number };
  return (n.hardwareConcurrency ?? 8) <= 2 || (n.deviceMemory ?? 8) < 2;
}

/** Loads three.js and the part files only when the stage comes near the viewport; the poster shows until then. */
export default function LazyScene(props: PartSceneProps & { eager?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useInView(ref, { once: true, margin: "400px 0px", threshold: 0 });
  const wait = props.poster ?? <div className="flex h-full items-center justify-center"><div className="h-14 w-14 rounded-full border-2 border-primary/20 border-t-primary/70 motion-safe:animate-spin" /></div>;
  const posterOnly = !!props.poster && lowEndDevice();
  return (
    <div ref={ref} className="h-full w-full">
      {posterOnly ? props.poster : (near || props.eager) ? <Suspense fallback={wait}><PartScene {...props} /></Suspense> : wait}
    </div>
  );
}
