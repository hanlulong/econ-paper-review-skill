/** Parse JSON without JavaScript's silent last-key-wins ambiguity. */
export function parseStrictJson(text: string): unknown {
  const parsed: unknown = JSON.parse(text);
  let position = 0;

  function whitespace() {
    while (position < text.length && /\s/.test(text[position])) position += 1;
  }

  function stringToken(): string {
    const start = position;
    position += 1;
    while (position < text.length) {
      if (text[position] === "\\") {
        position += 2;
      } else if (text[position] === '"') {
        position += 1;
        return text.slice(start, position);
      } else {
        position += 1;
      }
    }
    throw new SyntaxError("Unterminated JSON string");
  }

  function value(path: string) {
    whitespace();
    const token = text[position];
    if (token === '"') {
      stringToken();
      return;
    }
    if (token === "{") {
      object(path);
      return;
    }
    if (token === "[") {
      array(path);
      return;
    }
    while (position < text.length && !/[\s,}\]]/.test(text[position])) position += 1;
  }

  function object(path: string) {
    position += 1;
    whitespace();
    const keys = new Set<string>();
    if (text[position] === "}") {
      position += 1;
      return;
    }
    while (position < text.length) {
      whitespace();
      const keyToken = stringToken();
      const key = JSON.parse(keyToken) as string;
      if (keys.has(key)) throw new SyntaxError(`Duplicate JSON key at ${path}: ${key}`);
      keys.add(key);
      whitespace();
      if (text[position] !== ":") throw new SyntaxError(`Expected ':' after JSON key at ${path}`);
      position += 1;
      value(`${path}.${key}`);
      whitespace();
      if (text[position] === "}") {
        position += 1;
        return;
      }
      if (text[position] !== ",") throw new SyntaxError(`Expected ',' in JSON object at ${path}`);
      position += 1;
    }
  }

  function array(path: string) {
    position += 1;
    whitespace();
    if (text[position] === "]") {
      position += 1;
      return;
    }
    let index = 0;
    while (position < text.length) {
      value(`${path}[${index}]`);
      whitespace();
      if (text[position] === "]") {
        position += 1;
        return;
      }
      if (text[position] !== ",") throw new SyntaxError(`Expected ',' in JSON array at ${path}`);
      position += 1;
      index += 1;
    }
  }

  value("$");
  whitespace();
  if (position !== text.length) throw new SyntaxError("Unexpected trailing JSON content");
  return parsed;
}
