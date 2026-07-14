import { lstatSync, readFileSync, readdirSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { TextDecoder } from "node:util";
import { fileURLToPath } from "node:url";

const VIEWER_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const LOCK_PATH = join(VIEWER_ROOT, "package-lock.json");
const KATEX_FONT_LICENSE = join(VIEWER_ROOT, "licenses", "KATEX-FONTS-OFL-1.1.txt");
const LICENSE_OVERRIDES = new Map([
  ["rehype-katex@7.0.1", join(VIEWER_ROOT, "licenses", "remark-math-MIT.txt")],
  ["remark-math@6.0.0", join(VIEWER_ROOT, "licenses", "remark-math-MIT.txt")],
]);
const LICENSE_NAME = /^(?:licen[cs]e|copying|notice|copyright)(?:[._-].*)?$/i;
const UTF8 = new TextDecoder("utf-8", { fatal: true });

function normalizedText(path) {
  const value = UTF8.decode(readFileSync(path)).replace(/\r\n?/g, "\n");
  return value.endsWith("\n") ? value : `${value}\n`;
}

function canonicalJson(value) {
  const canonical = (item) => {
    if (Array.isArray(item)) return item.map(canonical);
    if (item && typeof item === "object") {
      return Object.fromEntries(Object.keys(item).sort().map((key) => [key, canonical(item[key])]));
    }
    return item;
  };
  return `${JSON.stringify(canonical(value))}\n`;
}

function cleanModulePath(moduleId) {
  const value = moduleId.startsWith("\0") ? moduleId.slice(1) : moduleId;
  return value.split("?", 1)[0];
}

function packageRecordForModule(moduleId, lockPackages) {
  const modulePath = cleanModulePath(moduleId);
  if (!isAbsolute(modulePath) || !modulePath.split(/[\\/]/).includes("node_modules")) return null;
  let current = dirname(modulePath);
  for (;;) {
    const descriptorPath = join(current, "package.json");
    try {
      const descriptor = JSON.parse(normalizedText(descriptorPath));
      const relativeRoot = relative(VIEWER_ROOT, current).split(sep).join("/");
      if (!relativeRoot.startsWith("node_modules/") || relativeRoot.split("/").includes("..")) {
        throw new Error(`bundled package resolves outside node_modules: ${moduleId}`);
      }
      const locked = lockPackages[relativeRoot];
      if (
        !descriptor || typeof descriptor !== "object"
        || typeof descriptor.name !== "string" || !descriptor.name
        || typeof descriptor.version !== "string" || !descriptor.version
        || typeof descriptor.license !== "string" || !descriptor.license
        || !locked || locked.version !== descriptor.version
      ) {
        throw new Error(`bundled package is not reproducibly described by package-lock.json: ${relativeRoot}`);
      }
      return {
        declaredLicense: descriptor.license,
        name: descriptor.name,
        relativeRoot,
        root: current,
        version: descriptor.version,
      };
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error(`invalid package descriptor while licensing ${moduleId}: ${error.message}`);
      if (error?.code !== "ENOENT" && !String(error?.message || "").includes("no such file")) throw error;
    }
    const parent = dirname(current);
    if (parent === current) throw new Error(`cannot resolve bundled package metadata: ${moduleId}`);
    current = parent;
  }
}

function safeComponent(value) {
  const safe = value.replace(/^@/, "").replaceAll("/", "__").replace(/[^A-Za-z0-9._-]/g, "_");
  if (!safe || safe === "." || safe === "..") throw new Error(`unsafe license path component: ${value}`);
  return safe;
}

function packageLicenses(record) {
  const names = readdirSync(record.root)
    .filter((name) => LICENSE_NAME.test(name))
    .sort((left, right) => left.localeCompare(right, "en"));
  if (!names.length) {
    const override = LICENSE_OVERRIDES.get(`${record.name}@${record.version}`);
    return override ? [{ name: "LICENSE", source: normalizedText(override) }] : [];
  }
  const folded = new Set();
  return names.map((name) => {
    const source = join(record.root, name);
    const stat = lstatSync(source);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`unsafe package license file: ${source}`);
    const safeName = safeComponent(name);
    const foldedName = safeName.toLocaleLowerCase("en");
    if (folded.has(foldedName)) throw new Error(`case-colliding package license files: ${record.name}`);
    folded.add(foldedName);
    return { name: safeName, source: normalizedText(source) };
  });
}

