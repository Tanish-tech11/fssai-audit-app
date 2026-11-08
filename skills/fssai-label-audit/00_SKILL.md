---
name: fssai-label-audit-skill
description: FSSAI nutraceutical and health supplement label audit engine. Audits a label, carton, artwork or online listing against the Nutra Regulations in both texts (2022 draft and 2016 as amended 2021), the Labelling and Display, Advertising and Claims, Packaging and Legal Metrology rules, the Drugs and Magic Remedies Act and the Consumer Protection e-commerce law, using only the 00_NUTRA LABEL AUDIT LIBRARY, and writes one Word report with marked artwork, deficiency schedule, corrected artwork and suggested label. Trigger on label audit, check this label, nutraceutical or supplement label, FSSAI label compliance, online listing check, composition rationality, Schedule III check, veg non-veg mark, NOT FOR MEDICINAL USE, suggest a compliant label, or any supplement carton photo or PDF.
---

# FSSAI Label Audit and Composition Rationality Engine (final)

## 1. What this skill does

Two things, always both.

**Part A, the label and its online listing.** Every mandatory declaration is put to the label, and to any website, marketplace or direct selling listing of the product, and each failure is recorded with the exact provision breached, in both texts of the Nutra Regulations where they apply.

**Part B, the composition.** Every declared ingredient is matched to its Schedule entry, tested for permitted range and marker standardisation, and the whole formulation is put through the dose reconciliation test. A composition can be perfectly labelled and still be legally impossible.

The output is one Word report (section 4, Step 5) that an advocate can turn into a notice or representation and a designer can work from.

## 2. Where the law and the reference files are

**Library (the only citation source).** `C:\Users\macec\OneDrive\ONE NOTES DOCUMENTS\Claude\FSSAI LABELLING LIABRARY\FSSAI LABELING-NUTRACEUTICAL ONLY\00_NUTRA LABEL AUDIT LIBRARY`, with its register `00_Register of documents_as on 23.10.2026.docx` (updated in place; position line carries the current date). Folders 01 to 08 hold the FSS Act, Rules, Regulations, compendia with the Gazette texts behind them, and the directions and advisories; 09 Legal Metrology (Act as enacted and amended print, the consolidated PC Rules with the 2026 Gazette texts, the advisories of 18.05.2026 and 08.10.2026); 10 the Drugs and Magic Remedies Act, 1954; 11 E-commerce and Consumer Protection (Consumer Protection Act, E-Commerce Rules and amendments, Direct Selling Rules and amendment, CCPA Guidelines and advisories, IT Act and Intermediary Rules, the FSSAI e-commerce instruments). Never cite from memory, from the source folders or from the web. A report cites the compendium page with the Gazette source beside it; a notice or pleading cites the Gazette text (`01_provisions.md` section 0B).

**Control ledger.** `FSSAI LABELLING LIABRARY\FSSAI LABELING-NUTRACEUTICAL ONLY\00_CONTROL LEDGER_Nutra Label Audit_25.10.2026.xlsx` is the master list of every check point with its library file, page, Gazette source, status, in-force date and change history. The checklist in `03_checklist.md` mirrors it. Every APPLY updates both.

