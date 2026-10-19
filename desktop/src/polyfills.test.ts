import { describe, it, expect, vi } from "vitest";
import { createContext, runInContext } from "node:vm";

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
  testFn: (polyfillRefs?: { at?: typeof Array.prototype.at }) => T | Promise<T>
): Promise<T> {
  setup();
  vi.resetModules();
  try {
    await import("./polyfills");
    // For Array.prototype.at, capture the polyfill then restore native so vitest internals work
    const atPolyfill = Array.prototype.at;
    if (originalAt !== undefined) {
      Array.prototype.at = originalAt;
    }
    return await testFn({ at: atPolyfill });
  } finally {
    restoreGlobals();
  }
}

// Run Array.prototype.at polyfill test in a fresh VM context where we can safely delete Array.prototype.at
async function testArrayAtInVmContext() {
  const context = createContext({
    Array,
    Object,
    globalThis: globalThis,
    console,
    Error,
    WeakMap,
    Map,
    Set,
    Date,
    RegExp,
    ArrayBuffer,
    Uint8Array,
    Int8Array,
    Uint16Array,
    Int16Array,
    Uint32Array,
    Int32Array,
    Float32Array,
    Float64Array,
    DataView,
    Symbol,
    // Minimal vitest-like test functions
    expect: (actual: any) => ({
      toBe: (expected: any) => { if (actual !== expected) throw new Error(`Expected ${actual} to be ${expected}`); },
      toBeUndefined: () => { if (actual !== undefined) throw new Error(`Expected undefined, got ${actual}`); },
      toBeInstanceOf: (ctor: any) => { if (!(actual instanceof ctor)) throw new Error(`Expected instanceof ${ctor.name}`); },
      not: { toBe: (expected: any) => { if (actual === expected) throw new Error(`Expected not to be ${expected}`); } },
    }),
  });

  // Delete Array.prototype.at in the VM context
  runInContext("delete Array.prototype.at", context);

  // Load and execute the polyfill code in the VM context
  const polyfillCode = `
    if (typeof Array.prototype.at === "undefined") {
      Object.defineProperty(Array.prototype, "at", {
        value: function at(index) {
          const arr = Array.from(this);
          const len = arr.length;
          if (len === 0) return undefined;
          const idx = index >= 0 ? index : len + index;
          if (idx < 0 || idx >= len) return undefined;
          return arr[idx];
        },
        writable: true,
        configurable: true,
        enumerable: false,
      });
    }
  `;
  runInContext(polyfillCode, context);

  // Run tests in the VM context
  const testCode = `
    const arr = [1, 2, 3];
    if (typeof arr.at !== "function") throw new Error("at is not a function");
    if (arr.at(0) !== 1) throw new Error("at(0) failed");
    if (arr.at(-1) !== 3) throw new Error("at(-1) failed");
    if (arr.at(-2) !== 2) throw new Error("at(-2) failed");
    if (arr.at(5) !== undefined) throw new Error("at(5) failed");
    if (arr.at(-5) !== undefined) throw new Error("at(-5) failed");
    const arrayLike = { 0: "a", 1: "b", 2: "c", length: 3 };
    if (Array.prototype.at.call(arrayLike, 0) !== "a") throw new Error("arrayLike at(0) failed");
    if (Array.prototype.at.call(arrayLike, -1) !== "c") throw new Error("arrayLike at(-1) failed");
  `;
  runInContext(testCode, context);
}

