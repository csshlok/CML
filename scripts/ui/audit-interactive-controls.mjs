import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = path.resolve("apps/desktop/src");
const files = [];
walk(root);
const failures = [];

for (const file of files) {
  if (file.includes(`${path.sep}components${path.sep}ui${path.sep}`)) continue;
  const sourceText = fs.readFileSync(file, "utf8");
  const source = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  visit(source);

  function visit(node) {
    if (ts.isJsxOpeningElement(node) && node.tagName.getText(source) === "button") {
      checkButton(node);
    } else if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(source) === "button") {
      checkButton(node);
    } else if (
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      node.tagName.getText(source) === "Button"
    ) {
      checkProductButton(node);
    }
    ts.forEachChild(node, visit);
  }

  function checkProductButton(node) {
    const attrs = new Set(
      node.attributes.properties
        .filter(ts.isJsxAttribute)
        .map((attribute) => attribute.name.getText(source)),
    );
    const actionAncestors = new Set([
      "ConfirmAction",
      "AlertDialogTrigger",
      "DialogTrigger",
      "DropdownMenuTrigger",
      "PopoverTrigger",
      "SheetTrigger",
    ]);
    let parent = node.parent;
    let wrapped = false;
    while (parent) {
      if (ts.isJsxElement(parent) && actionAncestors.has(parent.openingElement.tagName.getText(source))) {
        wrapped = true;
        break;
      }
      parent = parent.parent;
    }
    const hasAction =
      attrs.has("onClick") ||
      attrs.has("asChild") ||
      wrapped ||
      (attrs.has("type") && node.getText(source).includes('type="submit"'));
    if (!hasAction) {
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
      failures.push(`${path.relative(process.cwd(), file)}:${line} (Button)`);
    }
  }

  function checkButton(node) {
    const attrs = new Set(
      node.attributes.properties
        .filter(ts.isJsxAttribute)
        .map((attribute) => attribute.name.getText(source)),
    );
    const hasAction =
      attrs.has("onClick") ||
      attrs.has("onSubmit") ||
      attrs.has("data-compound-trigger") ||
      (attrs.has("type") && node.getText(source).includes('type="submit"'));
    if (!hasAction) {
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
      failures.push(`${path.relative(process.cwd(), file)}:${line}`);
    }
  }
}

if (failures.length) {
  console.error("Native buttons without an explicit action:");
  failures.forEach((failure) => console.error(`- ${failure}`));
  process.exitCode = 1;
} else {
  console.log(`Interactive control audit passed across ${files.length} TSX files.`);
}

function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) walk(target);
    else if (entry.isFile() && target.endsWith(".tsx")) files.push(target);
  }
}
