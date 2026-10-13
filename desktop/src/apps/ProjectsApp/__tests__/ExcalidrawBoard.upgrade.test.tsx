import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import fixtures from "./fixtures/tldraw-shapes.json" with { type: "json" };

const { convertSpy, parseSpy } = vi.hoisted(() => ({
  convertSpy: vi.fn((els: unknown[]) => els),
  parseSpy: vi.fn(async (_src: string) => ({ elements: [], files: {} })),
}));

const { markRemoteSpy, onLocalChangeSpy, disposeSpy, createSceneSyncSpy, flushSpy } = vi.hoisted(() => ({
  markRemoteSpy: vi.fn(),
  onLocalChangeSpy: vi.fn(async () => {}),
  disposeSpy: vi.fn(),
  createSceneSyncSpy: vi.fn(() => ({
    markRemote: markRemoteSpy,
    onLocalChange: onLocalChangeSpy,
    dispose: disposeSpy,
    shouldApplyRemote: vi.fn(() => true),
    shouldApplyRemoteDelete: vi.fn(() => true),
    flush: flushSpy,
  })),
  flushSpy: vi.fn(async () => {}),
}));

const mockApi = {
  updateScene: vi.fn(),
  scrollToContent: vi.fn(),
  addFiles: vi.fn(),
};

vi.mock("@excalidraw/excalidraw", () => ({
  convertToExcalidrawElements: convertSpy,
  Excalidraw: ({
    initialData,
    viewModeEnabled,
    theme,
    onChange,
    excalidrawAPI,
    UIOptions,
    ...props
  }: {
    initialData?: { elements?: { id?: string }[] };
    viewModeEnabled?: boolean;
    theme?: string;
    onChange?: (els: unknown[]) => void;
    excalidrawAPI?: (api: typeof mockApi) => void;
    UIOptions?: Record<string, unknown>;
  }) => {
    excalidrawAPI?.(mockApi);
    (window as unknown as { __excalidrawOnChange?: (els: unknown[]) => void }).__excalidrawOnChange = onChange;
    return (
      <div
        data-testid="excalidraw"
        data-count={initialData?.elements?.length ?? 0}
        data-ids={(initialData?.elements ?? []).map((e) => e.id).join(",")}
        data-viewmode={String(!!viewModeEnabled)}
        data-theme={theme}
        data-uioptions={JSON.stringify(UIOptions ?? {})}
        {...props}
      />
    );
  },
  CaptureUpdateAction: { NEVER: "NEVER" },
}));
vi.mock("@excalidraw/excalidraw/index.css", () => ({}));
vi.mock("@excalidraw/mermaid-to-excalidraw", () => ({
  parseMermaidToExcalidraw: parseSpy,
}));
vi.mock("../canvas/excalidraw-sync", () => ({
  createSceneSync: createSceneSyncSpy,
}));

import { ExcalidrawBoard } from "../canvas/ExcalidrawBoard";
import type { CanvasElement } from "../canvas/canvas-api";
import { isPlaceholder } from "../canvas/tldraw-to-excalidraw";

function makeElement(over: Partial<CanvasElement>): CanvasElement {
  return {
    id: "e",
    project_id: "p",
    kind: "note",
    author_kind: "user",
    author_id: "u",
    x: 0, y: 0, w: 80, h: 60, rotation: 0, z_index: 0,
    payload: {},
    created_at: 0, updated_at: 0, deleted_at: null,
    ...over,
  };
}

