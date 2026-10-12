import "./excalidraw-assets";
import { useMemo, useState, useEffect, useRef } from "react";
import type { ComponentProps } from "react";
import { Excalidraw, convertToExcalidrawElements, CaptureUpdateAction } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import { CanvasElement, canvasApi } from "./canvas-api";
import { elementToSkeleton } from "./element-to-excalidraw";
import { mermaidToExcalidraw, type ExcalidrawElements } from "./mermaid-to-elements";
import { createSceneSync, type SyncSceneElement } from "./excalidraw-sync";
import { isPlaceholder } from "./tldraw-to-excalidraw";

// Read-only Excalidraw view over the canonical CanvasElement scene (tldraw ->
// Excalidraw migration). Most kinds map synchronously; mermaid/flowchart kinds
// render their real diagram via mermaid-to-excalidraw, falling back to the
// placeholder rectangle while the (async) conversion runs or if it fails. The
// board is not yet wired into CanvasView; write-back interactions and the swap
// that retires tldraw are later slices.

const DIAGRAM_KINDS = new Set(["mermaid", "flowchart"]);

type ExcalidrawAPI = Parameters<
  NonNullable<ComponentProps<typeof Excalidraw>["excalidrawAPI"]>
>[0];

type SkeletonInput = Parameters<typeof convertToExcalidrawElements>[0];

// Branded types from Excalidraw (not exported from main module, use type assertions)
type FileId = string & { _brand: "FileId" };
type DataURL = string & { _brand: "DataURL" };
type AllowedMimeType = 
  | "image/svg+xml"
  | "image/png"
  | "image/jpeg"
  | "image/gif"
  | "image/webp"
  | "image/bmp"
  | "image/x-icon"
  | "image/avif"
  | "image/jfif"
  | "application/octet-stream";

export interface ExcalidrawBoardProps {
  elements: CanvasElement[];
  theme?: "light" | "dark";
  projectId?: string;
  projectSlug?: string;
  elementId?: string | null;
  getElement?: (id: string) => CanvasElement | undefined;
  readOnly?: boolean;
}

function live(elements: CanvasElement[]): CanvasElement[] {
  return elements
    .filter((el) => el.deleted_at == null)
    .slice()
    .sort((a, b) => (a.z_index || 0) - (b.z_index || 0));
}

function firstNonEmptyString(...vals: unknown[]): string {
  for (const v of vals) {
    if (typeof v === "string" && v.length > 0) return v;
  }
  return "";
}

function a11yLabelFor(el: CanvasElement): string {
  const p = (el.payload ?? {}) as Record<string, unknown>;
  const text = firstNonEmptyString(p.text, p.title, p.label);
  if (text) return `${el.kind}, ${el.author_id}, ${text}`;
  return `${el.kind}, ${el.author_id}`;
}

