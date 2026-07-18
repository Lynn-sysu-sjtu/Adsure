import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const input = await FileBlob.load("/Users/lcdat/Downloads/Adsure/40个十大类违法广告行政处罚案例汇总表.xlsx");
const workbook = await SpreadsheetFile.importXlsx(input);
console.log(workbook.help("range.format", {
  search: "fill|color|font",
  include: "index,examples,notes",
  maxChars: 10000,
}).ndjson);
