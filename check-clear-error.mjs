import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from '../studio/frontend/node_modules/typescript/lib/typescript.js';
const root = 'studio/frontend/src/';
function extract(file, names) {
  const source = readFileSync(root + file, 'utf8');
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found = [];
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && names.includes(node.name?.getText(tree))) {
      found.push(node.getText(tree).replace(/^export /, ''));
    } else if (ts.isVariableDeclaration(node) && names.includes(node.name.getText(tree))) {
      found.push(`const ${node.getText(tree)};`);
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  assert.equal(found.length, names.length);
  return found.join('\n');
}
const source = [
  extract('lib/format-fastapi-error.ts', ['formatFastApiDetail','formatErrorBody','formatApiErrorBody','readFastApiError','MAX_ERROR_BODY_DEPTH']),
  extract('features/audio/api.ts', ['parseJson','deleteTranscript']),
  extract('features/audio/transcript-gallery.tsx', ['mutate']),
  'return () => mutate(() => deleteTranscript(), null);',
].join('\n');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } });
for (const status of [500, 503]) {
  const errors = [];
  const calls = [];
  const scope = {
    authFetch: async (url, options) => {
      assert.equal(url, '/api/inference/audio/transcripts');
      assert.equal(options.method, 'DELETE');
      return new Response('Internal Server Error', {status});
    },
    currentIdRef: {current:'saved-transcript'},
    onDelete: () => calls.push('delete'),
    refresh: async () => calls.push('refresh'),
    toast: {error: message => errors.push(message)},
  };
  const clear = new Function(...Object.keys(scope), outputText)(...Object.values(scope));
  await clear();
  assert.deepEqual(calls, []);
  assert.deepEqual(errors, [`Request failed (${status})`]);
  console.log(`PASS ${status}: error displayed; selected transcript and history retained`);
}
