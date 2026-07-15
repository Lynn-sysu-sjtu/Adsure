import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "/Users/lcdat/Downloads/Adsure/40个十大类违法广告行政处罚案例汇总表.xlsx";
const outputDir = "/Users/lcdat/Documents/广告合规AI/outputs/ads_penalty_format";

const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 10000,
  tableMaxRows: 8,
  tableMaxCols: 12,
  tableMaxCellChars: 120,
});
console.log(overview.ndjson);

const sheets = await workbook.inspect({ kind: "sheet", include: "id,name" });
console.log(sheets.ndjson);

await fs.mkdir(outputDir, { recursive: true });
for (const line of sheets.ndjson.trim().split("\n")) {
  const item = JSON.parse(line);
  if (!item.name) continue;
  const preview = await workbook.render({ sheetName: item.name, autoCrop: "all", scale: 1, format: "png" });
  const bytes = new Uint8Array(await preview.arrayBuffer());
  await fs.writeFile(`${outputDir}/preview_${item.name.replace(/[\\/:*?"<>|]/g, "_")}.png`, bytes);
}
