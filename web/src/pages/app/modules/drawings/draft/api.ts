import { api } from "@/lib/api";
import type { Anno, DEnt, Dim, DPoint, DraftDoc, SheetSpec } from "./geom";
import type { Prim } from "./prims";

export const DBASE = "/api/m/drawings/drafts";

export interface DraftItem { id: string; name: string; rev: number; updated_at: string; created_at: string; summary: { entities: number; dims: number; annos: number; sheet: string; scale: string } }
export interface DraftRev { rev: number; date: string; by: string; note: string; entities: number; dims: number; annos: number }
export interface SheetCheck { passed: boolean; problems: string[]; dangling: string[]; outside: string[]; over_title_block: string[]; overlaps: string[][]; model_check: null; note: string }
export interface DraftState extends DraftItem { doc: DraftDoc; revs: DraftRev[]; can_edit: boolean; check: SheetCheck; dimensions: { id: string; type: string; value: number | null; ok: boolean; text?: string }[]; linked_model: null }
export interface TemplateDef { name: string; label: string; params: { key: string; label: string; default: number; integer: boolean }[] }
export interface TemplatesInfo { items: TemplateDef[]; sheets: string[]; scales: string[]; layers: { key: string; iso: string; label: string; width: number }[] }
export interface Fragment { geom: { points: DPoint[]; entities: DEnt[] }; dims: Dim[]; annos: Anno[]; extent?: number[]; template?: string; params?: Record<string, number>; missing?: string[] }
export interface FrameResp { prims: Prim[]; w: number; h: number; frame: number[]; blocked: number[][]; origin: [number, number] }
export interface AssistResp { source: "template" | "ai"; fragment: Fragment; missing: string[]; message: string; tokens?: number }

export const draftsApi = {
  list: () => api.get<{ items: DraftItem[] }>(DBASE),
  templates: () => api.get<TemplatesInfo>(`${DBASE}/templates`),
  get: (id: string) => api.get<DraftState>(`${DBASE}/${id}`),
  create: (body: { name: string; sheet: Partial<SheetSpec>; title?: Record<string, string>; template?: string | null; params?: Record<string, number>; local_date?: string; tz?: string }) =>
    api.post<DraftState>(DBASE, body),
  save: (id: string, body: { doc: DraftDoc; name?: string; note?: string; base_rev?: number }) => api.post<DraftState>(`${DBASE}/${id}`, body),
  remove: (id: string) => api.del<{ ok: boolean }>(`${DBASE}/${id}`),
  revision: (id: string, rev: number) => api.get<{ rev: number; doc: DraftDoc }>(`${DBASE}/${id}/revisions/${rev}`),
  frame: (body: { sheet: SheetSpec; title: Record<string, string>; revisions: unknown[]; notes: string[] }) => api.post<FrameResp>(`${DBASE}/frame`, body),
  template: (name: string, body: { params: Record<string, number>; scale: [number, number]; units: string; prefix: string }) => api.post<Fragment>(`${DBASE}/templates/${name}`, body),
  assist: (id: string, prompt: string, prefix: string) => api.post<AssistResp>(`${DBASE}/${id}/assist`, { prompt, prefix }),
  file: (id: string, name: string, rev?: number) => `${DBASE}/${id}/files/${name}?download=1${rev ? `&rev=${rev}` : ""}`,
};
