import { readFile } from 'node:fs/promises';

function parseValue(raw) {
  const value = raw.trim();
  if (
    value.length >= 2 &&
    ((value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'")))
  ) {
    const unquoted = value.slice(1, -1);
    if (value.startsWith("'")) return unquoted;
    return unquoted.replace(/\\([nrt"\\])/g, (_, escaped) => {
      const replacements = {
        n: '\n',
        r: '\r',
        t: '\t',
        '"': '"',
        '\\': '\\',
      };
      return replacements[escaped];
    });
  }
  return value;
}

export async function loadEnvFileIfPresent(
  filename = '.env',
  env = process.env,
) {
  let content;
  try {
    content = await readFile(filename, 'utf8');
  } catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error;
  }

  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const match = trimmed.match(
      /^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/,
    );
    if (!match) continue;
    const [, name, rawValue] = match;
    if (env[name] === undefined) env[name] = parseValue(rawValue);
  }
  return true;
}
