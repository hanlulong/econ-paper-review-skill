import assert from "node:assert/strict";
import test from "node:test";

import { parseStrictJson } from "../lib/strict-json.ts";

test("strict JSON accepts nested unambiguous objects", () => {
  assert.deepEqual(
    parseStrictJson('{"outer":{"name":"value"},"rows":[{"id":1},{"id":2}]}'),
    { outer: { name: "value" }, rows: [{ id: 1 }, { id: 2 }] },
  );
});

test("strict JSON rejects duplicate keys at every object depth", () => {
  assert.throws(
    () => parseStrictJson('{"review_id":"first","review_id":"second"}'),
    /Duplicate JSON key at \$: review_id/,
  );
  assert.throws(
    () => parseStrictJson('{"rows":[{"id":1,"id":2}]}'),
    /Duplicate JSON key at \$\.rows\[0\]: id/,
  );
});

test("escaped keys are compared after JSON decoding", () => {
  assert.throws(
    () => parseStrictJson('{"name":1,"na\\u006de":2}'),
    /Duplicate JSON key at \$: name/,
  );
});
