import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor, act } from "@testing-library/react";

// Hoisted so the vi.mock factories below can close over them.
const { convertSpy, parseSpy } = vi.hoisted(() => ({
  convertSpy: vi.fn((els: unknown[]) => els),
  parseSpy: vi.fn(async (_src: string) => ({ elements: [] as unknown[], files: {} })),
}));

// Mock excalidraw-sync with a spy object we can assert against.
const { markRemoteSpy, onLocalChangeSpy, disposeSpy, createSceneSyncSpy } = vi.hoisted(() => ({
  markRemoteSpy: vi.fn(),
  onLocalChangeSpy: vi.fn(async () => {}),
  disposeSpy: vi.fn(),
  createSceneSyncSpy: vi.fn(() => ({
    markRemote: markRemoteSpy,
    onLocalChange: onLocalChangeSpy,
    dispose: disposeSpy,
    shouldApplyRemote: vi.fn(() => true),
    shouldApplyRemoteDelete: vi.fn(() => true),
    flush: vi.fn(async () => {}),
  })),
}));

// Excalidraw is a heavy canvas/worker component jsdom cannot run. Mock it so the
// board's mapping + wiring can be asserted: convertToExcalidrawElements passes
// the skeletons through so we can count them, and Excalidraw records the props
// it was handed.
const mockApi = {
  updateScene: vi.fn(),
  scrollToContent: vi.fn(),
};
vi.mock("@excalidraw/excalidraw", () => ({
  convertToExcalidrawElements: convertSpy,
  Excalidraw: ({
    initialData,
    viewModeEnabled,
    theme,
    onChange,
    excalidrawAPI,
  }: {
    initialData?: { elements?: { id?: string }[] };
    viewModeEnabled?: boolean;
    theme?: string;
    onChange?: (els: unknown[]) => void;
    excalidrawAPI?: (api: typeof mockApi) => void;
  }) => {
    // Expose onChange so tests can call it.
    (window as unknown as { __excalidrawOnChange?: (els: unknown[]) => void }).__excalidrawOnChange = onChange;
    // Call the excalidrawAPI callback so the board gets the imperative API.
    excalidrawAPI?.(mockApi);
    return (
      <div
        data-testid="excalidraw"
        data-count={initialData?.elements?.length ?? 0}
        data-ids={(initialData?.elements ?? []).map((e) => e.id).join(",")}
        data-viewmode={String(!!viewModeEnabled)}
        data-theme={theme}
      />
    );
  },
}));
vi.mock("@excalidraw/excalidraw/index.css", () => ({}));
// Keep the heavy mermaid parser out of jsdom; a test that needs a ready
// diagram overrides the parse result.
vi.mock("@excalidraw/mermaid-to-excalidraw", () => ({
  parseMermaidToExcalidraw: parseSpy,
}));
// Mock excalidraw-sync so we can spy on its calls.
vi.mock("../canvas/excalidraw-sync", () => ({
  createSceneSync: createSceneSyncSpy,
}));

import { ExcalidrawBoard } from "../canvas/ExcalidrawBoard";
import type { CanvasElement } from "../canvas/canvas-api";

function el(over: Partial<CanvasElement>): CanvasElement {
  return {
    id: "e", project_id: "p", kind: "note", author_kind: "user", author_id: "u",
    x: 0, y: 0, w: 80, h: 60, rotation: 0, z_index: 0, payload: {},
    created_at: 0, updated_at: 0, deleted_at: null, ...over,
  };
}

function skeletonIds(call: unknown[]): string[] {
  return (call[0] as { id: string }[]).map((s) => s.id);
}