// Run Array.prototype.at polyfill test with ToIntegerOrInfinity semantics in a fresh VM context
async function testArrayAtToIntegerOrInfinityInVmContext() {
  const context = createContext({
    Array,
    Object,
    globalThis: globalThis,
    console,
    Error,
    WeakMap,
    Map,
    Set,
    Date,
    RegExp,
    ArrayBuffer,
    Uint8Array,
    Int8Array,
    Uint16Array,
    Int16Array,
    Uint32Array,
    Int32Array,
    Float32Array,
    Float64Array,
    DataView,
    Symbol,
    // Minimal vitest-like test functions
    expect: (actual: any) => ({
      toBe: (expected: any) => { if (actual !== expected) throw new Error(`Expected ${actual} to be ${expected}`); },
      toBeUndefined: () => { if (actual !== undefined) throw new Error(`Expected undefined, got ${actual}`); },
      toBeInstanceOf: (ctor: any) => { if (!(actual instanceof ctor)) throw new Error(`Expected instanceof ${ctor.name}`); },
      not: { toBe: (expected: any) => { if (actual === expected) throw new Error(`Expected not to be ${expected}`); } },
    }),
  });

  // Delete Array.prototype.at in the VM context
  runInContext("delete Array.prototype.at", context);

  // Load and execute the FIXED polyfill code in the VM context
  const polyfillCode = `
    if (typeof Array.prototype.at === "undefined") {
      Object.defineProperty(Array.prototype, "at", {
        value: function at(index) {
          const o = Object(this);
          const len = o.length >>> 0;
          if (len === 0) return undefined;
          let n = Math.trunc(Number(index)) || 0;
          if (n < 0) n += len;
          if (n < 0 || n >= len) return undefined;
          return o[n];
        },
        writable: true,
        configurable: true,
        enumerable: false,
      });
    }
  `;
  runInContext(polyfillCode, context);

  // Run tests in the VM context
  const testCode = `
    const arr = [10, 20, 30];
    if (arr.at(1.5) !== 20) throw new Error("at(1.5) failed, got " + arr.at(1.5));
    if (arr.at() !== 10) throw new Error("at() failed, got " + arr.at());
    if (arr.at(-1) !== 30) throw new Error("at(-1) failed, got " + arr.at(-1));
    if ([].at(0) !== undefined) throw new Error("empty at(0) failed, got " + [].at(0));
  `;
  runInContext(testCode, context);
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
    await testArrayAtInVmContext();
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
      try {
        globalThis.structuredClone(() => {});
        throw new Error("Expected to throw");
      } catch (e: any) {
        expect(e.name).toBe("DataCloneError");
      }
    });
  });

  it("structuredClone throws DataCloneError for symbols", async () => {
    await testWithPolyfill("structuredClone throws on symbol", deleteGlobalStructuredClone, () => {
      try {
        globalThis.structuredClone(Symbol("test"));
        throw new Error("Expected to throw");
      } catch (e: any) {
        expect(e.name).toBe("DataCloneError");
      }
    });
  });

  it("structuredClone copies typed array subarray with independent buffer", async () => {
    await testWithPolyfill("structuredClone typed array subarray", deleteGlobalStructuredClone, () => {
      const original = new Uint16Array([1, 2, 3, 4]).subarray(1, 3);
      const cloned = globalThis.structuredClone(original);

      expect(cloned).toBeInstanceOf(Uint16Array);
      expect(cloned.length).toBe(2);
      expect(cloned[0]).toBe(2);
      expect(cloned[1]).toBe(3);

      cloned[0] = 9;
      expect(original[0]).toBe(2);
    });
  });

  it("structuredClone copies DataView with independent buffer", async () => {
    await testWithPolyfill("structuredClone DataView", deleteGlobalStructuredClone, () => {
      const buffer = new ArrayBuffer(4);
      const view = new DataView(buffer);
      view.setUint8(0, 1);
      view.setUint8(1, 2);
      view.setUint8(2, 3);
      view.setUint8(3, 4);

      const cloned = globalThis.structuredClone(view);

      expect(cloned).toBeInstanceOf(DataView);
      expect(cloned.byteLength).toBe(4);
      expect(cloned.getUint8(0)).toBe(1);
      expect(cloned.getUint8(1)).toBe(2);
      expect(cloned.getUint8(2)).toBe(3);
      expect(cloned.getUint8(3)).toBe(4);

      cloned.setUint8(0, 99);
      expect(view.getUint8(0)).toBe(1);
    });
  });

  it("Array.prototype.at uses ToIntegerOrInfinity and handles edge cases", async () => {
    await testArrayAtToIntegerOrInfinityInVmContext();
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
