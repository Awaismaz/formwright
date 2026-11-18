import { lazy, Suspense, useRef } from "react";
import type { PartSceneProps } from "./PartScene";
import { useInView } from "./motion";

const PartScene = lazy(() => import("./PartScene"));

/** Loads three.js and the part files only when the stage comes near the viewport. */
export default function LazyScene(props: PartSceneProps & { eager?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useInView(ref, { once: true, margin: "400px 0px", threshold: 0 });
  const spinner = <div className="flex h-full items-center justify-center"><div className="h-14 w-14 rounded-full border-2 border-primary/20 border-t-primary/70 motion-safe:animate-spin" /></div>;
  return (
    <div ref={ref} className="h-full w-full">
      {(near || props.eager) ? <Suspense fallback={spinner}><PartScene {...props} /></Suspense> : spinner}
    </div>
  );
}