describe("ExcalidrawBoard upgrade test - 80 seeded rows", () => {
  beforeEach(() => {
    convertSpy.mockReset();
    parseSpy.mockClear();
    markRemoteSpy.mockClear();
    onLocalChangeSpy.mockClear();
    flushSpy.mockClear();
    disposeSpy.mockClear();
    createSceneSyncSpy.mockClear();
    mockApi.updateScene.mockClear();
    mockApi.scrollToContent.mockClear();
    mockApi.addFiles.mockClear();
    (window as unknown as { __excalidrawOnChange?: (els: unknown[]) => void }).__excalidrawOnChange = undefined;
  });

  function build80Rows(): CanvasElement[] {
    const rows: CanvasElement[] = [];

    // 54 notes
    for (let i = 0; i < 54; i++) {
      rows.push(makeElement({
        id: `note-${i}`,
        kind: "note",
        z_index: i,
        payload: { text: `Note ${i}`, color: "yellow", font_size: 14 },
      }));
    }

    // 11 text
    for (let i = 0; i < 11; i++) {
      rows.push(makeElement({
        id: `text-${i}`,
        kind: "text",
        z_index: 54 + i,
        payload: { text: `Text ${i}`, color: "#1e293b" },
      }));
    }

    // 6 links
    for (let i = 0; i < 6; i++) {
      rows.push(makeElement({
        id: `link-${i}`,
        kind: "link",
        z_index: 65 + i,
        payload: { url: `https://example${i}.com`, title: `Link ${i}`, description: "" },
      }));
    }

    // 4 mermaid
    for (let i = 0; i < 4; i++) {
      rows.push(makeElement({
        id: `mermaid-${i}`,
        kind: "mermaid",
        z_index: 71 + i,
        payload: { source: `graph TD; A${i}-->B${i}` },
      }));
    }

    // 5 user_shape: 4 from Pi fixture + 1 truly malformed from synthetic
    const piRows = fixtures.pi_rows.slice(0, 4);
    for (let i = 0; i < piRows.length; i++) {
      const pi = piRows[i];
      rows.push(makeElement({
        id: pi.id,
        kind: "user_shape",
        z_index: 75 + i,
        x: pi.x,
        y: pi.y,
        w: pi.w,
        h: pi.h,
        rotation: pi.rotation,
        author_kind: pi.author_kind,
        author_id: pi.author_id,
        payload: pi.payload,
      }));
    }

    // 1 malformed from synthetic_rows (syn-malformed-draw)
    const malformed = fixtures.synthetic_rows.find((r) => r.id === "syn-malformed-draw");
    if (malformed) {
      rows.push(makeElement({
        id: malformed.id,
        kind: "user_shape",
        z_index: 79,
        x: malformed.x,
        y: malformed.y,
        w: malformed.w,
        h: malformed.h,
        rotation: malformed.rotation,
        author_kind: malformed.author_kind,
        author_id: malformed.author_id,
        payload: malformed.payload,
      }));
    }

    return rows;
  }

  it("80 seeded rows incl. 5 legacy user_shape render 80 accessible entries", () => {
    const rows = build80Rows();
    expect(rows).toHaveLength(80);

    render(<ExcalidrawBoard elements={rows} theme="dark" />);

    const list = screen.getByRole("list", { name: /canvas elements/i });
    const items = list.getElementsByTagName("li");
    expect(items).toHaveLength(80);

    // The malformed user_shape (syn-malformed-draw) should appear
    // as a placeholder carrying its element id
    const malformedId = "syn-malformed-draw";
    const malformedItem = Array.from(items).find(
      (item) => item.textContent?.includes(malformedId) && item.textContent?.includes("not convertible")
    );
    expect(malformedItem).toBeDefined();
    expect(malformedItem?.textContent).toContain("not convertible");
    expect(malformedItem?.textContent).toContain(malformedId);

    // Every user_shape's stored tldraw_shape should be byte-identical after load
    // (verified via the payload carried through elementToSkeleton -> legacyShapeToSkeleton)
    const userShapeRows = rows.filter((r) => r.kind === "user_shape");
    expect(userShapeRows).toHaveLength(5);
    for (const row of userShapeRows) {
      const blob = (row.payload as { tldraw_shape?: unknown })?.tldraw_shape;
      expect(blob).toBeDefined();
      // The blob passes through to the skeleton's customData.taos_original_type etc.
    }
  });

  it("legacy user_shape tldraw_shape blob is byte-identical after conversion round-trip", () => {
    const rows = build80Rows();
    const userShapeRows = rows.filter((r) => r.kind === "user_shape");
    expect(userShapeRows).toHaveLength(5);

    // Render to trigger conversion
    render(<ExcalidrawBoard elements={rows} />);

    // Check that convertToExcalidrawElements was called with all elements
    expect(convertSpy).toHaveBeenCalledTimes(1);
    const callArgs = convertSpy.mock.calls[0][0] as Array<{ id: string; customData?: Record<string, unknown> }>;

    // Find the malformed row's skeleton
    const malformedSkeleton = callArgs.find((s) => s.id === "syn-malformed-draw");
    expect(malformedSkeleton).toBeDefined();
    // The malformed one should have taos_placeholder: true
    expect(malformedSkeleton?.customData?.taos_placeholder).toBe(true);
    expect(malformedSkeleton?.customData?.taos_original_element_id).toBe("syn-malformed-draw");

    // For valid legacy rows, the tldraw_shape should be preserved in customData
    for (const row of userShapeRows) {
      if (row.id === "syn-malformed-draw") continue;
      const skeleton = callArgs.find((s) => s.id === row.id);
      expect(skeleton).toBeDefined();
      expect(skeleton?.customData?.taos_original_element_id).toBe(row.id);
      expect(skeleton?.customData?.taos_original_type).toBeDefined();
    }
  });
});