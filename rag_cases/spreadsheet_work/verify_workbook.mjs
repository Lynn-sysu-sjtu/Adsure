import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputPath = "/Users/lcdat/Documents/广告合规AI/outputs/ads_penalty_format/40个十大类违法广告行政处罚案例汇总表_格式优化版.xlsx";
const outputDir = "/Users/lcdat/Documents/广告合规AI/outputs/ads_penalty_format";

const input = await FileBlob.load(outputPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const table = await workbook.inspect({
  kind: "table",
  range: "Sheet1!A1:I12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 9,
  maxChars: 12000,
});
console.log("TABLE");
console.log(table.ndjson);

const styles = await workbook.inspect({
  kind: "computedStyle",
  sheetId: "Sheet1",
  range: "A1:I4",
  maxChars: 8000,
});
console.log("STYLES");
console.log(styles.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log("ERRORS");
console.log(errors.ndjson);

try {
  const preview = await workbook.render({ sheetName: "Sheet1", range: "A1:I18", scale: 1, format: "png" });
  const bytes = new Uint8Array(await preview.arrayBuffer());
  await fs.writeFile(`${outputDir}/verify_preview.png`, bytes);
  console.log("RENDER_OK");
} catch (error) {
  console.log(`RENDER_FAILED: ${error.message}`);
}
