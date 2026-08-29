// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026-present the Unsloth AI Inc. team. All rights reserved. See /studio/LICENSE.AGPL-3.0

import assert from "node:assert/strict";
import test from "node:test";

import { registerStoreStubResolver } from "./helpers/kit.ts";

registerStoreStubResolver();

const { dedupeSameSourceHubCacheRows } = await import(
  "../src/features/hub/inventory/inventory-dedupe.ts"
);
const { buildCachedInventoryRow, buildLocalInventoryRows } = await import(
  "../src/features/hub/inventory/view-models.ts"
);
const { resolveDownloadedSelection } = await import(
  "../src/features/hub/lib/selection-resolution.ts"
);

test("keeps selection when a resumed download replaces its HF-cache row", () => {
  const repoId = "Org/Model";
  const local = buildLocalInventoryRows([
    {
      id: repoId,
      inventory_id: "hf_cache:safetensors:Org%2FModel",
      load_id: repoId,
      display_name: "Model",
      path: "/isolated-cache/models--Org--Model",
      source: "hf_cache",
      model_id: repoId,
      model_format: "safetensors",
      partial: true,
      partial_resumable: true,
    },
  ])[0];
  const live = {
    ...buildCachedInventoryRow(
      {
        repo_id: repoId,
        inventory_id: "cache:safetensors:Org%2FModel",
        load_id: repoId,
        model_format: "safetensors",
        size_bytes: 50,
        partial: true,
        optimistic: true,
      },
      "safetensors",
    ),
    liveDownload: true,
  };
  assert.ok(local);

  const inventory = dedupeSameSourceHubCacheRows({
    cachedRows: [live],
    localRows: [local],
  });
  assert.deepEqual(inventory.localRows, []);
  assert.deepEqual(
    resolveDownloadedSelection({
      selectedId: local.id,
      cachedRows: inventory.cachedRows,
      localRows: inventory.localRows,
      filteredCachedRows: inventory.cachedRows,
      filteredLocalRows: inventory.localRows,
    }),
    { selectedId: live.id, hiddenByFilters: false },
  );
});
