import { useMemo } from "react";
import { useCanvasElements } from "./use-canvas-elements";
import { ExcalidrawBoard } from "./ExcalidrawBoard";
import { useIsMobile } from "../../../hooks/use-is-mobile";
import type { CanvasElement } from "./canvas-api";

export function ExcalidrawCanvas({ projectId, elementId }: { projectId: string; elementId?: string | null }) {
  const elements = useCanvasElements(projectId, elementId);
  const readOnly = useIsMobile();
  const getElement = useMemo(() => {
    const map = new Map<string, CanvasElement>();
    for (const el of elements) map.set(el.id, el);
    return (id: string) => map.get(id);
  }, [elements]);
  return <ExcalidrawBoard elements={elements} projectId={projectId} elementId={elementId} getElement={getElement} readOnly={readOnly} />;
}

export default ExcalidrawCanvas;
