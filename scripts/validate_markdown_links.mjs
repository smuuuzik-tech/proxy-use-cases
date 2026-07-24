import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const markdown = [];
const errors = [];
walk(root);

for (const file of markdown) {
  const content = readFileSync(file, "utf8");
  for (const match of content.matchAll(/!?\[[^\]]*]\(([^)]+)\)/g)) {
    let target = match[1].trim();
    if (!target || target.startsWith("#") ||
        /^(?:https?:|mailto:|tel:)/i.test(target)) continue;
    if (target.startsWith("<") && target.endsWith(">")) {
      target = target.slice(1, -1);
    }
    target = target.split("#", 1)[0].split("?", 1)[0];
    try {
      target = decodeURIComponent(target);
    } catch {
      errors.push(`${relative(root, file)}: invalid URL encoding: ${target}`);
      continue;
    }
    if (!existsSync(resolve(dirname(file), target))) {
      errors.push(`${relative(root, file)}: missing target: ${target}`);
    }
  }
}

if (errors.length) {
  process.stderr.write(`${errors.map((error) => `- ${error}`).join("\n")}\n`);
  process.exit(1);
}
process.stdout.write(`Markdown links OK: ${markdown.length} files.\n`);

function walk(directory) {
  for (const entry of readdirSync(directory)) {
    if (entry === ".git" || entry === "node_modules") continue;
    const path = resolve(directory, entry);
    if (statSync(path).isDirectory()) walk(path);
    else if (path.endsWith(".md")) markdown.push(path);
  }
}
