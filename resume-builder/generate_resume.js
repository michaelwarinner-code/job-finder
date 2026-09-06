// generate_resume.js
// Usage: node generate_resume.js data.json output.docx
//
// Reads a JSON content file (objective/experience/education/skills) and
// produces a .docx that follows Michael's fixed resume format:
// - US Letter, 0.5" margins (content width = 10800 DXA)
// - Times New Roman, 11pt body / 16pt bold name
// - Bold section headers + company/school names, italic job titles/degrees
// - Right-aligned dates via a right tab stop at the content-width edge
// - Thin black rule under each section
// - Borderless 2x5 skills table
// - Explicit before/after paragraph spacing per section rules

const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, TabStopType, TabStopPosition,
  AlignmentType, BorderStyle, Table, TableRow, TableCell, WidthType,
  ShadingType, HeadingLevel
} = require("docx");

const [, , dataPath, outPath] = process.argv;
if (!dataPath || !outPath) {
  console.error("Usage: node generate_resume.js data.json output.docx");
  process.exit(1);
}
const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));

const FONT = "Times New Roman";
const CONTENT_WIDTH = 10800; // DXA, 7.5in — 0.5in margins on 8.5in page
const MARGIN = 720; // DXA, 0.5in

// Thin rule under a section — paragraph bottom border, full content width
const RULE_BORDER = {
  bottom: { style: BorderStyle.SINGLE, size: 2, color: "000000", space: 1 }
};

function sectionHeader(text) {
  return new Paragraph({
    children: [new TextRun({ text, bold: true, font: FONT, size: 22 })],
    border: RULE_BORDER,
    spacing: { after: 90 } // "space after paragraph" per header rule
  });
}

function projectBullet(text, isLast) {
  return new Paragraph({
    bullet: { level: 0 },
    spacing: isLast ? { before: 60, after: 130 } : { before: 60 },
    children: [new TextRun({ text, font: FONT, size: 22 })]
  });
}

function objectiveParagraph(text) {
  return new Paragraph({
    children: [new TextRun({ text, font: FONT, size: 22 })],
    spacing: { after: 200 }
  });
}

function companyLine(company, dates) {
  // Company bold, dates right-aligned via tab stop at content-width edge
  return new Paragraph({
    tabStops: [{ type: TabStopType.RIGHT, position: CONTENT_WIDTH }],
    spacing: { before: 130 }, // "space before paragraph" for every job entry
    children: [
      new TextRun({ text: company, bold: true, font: FONT, size: 22 }),
      new TextRun({ text: `\t${dates}`, font: FONT, size: 22 })
    ]
  });
}

function locationLine(location) {
  return new Paragraph({
    children: [new TextRun({ text: location, font: FONT, size: 22 })]
  });
}

function titleLine(title) {
  return new Paragraph({
    children: [new TextRun({ text: title, italics: true, font: FONT, size: 22 })],
    spacing: { after: 60 }
  });
}

function bulletParagraph(text, isLast) {
  return new Paragraph({
    bullet: { level: 0 },
    spacing: isLast ? { before: 60, after: 130 } : { before: 60 },
    children: [new TextRun({ text, font: FONT, size: 22 })]
  });
}

function educationBlock(edu) {
  const paras = [];
  // School (bold) + ", City, State" (not bold), dates right-aligned
  paras.push(new Paragraph({
    tabStops: [{ type: TabStopType.RIGHT, position: CONTENT_WIDTH }],
    spacing: { before: 130 },
    children: [
      new TextRun({ text: edu.school, bold: true, font: FONT, size: 22 }),
      new TextRun({ text: `, ${edu.location}`, font: FONT, size: 22 }),
      new TextRun({ text: `\t${edu.dates}`, font: FONT, size: 22 })
    ]
  }));
  paras.push(new Paragraph({
    spacing: { after: 60 },
    children: [new TextRun({ text: edu.degree, italics: true, font: FONT, size: 22 })]
  }));
  if (edu.scholarship) {
    paras.push(new Paragraph({
      bullet: { level: 0 },
      spacing: { before: 60, after: 120 },
      children: [new TextRun({ text: edu.scholarship, font: FONT, size: 22 })]
    }));
  }
  return paras;
}

function skillsTable(technical, other) {
  // Borderless 2-column table: "Technical Skills" bullets | "Other Skills" bullets
  const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
  const cellBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };
  const colWidth = CONTENT_WIDTH / 2;

  function cellFor(header, items) {
    const children = [
      new Paragraph({
        children: [new TextRun({ text: header, bold: true, font: FONT, size: 22 })],
        spacing: { after: 60 }
      }),
      ...items.map(i => new Paragraph({
        bullet: { level: 0 },
        children: [new TextRun({ text: i, font: FONT, size: 22 })]
      }))
    ];
    return new TableCell({
      width: { size: colWidth, type: WidthType.DXA },
      borders: cellBorders,
      children
    });
  }

  return new Table({
    columnWidths: [colWidth, colWidth],
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    rows: [new TableRow({ children: [
      cellFor("Technical Skills", technical),
      cellFor("Other Skills", other)
    ] })]
  });
}

const children = [];

// Name + contact, centered
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 40 },
  children: [new TextRun({ text: data.name, bold: true, font: FONT, size: 32 })]
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 200 },
  children: [new TextRun({ text: data.contact, font: FONT, size: 22 })]
}));

// OBJECTIVE
children.push(sectionHeader("OBJECTIVE"));
children.push(objectiveParagraph(data.objective));

// EXPERIENCE
children.push(sectionHeader("EXPERIENCE"));
data.experience.forEach(job => {
  children.push(companyLine(job.company, job.dates));
  children.push(locationLine(job.location));
  children.push(titleLine(job.title));
  job.bullets.forEach((b, i) => {
    children.push(bulletParagraph(b, i === job.bullets.length - 1));
  });
});

// PERSONAL PROJECTS (optional — only rendered if present in the data)
if (data.personalProjects && data.personalProjects.length) {
  children.push(sectionHeader("PERSONAL PROJECTS"));
  data.personalProjects.forEach((b, i) => {
    children.push(projectBullet(b, i === data.personalProjects.length - 1));
  });
}

// EDUCATION
children.push(sectionHeader("EDUCATION"));
educationBlock(data.education).forEach(p => children.push(p));

// SKILLS
children.push(sectionHeader("SKILLS"));
children.push(skillsTable(data.skills.technical, data.skills.other));

const doc = new Document({
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 }, // US Letter
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
