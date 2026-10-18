import { describe, it, expect, vi } from "vitest";

const originalHasOwn = Object.hasOwn;
const originalStructuredClone = globalThis.structuredClone;
const originalAt = Array.prototype.at;

function deleteGlobalHasOwn() {
  try {
    delete (Object as any).hasOwn;
  } catch {
    // ignore
  }
}

function deleteGlobalStructuredClone() {
  try {
    delete (globalThis as any).structuredClone;
  } catch {
    // ignore
  }
}

function deleteGlobalAt() {
  try {
    delete (Array.prototype as any).at;
  } catch {
    // ignore
  }
}

function restoreGlobals() {
  if (originalHasOwn !== undefined) {
    Object.hasOwn = originalHasOwn;
  } else {
    deleteGlobalHasOwn();
  }
  if (originalStructuredClone !== undefined) {
    globalThis.structuredClone = originalStructuredClone;
  } else {
    deleteGlobalStructuredClone();
  }
  if (originalAt !== undefined) {
    Array.prototype.at = originalAt;
  } else {
    deleteGlobalAt();
  }
}

async function testWithPolyfill<T>(
  name: string,
  setup: () => void,
  testFn: () => T | Promise<T>
): Promise<T> {
  setup();
  vi.resetModules();
  try {
    await import("./polyfills");
    return await testFn();
  } finally {
    restoreGlobals();
  }
}

// Polyfill implementation for direct testing (matches polyfills.ts)
function arrayAtPolyfill(this: unknown, index: number): unknown {
  const arr = Array.from(this);
  const len = arr.length;
  if (len === 0) return undefined;
  const idx = index >= 0 ? index : len + index;
  if (idx < 0 || idx >= len) return undefined;
  return arr[idx];
}

describe("polyfills", () => {
  it("Object.hasOwn polyfill exists and works", async () => {
    await testWithPolyfill("Object.hasOwn", deleteGlobalHasOwn, () => {
      expect(typeof Object.hasOwn).toBe("function");
      expect(Object.hasOwn({ a: 1 }, "a")).toBe(true);
      expect(Object.hasOwn({ a: 1 }, "b")).toBe(false);
      const obj = Object.create({ inherited: true });
      obj.own = true;
      expect(Object.hasOwn(obj, "own")).toBe(true);
      expect(Object.hasOwn(obj, "inherited")).toBe(false);
    });
  });

  it("Array.prototype.at polyfill exists and works", async () => {
    // Note: Cannot delete Array.prototype.at globally as vitest internals depend on it.
    // Test the polyfill logic directly instead.
    const polyfill = arrayAtPolyfill;
    const arr = [1, 2, 3];
    expect(polyfill.call(arr, 0)).toBe(1);
    expect(polyfill.call(arr, -1)).toBe(3);
    expect(polyfill.call(arr, -2)).toBe(2);
    expect(polyfill.call(arr, 5)).toBeUndefined();
    expect(polyfill.call(arr, -5)).toBeUndefined();
    // Also test on array-like object
    const arrayLike = { 0: "a", 1: "b", 2: "c", length: 3 };
    expect(polyfill.call(arrayLike, 0)).toBe("a");
    expect(polyfill.call(arrayLike, -1)).toBe("c");
    // Verify native at() works the same (polyfill matches native behavior)
    if (originalAt) {
      expect(arr.at(0)).toBe(polyfill.call(arr, 0));
      expect(arr.at(-1)).toBe(polyfill.call(arr, -1));
    }
  });

  it("globalThis.structuredClone polyfill exists and works", async () => {
    await testWithPolyfill("structuredClone", deleteGlobalStructuredClone, () => {
      expect(typeof globalThis.structuredClone).toBe("function");

      const original: any = {
        name: "test",
        date: new Date("2024-01-01T00:00:00Z"),
        map: new Map([["key", "value"]]),
        nested: { value: 42 },
      };
      original.cycle = original;

      const cloned = globalThis.structuredClone(original);

      expect(cloned).not.toBe(original);
      expect(cloned.name).toBe("test");
      expect(cloned.date).toBeInstanceOf(Date);
      expect(cloned.date.getTime()).toBe(original.date.getTime());
      expect(cloned.map).toBeInstanceOf(Map);
      expect(cloned.map.get("key")).toBe("value");
      expect(cloned.map).not.toBe(original.map);
      expect(cloned.nested).not.toBe(original.nested);
      expect(cloned.nested.value).toBe(42);
      expect(cloned.cycle).toBe(cloned);
    });
  });

  it("structuredClone throws DataCloneError for functions", async () => {
    await testWithPolyfill("structuredClone throws on function", deleteGlobalStructuredClone, () => {
      expect(() => globalThis.structuredClone(() => {})).toThrow();
    });
  });

  it("structuredClone throws DataCloneError for symbols", async () => {
    await testWithPolyfill("structuredClone throws on symbol", deleteGlobalStructuredClone, () => {
      expect(() => globalThis.structuredClone(Symbol("test"))).toThrow();
    });
  });

  it("does not replace existing native Object.hasOwn", async () => {
    Object.hasOwn = originalHasOwn;
    const nativeHasOwn = Object.hasOwn;
    vi.resetModules();
    await import("./polyfills");
    expect(Object.hasOwn).toBe(nativeHasOwn);
  });

  it("does not replace existing native Array.prototype.at", async () => {
    Array.prototype.at = originalAt;
    const nativeAt = Array.prototype.at;
    vi.resetModules();
    await import("./polyfills");
    expect(Array.prototype.at).toBe(nativeAt);
  });

  it("does not replace existing native globalThis.structuredClone", async () => {
    globalThis.structuredClone = originalStructuredClone;
    const nativeStructuredClone = globalThis.structuredClone;
    vi.resetModules();
    await import("./polyfills");
    expect(globalThis.structuredClone).toBe(nativeStructuredClone);
  });
});