function emitRuntimeNotices(context, bundle) {
  const lock = JSON.parse(normalizedText(LOCK_PATH));
  if (!lock || typeof lock !== "object" || !lock.packages || typeof lock.packages !== "object") {
    throw new Error("package-lock.json lacks the packages inventory required for release licensing");
  }
  const packages = new Map();
  for (const output of Object.values(bundle)) {
    if (output.type !== "chunk") continue;
    for (const moduleId of Object.keys(output.modules)) {
      const record = packageRecordForModule(moduleId, lock.packages);
      if (!record) continue;
      const key = `${record.name}\u0000${record.version}`;
      const previous = packages.get(key);
      if (previous && previous.relativeRoot !== record.relativeRoot) {
        throw new Error(`bundle contains ambiguous copies of ${record.name}@${record.version}`);
      }
      packages.set(key, record);
    }
  }
  const rows = [...packages.values()].sort((left, right) => (
    left.name.localeCompare(right.name, "en") || left.version.localeCompare(right.version, "en")
  ));
  if (!rows.length) throw new Error("static client bundle contains no attributable runtime packages");

  const manifestPackages = [];
  const seenDirectories = new Set();
  const missingLicenses = [];
  for (const record of rows) {
    const directory = `${safeComponent(record.name)}-${safeComponent(record.version)}`;
    const folded = directory.toLocaleLowerCase("en");
    if (seenDirectories.has(folded)) throw new Error(`case-colliding bundled package license directory: ${directory}`);
    seenDirectories.add(folded);
    const packageLicenseFiles = packageLicenses(record);
    if (!packageLicenseFiles.length) missingLicenses.push(`${record.name}@${record.version}`);
    const licenseFiles = packageLicenseFiles.map(({ name, source }) => {
      const fileName = `third-party-licenses/packages/${directory}/${name}`;
      context.emitFile({ type: "asset", fileName, source });
      return `app/${fileName}`;
    });
    manifestPackages.push({
      declared_license: record.declaredLicense,
      license_files: licenseFiles,
      name: record.name,
      version: record.version,
    });
  }
  if (missingLicenses.length) {
    throw new Error(`bundled packages have no distributable license or notice file: ${missingLicenses.join(", ")}`);
  }

  const katexFonts = {
    component: "KaTeX font assets",
    copyright: "Copyright (c) 2009-2010 Design Science, Inc.; Copyright (c) 2014-2018 Khan Academy",
    declared_license: "SIL Open Font License 1.1",
    license_files: ["app/third-party-licenses/katex-fonts/KATEX-FONTS-OFL-1.1.txt"],
    reserved_font_names: [
      "KaTeX_AMS", "KaTeX_Caligraphic", "KaTeX_Fraktur", "KaTeX_Main", "KaTeX_Math",
      "KaTeX_SansSerif", "KaTeX_Script", "KaTeX_Size1", "KaTeX_Size2", "KaTeX_Size3",
      "KaTeX_Size4", "KaTeX_Typewriter",
    ],
  };
  if (!manifestPackages.some((row) => row.name === "katex")) {
    throw new Error("KaTeX font assets were emitted without the KaTeX runtime package");
  }
  context.emitFile({
    type: "asset",
    fileName: "third-party-licenses/katex-fonts/KATEX-FONTS-OFL-1.1.txt",
    source: normalizedText(KATEX_FONT_LICENSE),
  });
  const manifest = {
    generated_from: "Vite client output module graph and package-lock.json",
    packages: manifestPackages,
    schema_version: "1",
    supplemental_assets: [katexFonts],
  };
  context.emitFile({
    type: "asset",
    fileName: "third-party-licenses/manifest.json",
    source: canonicalJson(manifest),
  });

  const notice = [
    "Review Desk third-party notices",
    "",
    "This inventory is generated from the exact client modules in this static build and the locked package metadata.",
    "Each package's complete upstream license and notice files are stored at the paths listed below.",
    "Build tools that do not enter the client bundle are intentionally absent.",
    "",
    ...manifestPackages.flatMap((row) => [
      `${row.name} ${row.version} — ${row.declared_license}`,
      ...row.license_files.map((path) => `  ${path.replace(/^app\//, "")}`),
      "",
    ]),
    "KaTeX font assets — SIL Open Font License 1.1",
    "  Copyright (c) 2009-2010 Design Science, Inc.",
    "  Copyright (c) 2014-2018 Khan Academy",
    "  third-party-licenses/katex-fonts/KATEX-FONTS-OFL-1.1.txt",
    "",
    "These notices describe third-party material only and do not grant a license to Review Desk itself.",
    "",
  ].join("\n");
  context.emitFile({ type: "asset", fileName: "THIRD_PARTY_NOTICES.txt", source: notice });
}

export function runtimeLicenseNotices() {
  return {
    name: "econ-review-runtime-license-notices",
    generateBundle(_options, bundle) {
      emitRuntimeNotices(this, bundle);
    },
  };
}