export function ExcalidrawBoard({
  elements,
  theme = "light",
  projectId,
  projectSlug,
  elementId,
  getElement,
  readOnly,
}: ExcalidrawBoardProps) {
  const [api, setApi] = useState<ExcalidrawAPI | null>(null);
  const [diagrams, setDiagrams] = useState<Record<string, ExcalidrawElements>>({});

  const getElementRef = useRef(getElement);
  getElementRef.current = getElement;
  const stableGetElement = useRef((id: string) => getElementRef.current?.(id)).current;

  const diagramKey = useMemo(
    () =>
      JSON.stringify(
        live(elements)
          .filter((el) => DIAGRAM_KINDS.has(el.kind))
          .map((el) => [el.id, el.x, el.y, (el.payload || {}).source]),
      ),
    [elements],
  );

  useEffect(() => {
    let cancelled = false;
    const diagramEls = live(elements).filter((el) => DIAGRAM_KINDS.has(el.kind));
    if (diagramEls.length === 0) {
      setDiagrams({});
      return;
    }
    (async () => {
      const converted = await Promise.all(
        diagramEls.map(async (el) => {
          const src = String((el.payload || {}).source ?? "");
          return [el.id, await mermaidToExcalidraw(src, el.x, el.y)] as const;
        }),
      );
      if (!cancelled) setDiagrams(Object.fromEntries(converted));
    })();
    return () => {
      cancelled = true;
    };
  }, [diagramKey]);

  const sceneElements = useMemo(() => {
    const ordered = live(elements);
    const readyDiagram = (el: CanvasElement): ExcalidrawElements | null => {
      const ready = DIAGRAM_KINDS.has(el.kind) ? diagrams[el.id] : undefined;
      return ready && ready.length > 0 ? ready : null;
    };
    const skeletons = ordered
      .filter((el) => !readyDiagram(el))
      .map((el) => elementToSkeleton(el, { rows: elements }));
    const converted =
      skeletons.length > 0 ? convertToExcalidrawElements(skeletons as unknown as SkeletonInput) : [];
    const taosIdOf = (x: ExcalidrawElements[number]): string | undefined => {
      const taosId = (x.customData as { taos_id?: unknown } | undefined)?.taos_id;
      return typeof taosId === "string" ? taosId : undefined;
    };
    const rowOf = new Map<string, string>();
    for (const x of converted) {
      const taosId = taosIdOf(x);
      if (taosId) rowOf.set(x.id, taosId);
    }
    const byRow = new Map<string, ExcalidrawElements[number][]>();
    let lastRow: string | undefined;
    for (const x of converted) {
      const containerId = "containerId" in x ? x.containerId : null;
      const row = taosIdOf(x) ?? (containerId && rowOf.get(containerId)) ?? lastRow;
      if (!row) continue;
      lastRow = row;
      const group = byRow.get(row);
      if (group) group.push(x);
      else byRow.set(row, [x]);
    }
    return { elements: ordered.flatMap((el) => readyDiagram(el) ?? byRow.get(el.id) ?? []), byRow };
  }, [elements, diagrams]);

  const sceneElementsArray = sceneElements.elements;
  const byRow = sceneElements.byRow;

  const sync = useMemo(() => {
    if (!projectId || readOnly) return null;
    return createSceneSync({
      projectId,
      elementId: elementId ?? null,
      api: canvasApi,
      getElement: stableGetElement,
    });
  }, [projectId, elementId, readOnly, stableGetElement]);

  useEffect(() => {
    if (!sync) return;
    return () => { const s = sync; void s.flush().catch(() => {}).finally(() => s.dispose()); };
  }, [sync]);

  const hasFit = useRef(false);
  useEffect(() => {
    if (!api) return;
    api.updateScene({ elements: sceneElementsArray, captureUpdate: CaptureUpdateAction.NEVER });
    if (sync) sync.markRemote(sceneElementsArray as unknown as readonly SyncSceneElement[]);
    if (!hasFit.current && sceneElementsArray.length > 0) {
      api.scrollToContent(sceneElementsArray, { fitToContent: true, animate: false });
      hasFit.current = true;
    }
  }, [api, sceneElementsArray, sync]);

  // Image fetching: track fetched fileIds to avoid refetching on re-render.
  const fetchedFileIds = useRef<Set<string>>(new Set());
  const fileIdToMimeType = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    if (!api || !projectSlug) return;
    const ordered = live(elements);
    const imageRows = ordered.filter((el) => el.kind === "image");
    for (const row of imageRows) {
      const fileId = String((row.payload || {}).file_id ?? "");
      if (!fileId || fetchedFileIds.current.has(fileId)) continue;
      fetchedFileIds.current.add(fileId);
      (async () => {
        try {
          const res = await fetch(`/api/projects/${projectSlug}/files/canvas/${fileId}`);
          if (!res.ok) return;
          const blob = await res.blob();
          const mimeType = (blob.type || "image/png") as AllowedMimeType;
          fileIdToMimeType.current.set(fileId, mimeType);
          const reader = new FileReader();
          reader.onload = () => {
            if (api && reader.result) {
              api.addFiles([{ id: fileId as FileId, dataURL: reader.result as DataURL, mimeType, created: Date.now() }]);
            }
          };
          reader.readAsDataURL(blob);
        } catch {
          // best-effort: ignore fetch/read errors
        }
      })();
    }
  }, [api, projectSlug, elements]);

  const viewModeEnabled = !projectId || !!readOnly;

  const orderedLive = live(elements);
  const a11yItems = orderedLive.map((el) => {
    const readyDiagram = DIAGRAM_KINDS.has(el.kind) ? diagrams[el.id] : undefined;
    const convertedForRow = readyDiagram && readyDiagram.length > 0
      ? readyDiagram
      : byRow.get(el.id);
    const hasPlaceholder = convertedForRow?.some((x) => isPlaceholder(x as any)) ?? false;
    const label = hasPlaceholder
      ? `not convertible, element ${el.id}`
      : a11yLabelFor(el);
    return <li key={el.id}>{label}</li>;
  });

  return (
    <div style={{ position: "absolute", inset: 0 }} data-testid="excalidraw-board">
      <ul className="sr-only" aria-label="Canvas elements" role="list">
        {a11yItems}
      </ul>
      <Excalidraw
        excalidrawAPI={setApi}
        theme={theme}
        viewModeEnabled={viewModeEnabled}
        zenModeEnabled
        UIOptions={{ tools: { image: false } }}
        onChange={sync ? (els) => { void sync.onLocalChange(els as unknown as readonly SyncSceneElement[]); } : undefined}
        initialData={{
          elements: sceneElementsArray,
          appState: {
            viewBackgroundColor: theme === "dark" ? "#0b0f17" : "#ffffff",
          },
        }}
      />
    </div>
  );
}

export default ExcalidrawBoard;