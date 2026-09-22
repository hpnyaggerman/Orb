// Read step ids from the backend so new steps cannot silently lose their label.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { generationStepLabel } from "../../frontend/generation_status.js";

const pipeline = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "backend", "pipeline");

function backendSteps() {
  const steps = new Set();
  for (const file of readdirSync(pipeline, { recursive: true })) {
    if (!file.endsWith(".py")) continue;
    for (const m of readFileSync(join(pipeline, file), "utf8").matchAll(/"step": "([a-z_]+)"/g)) steps.add(m[1]);
  }
  return [...steps];
}

test("every backend step has its own status text", () => {
  const steps = backendSteps();
  assert.ok(steps.includes("writer"), "the step scan found nothing; did the emission shape change?");
  // `director_start` shares the "director" entry with the scene-direction step.
  const ids = [...new Set([...steps, "director"])];
  const labels = ids.map(generationStepLabel);
  for (const [i, label] of labels.entries()) assert.ok(label, `no status text for ${ids[i]}`);
  assert.equal(new Set(labels).size, labels.length);
});

test("unknown steps have no label", () => {
  assert.equal(generationStepLabel("future_step"), "");
  assert.equal(generationStepLabel("toString"), "");
  assert.equal(generationStepLabel(undefined), "");
});
