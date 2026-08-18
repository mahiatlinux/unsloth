// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import test from "node:test";

import { registerBundlerResolver } from "./helpers/kit.ts";

registerBundlerResolver();

const { getExternalMaxOutputTokens } = await import(
  "../src/features/chat/provider-capabilities.ts"
);

// Reports rather than asserts, so it still prints the resolved ceiling on the branch
// where the fix is reverted and the suite next to it is failing.
const OPENROUTER_IDS = [
  "minimax/minimax-m3",
  "minimax/minimax-m2",
  "deepseek/deepseek-chat",
  "unknownvendor/some-model",
];

test("report the OpenRouter output-token caps this branch resolves", () => {
  for (const modelId of OPENROUTER_IDS) {
    console.log(`CAP ${modelId} ${getExternalMaxOutputTokens("openrouter", modelId)}`);
  }
});
