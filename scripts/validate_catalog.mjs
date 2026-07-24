import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const catalog = JSON.parse(readFileSync(resolve(root, "catalog.json"), "utf8"));
const errors = [];
const ids = new Set();
const paths = new Set();
const contractIds = new Set();
const categories = new Set([
  "quickstart",
  "sdk",
  "tool",
  "lab",
  "use_case",
  "vendor_adapter",
]);

if (catalog.$schema !== "./catalog.schema.json") {
  errors.push("catalog.$schema must point to ./catalog.schema.json");
}
if (!Array.isArray(catalog.solutions) || !catalog.solutions.length) {
  errors.push("catalog.solutions must be a non-empty array");
}
if (!Array.isArray(catalog.contracts) || !catalog.contracts.length) {
  errors.push("catalog.contracts must be a non-empty array");
}

for (const [index, solution] of (catalog.solutions || []).entries()) {
  const prefix = `solutions[${index}]`;
  for (const field of [
    "id",
    "title",
    "title_en",
    "category",
    "status",
    "path",
    "readme",
    "test_command",
    "choose_when",
    "avoid_when",
  ]) {
    if (typeof solution[field] !== "string" || !solution[field].trim()) {
      errors.push(`${prefix}.${field} must be a non-empty string`);
    }
  }
  for (const field of ["runtimes", "capabilities", "keywords"]) {
    if (!Array.isArray(solution[field]) || !solution[field].length) {
      errors.push(`${prefix}.${field} must be a non-empty array`);
    }
  }
  if (!categories.has(solution.category)) {
    errors.push(`${prefix}.category is unsupported`);
  }
  if (!["beta", "stable"].includes(solution.status)) {
    errors.push(`${prefix}.status is unsupported`);
  }
  if (!Number.isInteger(solution.maturity_level) ||
      solution.maturity_level < 1 || solution.maturity_level > 4) {
    errors.push(`${prefix}.maturity_level must be from 1 to 4`);
  }
  if (typeof solution.provider_neutral !== "boolean") {
    errors.push(`${prefix}.provider_neutral must be boolean`);
  }
  if (ids.has(solution.id)) errors.push(`duplicate id: ${solution.id}`);
  if (paths.has(solution.path)) errors.push(`duplicate path: ${solution.path}`);
  ids.add(solution.id);
  paths.add(solution.path);

  for (const [field, expected] of [["path", "directory"], ["readme", "file"]]) {
    const target = resolve(root, solution[field] || "__missing__");
    if (!existsSync(target) ||
        (expected === "directory" ? !statSync(target).isDirectory() : !statSync(target).isFile())) {
      errors.push(`${prefix}.${field} does not resolve to a ${expected}`);
    }
  }
}

for (const [index, contract] of (catalog.contracts || []).entries()) {
  const prefix = `contracts[${index}]`;
  for (const field of ["id", "schema_version", "path"]) {
    if (typeof contract[field] !== "string" || !contract[field].trim()) {
      errors.push(`${prefix}.${field} must be a non-empty string`);
    }
  }
  for (const field of ["applies_to", "fixtures"]) {
    if (!Array.isArray(contract[field]) || !contract[field].length) {
      errors.push(`${prefix}.${field} must be a non-empty array`);
    }
  }
  if (contractIds.has(contract.id)) {
    errors.push(`duplicate contract id: ${contract.id}`);
  }
  contractIds.add(contract.id);

  for (const path of [contract.path, ...(contract.fixtures || [])]) {
    const target = resolve(root, path || "__missing__");
    if (!existsSync(target) || !statSync(target).isFile()) {
      errors.push(`${prefix} path does not resolve to a file: ${path}`);
    }
  }
  for (const solutionId of contract.applies_to || []) {
    if (!ids.has(solutionId)) {
      errors.push(`${prefix}.applies_to references unknown solution: ${solutionId}`);
    }
  }
}

if (errors.length) {
  process.stderr.write(`${errors.map((error) => `- ${error}`).join("\n")}\n`);
  process.exit(1);
}
process.stdout.write(
  `Catalog OK: ${ids.size} solutions, ${contractIds.size} contract.\n`,
);
