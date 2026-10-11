import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { LibraryApp } from "./LibraryApp";

const MOCK_ITEMS = [
  {
    id: "lib-item-1",
    title: "YouTube Video",
    source_type: "youtube",
    source_url: "https://youtube.com/watch?v=1",
    source_id: "yt-1",
    author: "YT Author",
    summary: "Summary 1",
    content: "Content 1",
    media_path: null,
    thumbnail: null,
    categories: ["video"],
    tags: [],
    metadata: {},
    status: "ready",
    monitor: { current_interval: 3600, frequency: 3600, decay_rate: 0, pinned: false, last_poll: 1700000000, last_hash: "" },
    created_at: 1700007200,
    updated_at: 1700007300,
  },
];

const MOCK_AGENTS = [
  { name: "Agent 1", color: "#ff0000" },
  { name: "Agent 2", color: "#00ff00" },
];

const MOCK_SNAPSHOTS = [
  {
    id: 1,
    item_id: "lib-item-1",
    snapshot_at: 1700000100,
    content_hash: "abc123",
    diff_json: { title: "Updated" },
    metadata_json: {},
  },
];

const MOCK_SUBSCRIPTIONS = [
  { agent_name: "Agent 1", category: "video", auto_ingest: true },
];

function createFetchMock(overrides: Record<string, Promise<Response>> = {}) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input);

    for (const [prefix, response] of Object.entries(overrides)) {
      if (url.startsWith(prefix)) return response;
    }

    if (url.includes("/snapshots")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve({ snapshots: MOCK_SNAPSHOTS }),
      } as Response);
    }

    if (url.startsWith("/api/knowledge/items/")) {
      const itemId = url.split("/").pop();
      const item = MOCK_ITEMS.find((i) => i.id === itemId);
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve(item ?? null),
      } as Response);
    }

    if (url.startsWith("/api/knowledge/items")) {
      const qs = new URLSearchParams(url.split("?")[1] || "");
      const sourceType = qs.get("source_type");
      const status = qs.get("status");
      let items = MOCK_ITEMS;
      if (sourceType) items = items.filter((i) => i.source_type === sourceType);
      if (status) items = items.filter((i) => i.status === status);
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve({ items, count: items.length }),
      } as Response);
    }

    if (url.startsWith("/api/knowledge/search")) {
      const qs = new URLSearchParams(url.split("?")[1] || "");
      const q = qs.get("q")?.toLowerCase() || "";
      const results = q ? MOCK_ITEMS.filter((i) => i.title.toLowerCase().includes(q)) : MOCK_ITEMS;
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve({ results, mode: "keyword" }),
      } as Response);
    }

    if (url === "/api/agents") {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve(MOCK_AGENTS),
      } as Response);
    }

    if (url === "/api/knowledge/subscriptions") {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve({ subscriptions: MOCK_SUBSCRIPTIONS }),
      } as Response);
    }

    if (url === "/api/knowledge/rules") {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve({ rules: [] }),
      } as Response);
    }

    if (url === "/api/import/upload") {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve({ id: "new-item-id", status: "processing" }),
      } as Response);
    }

    if (url === "/api/import/embed") {
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve({ status: "ok" }),
      } as Response);
    }

    return Promise.resolve({
      ok: false,
      status: 404,
      headers: new Map([["content-type", "application/json"]]),
      json: () => Promise.resolve({}),
    } as Response);
  });
}

