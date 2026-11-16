import { lazy, type ComponentType, type LazyExoticComponent } from "react";

/** Props every live module app receives. `projectId` comes from `?project=<id>` (e.g. opened from the Studio). */
export interface ModuleAppProps { code: string; projectId: string | null }

/**
 * Live module apps, auto-discovered: a module ships `web/src/pages/app/modules/<code>/index.tsx` with a default
 * export taking ModuleAppProps. The module page renders it when the catalog marks the module "live" and the
 * workspace has it unlocked. No shared file needs editing to add a module.
 */
const found = import.meta.glob<{ default: ComponentType<ModuleAppProps> }>("./*/index.tsx");

export const MODULE_APPS: Record<string, LazyExoticComponent<ComponentType<ModuleAppProps>>> = Object.fromEntries(
  Object.entries(found).map(([path, load]) => [path.split("/")[1]!, lazy(load)]),
);
