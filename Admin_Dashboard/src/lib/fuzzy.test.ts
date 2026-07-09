// @ts-nocheck
import { describe, expect, test } from "bun:test";
import { fuzzyFilter } from "./fuzzy";

const docs = [
  { filename: "TECHNICAL_REPORT_V8.pdf", source_path: "upload_docs/General/TECHNICAL_REPORT_V8.pdf", parser: "docling" },
  { filename: "LeaveAtaGlance.pdf", source_path: "upload_docs/General/LeaveAtaGlance.pdf", parser: "docling" },
  { filename: "FAQ_LTDP_28Dec11.pdf", source_path: "upload_docs/QnA/FAQ_LTDP_28Dec11.pdf", parser: "pymupdf4llm" }
];

describe("fuzzyFilter", () => {
  test("matches compact subsequences like Ctrl+P", () => {
    const result = fuzzyFilter(docs, "trv8", ["filename", "source_path", "parser"]);
    expect(result[0].filename).toBe("TECHNICAL_REPORT_V8.pdf");
  });

  test("matches words separated by spaces", () => {
    const result = fuzzyFilter(docs, "leave glance", ["filename", "source_path", "parser"]);
    expect(result[0].filename).toBe("LeaveAtaGlance.pdf");
  });

  test("searches secondary fields", () => {
    const result = fuzzyFilter(docs, "qna", ["filename", "source_path", "parser"]);
    expect(result[0].filename).toBe("FAQ_LTDP_28Dec11.pdf");
  });
});
