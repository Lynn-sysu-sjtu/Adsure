import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const input = await FileBlob.load("/Users/lcdat/Downloads/Adsure/40个十大类违法广告行政处罚案例汇总表.xlsx");
const workbook = await SpreadsheetFile.importXlsx(input);
console.log(workbook.help("*", {
  search: "fill|font|wrapText|alignment|freezePanes|columnWidth",
  include: "index,examples,notes",
  maxChars: 8000,
}).ndjson);