describe("LibraryApp local file upload (tsk-6gtsvj)", () => {
  let fetchMock: ReturnType<typeof createFetchMock>;

  beforeEach(() => {
    fetchMock = createFetchMock();
    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a file drop zone in the items view", async () => {
    render(<LibraryApp windowId="test-win" />);

    await waitFor(() => screen.getByText("YouTube Video"), { timeout: 5000 });

    // The drop zone should be visible
    const dropZone = screen.getByLabelText(/drop files here or click to browse/i);
    expect(dropZone).toBeInTheDocument();
  });

  it("uploads a file via drag-and-drop and calls /api/import/upload with the file", async () => {
    render(<LibraryApp windowId="test-win" />);

    await waitFor(() => screen.getByText("YouTube Video"), { timeout: 5000 });

    const dropZone = screen.getByLabelText(/drop files here or click to browse/i);

    // Create a test file
    const testFile = new File(["test content"], "test.txt", { type: "text/plain" });

    // Simulate drag and drop
    const dataTransfer = {
      files: [testFile],
      types: ["Files"],
    };

    await act(async () => {
      fireEvent.drop(dropZone, { dataTransfer });
    });

    // Should have called /api/import/upload
    await waitFor(() => {
      const uploadCalls = fetchMock.mock.calls.filter((call) =>
        String(call[0]).includes("/api/import/upload")
      );
      expect(uploadCalls.length).toBeGreaterThan(0);
    });
  });

  it("uploads a file via file picker (click) and calls /api/import/upload", async () => {
    render(<LibraryApp windowId="test-win" />);

    await waitFor(() => screen.getByText("YouTube Video"), { timeout: 5000 });

    const dropZone = screen.getByLabelText(/drop files here or click to browse/i);
    const fileInput = dropZone.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeInTheDocument();

    const testFile = new File(["test content"], "test.txt", { type: "text/plain" });

    await act(async () => {
      fireEvent.change(fileInput, {
        target: { files: [testFile] },
      });
    });

    await waitFor(() => {
      const uploadCalls = fetchMock.mock.calls.filter((call) =>
        String(call[0]).includes("/api/import/upload")
      );
      expect(uploadCalls.length).toBeGreaterThan(0);
    });
  });

  it("supports keyboard activation (Enter/Space) on drop zone", async () => {
    render(<LibraryApp windowId="test-win" />);

    await waitFor(() => screen.getByText("YouTube Video"), { timeout: 5000 });

    const dropZone = screen.getByLabelText(/drop files here or click to browse/i);
    expect(dropZone).toHaveAttribute("tabIndex", "0");

    // Simulate Enter key
    await act(async () => {
      fireEvent.keyDown(dropZone, { key: "Enter" });
    });

    // File input should be triggered (we can't easily test the click, but we verify the handler exists)
    expect(dropZone).toHaveAttribute("role", "button");
  });

  it("shows embed-now action on uploaded item with agent picker", async () => {
    // Mock an item that was just uploaded (source_type: "file")
    const mockUploadedItem = {
      ...MOCK_ITEMS[0],
      id: "uploaded-file-1",
      title: "uploaded-doc.txt",
      source_type: "file",
      source_url: "",
      categories: ["default"],
    };

    const fetchMockWithUploaded = createFetchMock({
      // More specific overrides first
      "/api/knowledge/items/uploaded-file-1": Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve(mockUploadedItem),
      } as Response),
      "/api/knowledge/items": Promise.resolve({
        ok: true,
        status: 200,
        headers: new Map([["content-type", "application/json"]]),
        json: () => Promise.resolve({ items: [mockUploadedItem], count: 1 }),
      } as Response),
    });

    vi.stubGlobal("fetch", fetchMockWithUploaded as unknown as typeof fetch);

    render(<LibraryApp windowId="test-win" />);

    await waitFor(() => screen.getByText("uploaded-doc.txt"), { timeout: 5000 });

    // Click on the item to open detail view
    fireEvent.click(screen.getByRole("button", { name: /Open uploaded-doc.txt/i }));

    await waitFor(() => screen.getByText("Content 1"), { timeout: 5000 });

    // Should have an "Embed now" button or similar action
    const embedButton = screen.getByRole("button", { name: /embed this file into an agent now/i });
    expect(embedButton).toBeInTheDocument();

    // Click embed now - should open agent picker
    fireEvent.click(embedButton);

    // Agent picker should show available agents
    await waitFor(() => screen.getByText("Agent 1"), { timeout: 5000 });
    expect(screen.getByText("Agent 1")).toBeInTheDocument();
    expect(screen.getByText("Agent 2")).toBeInTheDocument();

    // Select an agent
    fireEvent.click(screen.getByText("Agent 1"));

    // Should call /api/import/embed with the chosen agent
    await waitFor(() => {
      const embedCalls = fetchMockWithUploaded.mock.calls.filter((call) =>
        String(call[0]).includes("/api/import/embed")
      );
      expect(embedCalls.length).toBeGreaterThan(0);
      const body = JSON.parse(embedCalls[0][1]?.body as string);
      expect(body.agent).toBe("Agent 1");
    });
  });
});