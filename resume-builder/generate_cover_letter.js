// generate_cover_letter.js
// Usage: node generate_cover_letter.js data.json output.docx
//
// Simple layout, no sidebar: date, name (bold), phone/email, recipient block,
// salutation, 3-4 body paragraphs. Aptos 12pt black, 1" margins all sides.

const fs = require("fs");
const { Document, Packer, Paragraph, TextRun } = require("docx");

const [, , dataPath, outPath] = process.argv;
if (!dataPath || !outPath) {
  console.error("Usage: node generate_cover_letter.js data.json output.docx");
  process.exit(1);
}
const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));

const FONT = "Times New Roman";
const SIZE = 24; // 12pt
const MARGIN = 1440; // 1 inch

const children = [];

children.push(new Paragraph({
  spacing: { after: 200 },
  children: [new TextRun({ text: data.date, font: FONT, size: SIZE })]
}));

children.push(new Paragraph({
  spacing: { after: 40 },
  children: [new TextRun({ text: data.name, bold: true, font: FONT, size: SIZE })]
}));
children.push(new Paragraph({
  spacing: { after: 200 },
  children: [new TextRun({ text: `${data.phone} | ${data.email}`, font: FONT, size: SIZE })]
}));

[data.recruiter.name, data.recruiter.title, data.recruiter.company, data.recruiter.location]
  .filter(Boolean)  // skip blank lines (e.g. auto-apply track has no recruiter name/title)
  .forEach((line, i, arr) => {
    children.push(new Paragraph({
      spacing: { after: i === arr.length - 1 ? 200 : 0 },
      children: [new TextRun({ text: line, font: FONT, size: SIZE })]
    }));
  });

children.push(new Paragraph({
  spacing: { after: 200 },
  children: [new TextRun({ text: data.salutation, font: FONT, size: SIZE })]
}));

data.paragraphs.forEach(p => {
  children.push(new Paragraph({
    spacing: { after: 200 },
    children: [new TextRun({ text: p, font: FONT, size: SIZE })]
  }));
});

children.push(new Paragraph({
  spacing: { after: 40 },
  children: [new TextRun({ text: "Sincerely,", font: FONT, size: SIZE })]
}));
children.push(new Paragraph({
  children: [new TextRun({ text: data.name, font: FONT, size: SIZE })]
}));

const doc = new Document({
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN }
      }
    },
    children
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log("Wrote " + outPath);
});
