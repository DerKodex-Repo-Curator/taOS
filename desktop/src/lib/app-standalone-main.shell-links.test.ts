import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { TAOS_AGENT_CONFIG_URL } from "./taos-agent-api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const { openUrlInShellMock, fetchMock } = vi.hoisted(() => ({
  openUrlInShellMock: vi.fn(),
  fetchMock: vi.fn(),
}));

vi.mock("@/lib/mobile-shell", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    openUrlInShell: openUrlInShellMock,
  };
});

describe("app-standalone-main shell link routing", () => {
  let configResolve: (value: Response) => void;
  let configPromise: Promise<Response>;

  beforeEach(() => {
    vi.resetModules();
    openUrlInShellMock.mockReset();
    openUrlInShellMock.mockResolvedValue(true);

    configPromise = new Promise((resolve) => {
      configResolve = resolve;
    });

    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === TAOS_AGENT_CONFIG_URL) {
        return configPromise;
      }
      return Promise.reject(new Error(`unexpected fetch ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    document.head.innerHTML = "";
    document.body.innerHTML = '<div id="root"></div>';
    document.title = "";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("awaits device-class prime before routing links: window.open after boot routes through openUrlInShell on mobile", async () => {
    let booted = false;
    const bootPromise = import("../app-standalone-main").then(() => {
      booted = true;
    });

    await Promise.resolve();

    expect(booted).toBe(false);

    configResolve!(jsonResponse({ device_class: "mobile" }));

    await bootPromise;

    window.open("https://example.com/", "_blank");

    expect(openUrlInShellMock).toHaveBeenCalledWith("https://example.com/");
  });
});