describe("ExcalidrawBoard", () => {
  beforeEach(() => {
    // mockReset also restores the pass-through after a test overrides it.
    convertSpy.mockReset();
    parseSpy.mockClear();
    markRemoteSpy.mockClear();
    onLocalChangeSpy.mockClear();
    disposeSpy.mockClear();
    createSceneSyncSpy.mockClear();
    mockApi.updateScene.mockClear();
    mockApi.scrollToContent.mockClear();
    // Reset the exposed onChange.
    (window as unknown as { __excalidrawOnChange?: (els: unknown[]) => void }).__excalidrawOnChange = undefined;
  });

  it("maps non-deleted elements into the scene and renders read-only", () => {
    const { getByTestId } = render(
      <ExcalidrawBoard
        theme="dark"
        elements={[
          el({ id: "n1", kind: "note", payload: { text: "a" } }),
          el({ id: "t1", kind: "text", payload: { text: "idea" } }),
          el({ id: "gone", deleted_at: 1 }),
        ]}
      />,
    );
    const ex = getByTestId("excalidraw");
    expect(ex.getAttribute("data-count")).toBe("2");
    expect(ex.getAttribute("data-viewmode")).toBe("true");
    expect(ex.getAttribute("data-theme")).toBe("dark");
  });

  it("defaults to the light theme", () => {
    const { getByTestId } = render(<ExcalidrawBoard elements={[el({})]} />);
    expect(getByTestId("excalidraw").getAttribute("data-theme")).toBe("light");
  });

  it("renders an empty scene without crashing", () => {
    const { getByTestId } = render(<ExcalidrawBoard elements={[]} />);
    expect(getByTestId("excalidraw").getAttribute("data-count")).toBe("0");
  });

  it("mindmap_edge between two notes is converted in the same batch", () => {
    // An arrow binds start/end by the target's id, and the converter can only
    // resolve a binding to an element passed in the SAME call.
    const rows = [
      el({ id: "n1", kind: "note", z_index: 0, payload: { text: "a" } }),
      el({ id: "n2", kind: "note", z_index: 1, payload: { text: "b" } }),
      el({ id: "e1", kind: "mindmap_edge", z_index: 2, payload: { from: "n1", to: "n2" } }),
    ];
    const { rerender, getByTestId } = render(<ExcalidrawBoard elements={rows} />);
    // Count the conversions for one scene build: a fresh elements array
    // recomputes the scene exactly once.
    convertSpy.mockClear();
    rerender(<ExcalidrawBoard elements={[...rows]} />);
    expect(convertSpy).toHaveBeenCalledTimes(1);
    expect(skeletonIds(convertSpy.mock.calls[0])).toEqual(["n1", "n2", "e1"]);
    expect(getByTestId("excalidraw").getAttribute("data-ids")).toBe("n1,n2,e1");
  });

  it("a ready diagram keeps its z_index position", async () => {
    parseSpy.mockResolvedValueOnce({
      elements: [{ id: "d1", type: "rectangle", x: 0, y: 0 }],
      files: {},
    });
    const { getByTestId } = render(
      <ExcalidrawBoard
        elements={[
          el({ id: "top", kind: "note", z_index: 2, payload: { text: "top" } }),
          el({ id: "m1", kind: "mermaid", z_index: 1, payload: { source: "graph TD; A-->B" } }),
          el({ id: "bottom", kind: "note", z_index: 0, payload: { text: "bottom" } }),
        ]}
      />,
    );
    await waitFor(() =>
      expect(getByTestId("excalidraw").getAttribute("data-ids")).toBe("bottom,d1,top"),
    );
    // The ready diagram is spliced in after conversion: the last scene build
    // converted only the two notes, together, in one call.
    const last = convertSpy.mock.calls[convertSpy.mock.calls.length - 1];
    expect(skeletonIds(last)).toEqual(["bottom", "top"]);
  });

  it("a bound label text follows its container whatever the converter's order", () => {
    // A labelled skeleton converts to a container plus a text element that
    // carries no customData, only containerId. Emit n2's text BEFORE its
    // container: grouping must not depend on the converter's output order.
    convertSpy.mockImplementation((skeletons: unknown[]) =>
      (skeletons as { id: string; label?: { text: string } }[]).flatMap((s) => {
        const text = { id: `t-${s.id}`, type: "text", containerId: s.id, text: s.label?.text };
        return s.id === "n2" ? [text, s] : [s, text];
      }),
    );
    const { getByTestId } = render(
      <ExcalidrawBoard
        elements={[
          el({ id: "n1", kind: "note", z_index: 1, payload: { text: "a" } }),
          el({ id: "n2", kind: "note", z_index: 0, payload: { text: "b" } }),
        ]}
      />,
    );
    expect(getByTestId("excalidraw").getAttribute("data-ids")).toBe("t-n2,n2,n1,t-n1");
  });

  it("with projectId the board is editable and onChange reaches the sync", () => {
    const getElement = vi.fn((id: string) => ({ id, kind: "note" } as CanvasElement));
    const { getByTestId } = render(
      <ExcalidrawBoard
        projectId="prj-1"
        elements={[el({ id: "n1" })]}
        getElement={getElement}
      />,
    );
    // Board should be editable (viewModeEnabled = false).
    expect(getByTestId("excalidraw").getAttribute("data-viewmode")).toBe("false");
    // Sync should have been created once.
    expect(createSceneSyncSpy).toHaveBeenCalledTimes(1);
    expect(createSceneSyncSpy).toHaveBeenCalledWith(
      expect.objectContaining({ projectId: "prj-1", elementId: null, getElement }),
    );
    // Call the exposed onChange (simulating Excalidraw firing onChange).
    const onChange = (window as unknown as { __excalidrawOnChange?: (els: unknown[]) => void }).__excalidrawOnChange;
    expect(onChange).toBeDefined();
    act(() => { onChange?.([{ id: "n1", type: "rectangle" }]); });
    // onLocalChange should have been called with the elements.
    expect(onLocalChangeSpy).toHaveBeenCalledTimes(1);
    expect(onLocalChangeSpy).toHaveBeenCalledWith([{ id: "n1", type: "rectangle" }]);
  });

  it("updateScene is followed by markRemote", async () => {
    const getElement = vi.fn((id: string) => ({ id, kind: "note" } as CanvasElement));
    const { rerender, getByTestId } = render(
      <ExcalidrawBoard
        projectId="prj-1"
        elements={[el({ id: "n1" })]}
        getElement={getElement}
      />,
    );
    // Wait for the effect to run and call markRemote.
    await waitFor(() => expect(markRemoteSpy).toHaveBeenCalledTimes(1));
    const firstCall = markRemoteSpy.mock.calls[0][0];
    expect(Array.isArray(firstCall)).toBe(true);
    // Re-render with new elements (simulates sceneElements change).
    markRemoteSpy.mockClear();
    rerender(
      <ExcalidrawBoard
        projectId="prj-1"
        elements={[el({ id: "n1" }), el({ id: "n2" })]}
        getElement={getElement}
      />,
    );
    // markRemote should be called again with the new scene.
    await waitFor(() => expect(markRemoteSpy).toHaveBeenCalledTimes(1));
    const secondCall = markRemoteSpy.mock.calls[0][0];
    expect(Array.isArray(secondCall)).toBe(true);
  });

  it("without projectId the board stays view-only", () => {
    const { getByTestId } = render(
      <ExcalidrawBoard elements={[el({ id: "n1" })]} />,
    );
    // Board should be view-only (viewModeEnabled = true).
    expect(getByTestId("excalidraw").getAttribute("data-viewmode")).toBe("true");
    // Sync should NOT have been created.
    expect(createSceneSyncSpy).not.toHaveBeenCalled();
  });

  it("readOnly=true forces view-only even with projectId", () => {
    const getElement = vi.fn((id: string) => ({ id, kind: "note" } as CanvasElement));
    const { getByTestId } = render(
      <ExcalidrawBoard
        projectId="prj-1"
        readOnly={true}
        elements={[el({ id: "n1" })]}
        getElement={getElement}
      />,
    );
    // Board should be view-only.
    expect(getByTestId("excalidraw").getAttribute("data-viewmode")).toBe("true");
    // Sync should NOT have been created.
    expect(createSceneSyncSpy).not.toHaveBeenCalled();
  });

  it("disposes sync on unmount", () => {
    const getElement = vi.fn((id: string) => ({ id, kind: "note" } as CanvasElement));
    const { unmount } = render(
      <ExcalidrawBoard
        projectId="prj-1"
        elements={[el({ id: "n1" })]}
        getElement={getElement}
      />,
    );
    expect(createSceneSyncSpy).toHaveBeenCalledTimes(1);
    unmount();
    expect(disposeSpy).toHaveBeenCalledTimes(1);
  });
});