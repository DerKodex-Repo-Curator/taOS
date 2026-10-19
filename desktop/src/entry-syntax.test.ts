// @vitest-environment node
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const projectRoot = resolve(__dirname, "..");
const { transformSync } = require("esbuild");

const entries = [
  "src/main.tsx",
  "src/app-standalone-main.tsx",
  "src/chat-main.tsx",
];

describe("entry syntax compatibility with Chrome 87", () => {
  for (const entry of entries) {
    const filePath = join(projectRoot, entry);

    it(`${entry} transforms without error for target chrome87`, () => {
      const source = readFileSync(filePath, "utf-8");
      expect(() => {
        transformSync(source, {
          loader: "tsx",
          format: "esm",
          target: "chrome87",
        });
      }).not.toThrow();
    });

    it(`${entry} has ./polyfills as the first import`, () => {
      const source = readFileSync(filePath, "utf-8");
      const lines = source.split("\n");
      const firstImportLine = lines.find((line) => line.trim().startsWith("import "));
      expect(firstImportLine).toBeDefined();
      expect(firstImportLine?.trim()).toBe('import "./polyfills";');
    });
  }
});