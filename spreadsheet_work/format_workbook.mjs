import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "/Users/lcdat/Downloads/Adsure/40个十大类违法广告行政处罚案例汇总表.xlsx";
const outputPath = "/Users/lcdat/Documents/广告合规AI/outputs/ads_penalty_format/40个十大类违法广告行政处罚案例汇总表_格式优化版.xlsx";

const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("Sheet1");

sheet.showGridLines = false;
sheet.freezePanes.freezeRows(3);

const used = sheet.getRange("A1:I128");
used.format.font.name = "Microsoft YaHei";
used.format.font.size = 10;
used.format.verticalAlignment = "top";
used.format.wrapText = true;
used.format.borders = {
  insideHorizontal: { style: "thin", color: "#E5E7EB" },
  insideVertical: { style: "thin", color: "#E5E7EB" },
  top: { style: "thin", color: "#D1D5DB" },
  bottom: { style: "thin", color: "#D1D5DB" },
  left: { style: "thin", color: "#D1D5DB" },
  right: { style: "thin", color: "#D1D5DB" },
};

const title = sheet.getRange("A1:I1");
title.merge();
title.values = [["十大类违法广告行政处罚案例汇总表"]];
title.format.fill = "#17365D";
title.format.font.color = "#FFFFFF";
title.format.font.bold = true;
title.format.font.size = 16;
title.format.horizontalAlignment = "center";
title.format.verticalAlignment = "middle";
title.format.rowHeight = 34;

const header = sheet.getRange("A3:I3");
header.format.fill = "#D9EAF7";
header.format.font.bold = true;
header.format.font.color = "#1F2937";
header.format.horizontalAlignment = "center";
header.format.verticalAlignment = "middle";
header.format.rowHeight = 30;
header.format.borders = { preset: "all", style: "thin", color: "#9CA3AF" };

const values = sheet.getRange("A1:I128").values;
for (let r = 0; r < values.length; r += 1) {
  const rowNumber = r + 1;
  const first = values[r]?.[0];
  const second = values[r]?.[1];
  const isSection = typeof first === "string" && /^([一二三四五六七八九十]+)、/.test(first);
  const isHeader = first === "序号" && second === "违法类型";
  if (isSection) {
    const range = sheet.getRange(`A${rowNumber}:I${rowNumber}`);
    range.merge();
    range.format.fill = "#F3F4F6";
    range.format.font.bold = true;
    range.format.font.color = "#111827";
    range.format.horizontalAlignment = "left";
    range.format.verticalAlignment = "middle";
    range.format.rowHeight = 26;
    range.format.borders = {
      top: { style: "medium", color: "#9CA3AF" },
      bottom: { style: "thin", color: "#D1D5DB" },
    };
  }
  if (isHeader && rowNumber !== 3) {
    const repeatHeader = sheet.getRange(`A${rowNumber}:I${rowNumber}`);
    repeatHeader.format.fill = "#E0F2FE";
    repeatHeader.format.font.bold = true;
    repeatHeader.format.horizontalAlignment = "center";
    repeatHeader.format.verticalAlignment = "middle";
    repeatHeader.format.rowHeight = 26;
    repeatHeader.format.borders = { preset: "all", style: "thin", color: "#9CA3AF" };
  }
}

sheet.getRange("A:A").format.columnWidth = 7;
sheet.getRange("B:B").format.columnWidth = 20;
sheet.getRange("C:C").format.columnWidth = 34;
sheet.getRange("D:D").format.columnWidth = 18;
sheet.getRange("E:E").format.columnWidth = 18;
sheet.getRange("F:F").format.columnWidth = 12;
sheet.getRange("G:G").format.columnWidth = 54;
sheet.getRange("H:H").format.columnWidth = 40;
sheet.getRange("I:I").format.columnWidth = 34;

sheet.getRange("A4:A128").format.horizontalAlignment = "center";
sheet.getRange("F4:F128").format.numberFormat = "yyyy-mm-dd";
sheet.getRange("F4:F128").format.horizontalAlignment = "center";
sheet.getRange("G4:I128").format.wrapText = true;
sheet.getRange("G4:I128").format.horizontalAlignment = "left";

for (let row = 4; row <= 128; row += 1) {
  const first = values[row - 1]?.[0];
  const isSection = typeof first === "string" && /^([一二三四五六七八九十]+)、/.test(first);
  const isHeader = first === "序号";
  if (!isSection && !isHeader) {
    sheet.getRange(`A${row}:I${row}`).format.rowHeight = 72;
  }
}

if (sheet.tables.items.length > 0) {
  const table = sheet.tables.items[0];
  table.showFilterButton = true;
  table.showBandedRows = true;
}

await fs.mkdir("/Users/lcdat/Documents/广告合规AI/outputs/ads_penalty_format", { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