**Reference files.** Read them before every audit, in this order. They are kept in the Project "FSSAI NUTRACEUTICAL LABELLING PROJECT" as `claude/skill/00_SKILL.md` to `claude/skill/07_report_builder.md` (read with the Projects tool), and on disk in `...\FSSAI LABELLING LIABRARY\FSSAI LABELING-NUTRACEUTICAL ONLY\skills\fssai-label-audit\` (read through the computer link). The disk copy is the master; the Project copy is an exact copy of it and is replaced whenever the disk copy changes. A file too large for one Project document is held there in numbered parts (`_part2`, `_part3` and so on), each marked at its head and foot; every part is read. Any `references/` folder bundled with the installed skill holds an earlier draft: do not read or cite it.

| File | Holds |
|---|---|
| 01_provisions.md | Every provision with library file and page; section 0A the in-force check; section 2A the 2016 and 2022 correspondence table; section 4 Legal Metrology (Rules, rule 4 import declarations, the Act with both Jan Vishwas amendments); section 6 the directions and advisories applied; section 7 the Drugs and Magic Remedies Act, pinned; section 8 the Packaging Regulations, pinned |
| 01A_provisions_additions.md | Consumer Protection Act, E-commerce and Direct Selling Rules, CCPA Guidelines and advisories, IT Act and Rules, the FSSAI e-commerce instruments; in-force entries; the Jan Vishwas check |
| 02_schedules.md | Structural rules of the Schedules in both texts, Schedule I, Schedule III Part A with ranges and markers, botanical caution statements, Ashwagandha rule, animal origin rules |
| 02A_schedules_full.md | The complete Schedule II (439 botanicals, every part and range), Schedule III Part B (192 entries) and Schedule IV, each with its page in both texts |
| 03_checklist.md | The checklist: points 1 to 197 and 139A, Blocks A to U, every statutory row pinned |
| 04_rationality.md | The dose reconciliation test and worked example |
| 05_templates.md | The report: structure, colours, page, sources |
| 06_reference_data (xlsx on disk; in the Project as text without the two Schedule sheets, which are in 02A) | RDA, vitamin and mineral forms, overages, probiotics (31), prebiotics (16), conversions, claim thresholds, and the full Schedule II and Part B tables as sheets |
| 07_report_builder.py (md copy in the Project) | Script that builds the report from the artwork and a findings file; prints the online listing section and the four exposure heads when given |

**Updates.** Amendments for both label audit projects (nutraceutical and FMCG) arrive in one common folder, `C:\Users\macec\OneDrive\ONE NOTES DOCUMENTS\Claude\FSSAI LABELLING LIABRARY\00_AMENDMENTS-LATEST UPDATES`. The weekly scan puts each new instrument once into `01_INBOX` with a note `WHATS NEW_dd.mm.yyyy.docx`, and `00_ROUTING REGISTER.xlsx` marks each item NUTRA, FMCG or BOTH under the routing rule on its Read Me sheet. Nothing reaches this library, the ledger or this engine until Advocate Mahapatra says APPLY. On APPLY of an item marked NUTRA or BOTH, the PDF is filed in this library, and the library register, the ledger and these engine files are updated in the same pass; the routing register then records where it was filed. The inbox copy is removed once every project the item goes to has received it, and the note moves to `99_DECIDED`.

## 3. Three rules that run through every audit

1. **Two texts of the Nutra Regulations.** The 2022 text (N22) is operated by FSSAI Directions, the last of 30.08.2024; FSSAI also enforces the 2016 Regulations as amended in 2021 (N16) as current law (Advisories of 15.10.2026 and 16.04.2026; ePAAS Order of 06.05.2026). Check the label against both, cite both, and where they differ say so and say which is stricter (`01_provisions.md` section 2A).
2. **In force on the audit date.** Apply only what is in force on the date of the audit (`01_provisions.md` section 0A and `01A_provisions_additions.md` section B). Labelling changes take effect on 1 July, at least 365 days after notification (Order of 06.01.2026). The 2026 amendments to the Labelling and Display and Vegan Regulations and the LM country-of-origin filter substitution apply from 01.07.2027; the Vegan Form I rule from 01.04.2027; the Contaminants Amendment No. 17 from 01.12.2026; the E-Commerce Amendment Rules, 2026 from 01.01.2027; the Legal Metrology Act penalties as substituted by the Jan Vishwas Act, 2026 since 01.05.2026.
3. **Verified and unverified kept apart.** Every finding rests on a library document read at a stated page. Anything else (published literature doses, a document the register lists as a gap) is marked unverified and listed separately in the report.

## 4. Workflow

### Step 1. Read the label completely

Extract every panel before analysing anything. Where the PDF has a text layer, read it and get word positions with PyMuPDF (`page.search_for()`); where it is a scan or a photograph, OCR it (`ocr-general`; vernacular through `translation-ocr`), keep the OCR word boxes for the marked artwork, and check every box by eye on the rendered page. Record verbatim: brand, product and descriptive name; declared category and where it sits; pack format and net quantity; full composition with quantities and units; nutrition panel; every mandatory statement, present or absent; every claim, express or implied, including devices and imagery; veg or non-veg mark, colour, shape, size and position; manufacturer, marketer, addresses, licence numbers; batch, dates, MRP, unit sale price, consumer care; storage, dosage and usage; any seals or logos. Where the product is sold online, capture the listing pages (title, images, description, seller details, price and price history, reviews, sponsored tags) as well. A blank or slipped field is recorded as printed; a blank mandatory field is itself a defect.

### Step 2. Fix the category first

Read `02_schedules.md`. A **Health Supplement** may use Schedules I, II and IV, not Schedule III (except Schedule III enzymes and proteins, Direction of 10.05.2022); a **Nutraceutical** is the category for Schedule III molecules, isolates and extracts. One Schedule III ingredient on a pack declared "HEALTH SUPPLEMENT" makes the category declaration wrong, and every consequence flows from that.

### Step 3. Run the checklist

Read `03_checklist.md` and work Blocks A to U in order (Block T only where there is an online listing or direct selling material; Block U once, in Exposure). Mark each point **NC**, **C**, **UTV** (with the document needed) or **NA** (with the reason). Never mark a point C by inference.

### Step 4. Run the composition audit

Read `02_schedules.md`, `02A_schedules_full.md` and `04_rationality.md`. For each ingredient: Schedule and entry in both texts, permitted range, marker, plant part, caution statement; then the dose reconciliation test. This is the step that finds formulations no relabelling can save.

### Step 5. Write the report

Read `05_templates.md`. One Word report per product, `[Product]_Label Audit Report.docx`, saved in `C:\Users\macec\OneDrive\ONE NOTES DOCUMENTS\00_LABEL AUDIT REPORTS\[Client or case]\[NN Product]\` (created without asking): product identification; executive position; marked artwork (red Critical, orange Major, yellow Minor, numbered boxes); deficiency schedule (crop, as printed, deficiency, provision in both texts, severity, correction in blue); online listing findings where Block T was run; composition and rationality; unable to verify; exposure under four heads (FSS Act, DMR54, Consumer Protection, Legal Metrology) with the forum map; recommended course; corrected artwork (blue boxes); suggested compliant label with changed text in blue; sources relied on, verified and unverified, each with the ledger point number. Build it with `07_report_builder.py`; then render every page and look at it before saving. Language per `ai-removal-mace-style`; saving per `default-saving-all-work-skill`.

Where a notice or representation is to follow, hand the deficiency schedule to `notice-reply-skill`. This skill does not draft notices.

## 5. Standing rules

**Never assert a Schedule entry you have not seen.** Look the ingredient up in `02A_schedules_full.md` and `02_schedules.md`; if it is in no table, it is non-specified (NSF&FI approval, on ePAAS since 01.06.2026) and the finding is UTV pending the approval. No entry is ever invented or inferred.

**Never certify a label as compliant.** The report states which points are met on the face of the label; analytical values, ingredient origin, packaging conformity and licence scope are for the Open Verification List.

**Animal origin is checked first.** Apply the definition in L&D 2(1)(o): it excludes milk, milk products (lactose, whey, casein, colostrum), honey, beeswax, carnauba wax and shellac. Gelatin capsules, collagen, chondroitin, crustacean glucosamine, fish and krill oil, shark cartilage, egg and animal-source vitamin D3 force the brown triangle. A green mark on such a pack is a false declaration on the principal display panel (Letter of 18.09.2019) and usually the most serious single defect.

**Plant part and caution statements.** Every botanical declares its part; every Schedule caution is carried on the label (Advisory of 15.10.2026, Annexure I). Ashwagandha is root or root extract only (Advisory of 16.04.2026).

**Drugs and Magic Remedies Act.** Apply the K.S. Saini test to every hit under s. 3 and name a Scheduled condition only from the Schedule at pp. 9 to 11 of the Act in folder 10.

**Penalties are quoted with their amending Act.** A Legal Metrology penalty is quoted from s. 36 as substituted by the Jan Vishwas Act, 2026 (in force 01.05.2026); the DMR Act and the Consumer Protection Act are untouched by either Jan Vishwas Act (`01A` section C).

**Do the arithmetic yourself.** Energy against macronutrients; per cent RDA against the ICMR-NIN 2020 figure as FSSAI adopted it, on the sedentary adult basis (Direction of 02.08.2021, Note 1), with every row on the same basis; one-RDA ceiling at the maximum stated dose; MRP against unit sale price; any online price reduction against the prior price once CPE26 is in force.

**The suggested label changes only what a finding supports.** Keep the pack's own wording where it already meets the requirement in substance, and add nothing the label did not say and no finding calls for.

**No em dashes, no underline on bold text, no AI or software marks in the document.**

**The latest text is the only text.** When a decision of Advocate Mahapatra changes a rule, a path or a point, the old text is replaced in place in every engine file and in the ledger; no earlier version, note of what was changed, or dated session history is kept beside it. The ledger's Change Log is the one record of what changed and when. A copy of these files found anywhere else (an older Project document, a zip, a backup folder, a bundled references folder) is superseded and is not read.
