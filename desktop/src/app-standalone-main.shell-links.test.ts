import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const CONFIG_URL = "/api/taos-agent/config";

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
      if (url === CONFIG_URL) {
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
    // Start booting the standalone app (this starts and awaits the prime)
    const bootPromise = import("./app-standalone-main");

    // Give it time to start the prime
    await Promise.resolve();

    // Now resolve the config as mobile
    configResolve!(jsonResponse({ device_class: "mobile" }));

    // Wait for the prime to complete
    await configPromise;
    await Promise.resolve();
    await Promise.resolve();

    // Now await the import (which was waiting for the prime)
    await bootPromise;

    // Fire window.open AFTER the prime resolves and boot completes
    window.open("https://example.com/", "_blank");

    // With the fix (awaiting prime before installShellLinks), this should route through openUrlInShell
    expect(openUrlInShellMock).toHaveBeenCalledWith("https://example.com/");
  });
});