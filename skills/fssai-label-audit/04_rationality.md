# Composition rationality: the dose reconciliation test

## 1. Why this exists

Most label audits stop at the panel. A carton can be redrafted in an afternoon. A formulation that cannot lawfully be dosed cannot be redrafted at all, and that is a materially different advice to give a client.

The governing provision is N22 5(7) (N16 3(29)): any combination of ingredients shall be based on available scientific and technical evidence, and that evidence shall be produced to the Food Authority when called for. N22 6(2)(c)(i) (N16 7(3)(i)) supplies the arithmetic: limits as specified in Schedule III, with standardisation to the marker compounds specified, at the daily usage levels specified. The Schedule ranges are the same in both texts (`02_schedules.md`), so the test gives one answer; cite both.

Put together, they mean the recommended daily dose must satisfy every ingredient's Schedule position **at the same time**. Indian combination supplements are usually built by putting fashionable actives on a carton at whatever quantity the tablet will hold. Nobody runs the test. It very often fails.

## 2. The test, step by step

**Step 1. Build the table.**

| Ingredient | Per unit | Schedule and entry | Floor per day | Ceiling per day | Marker required | Marker declared |
|---|---|---|---|---|---|---|

**Step 2. Derive the permitted dose window for each ingredient.**

For ingredient *i* with quantity *q* per tablet, floor *F* and ceiling *C* per day, the number of tablets *n* must satisfy:

- *n* ≥ *F* / *q*
- *n* ≤ *C* / *q*

Round the lower bound up and the upper bound down to whole units, since tablets are not divisible in practice.

Where the Schedule gives only a maximum, the floor is zero and only the upper bound binds. Where the entry is Schedule III Part B with no figures, no bound is imposed by the Schedule, but record that the client must justify the level under N22 6(2)(c)(i) second limb (N16 7(3)(iii)), and that N22 5(7) (N16 3(29)) applies regardless.

For Schedule II botanicals, convert first. The Schedule range is stated in raw herb. Apply the extract ratio before comparing. Where the label declares no ratio, the conversion cannot be performed and the ingredient is recorded as unverifiable, which is itself the Block E defect.

**Step 3. Intersect.**

Take the intersection of every window. Three outcomes:

- **Non-empty, and the label's stated dose falls inside it.** The formulation is dosable and the stated dose is lawful. Rationality then turns on evidence under N22 5(7), which is Step 4.
- **Non-empty, but the label's stated dose falls outside it.** The formulation can be saved by changing the recommended usage level. This is a labelling correction, not a reformulation.
- **Empty.** No daily dose satisfies every ingredient. The formulation cannot be lawfully marketed in its present composition at any dosing schedule. Say so in terms. This is a reformulation finding, and it is the strongest single conclusion this skill produces.

**Step 4. Evidence, ingredient by ingredient.**

Even a dosable formulation has to answer N22 5(7). For each ingredient ask: at the quantity actually delivered per day, is there published evidence of a physiological effect? Where the delivered quantity is a small fraction of the quantity used in the literature, the ingredient is present for the carton and not for the consumer. Record it as label dressing, name the quantity used in the published work, and note that the burden of producing the contrary evidence lies on the FBO, not on the reader.

**Step 5. Standardisation.**

For every Schedule III Part A ingredient, the Schedule prescribes a marker. Compliance with the range is not enough. If the marker is not declared on the label, N22 6(2)(c)(i) is not satisfied even where the milligram figure is within range. This is missed almost every time.

## 3. Worked example

(Schedule entry numbers per the library text: chondroitin is Part B entry 42, collagen peptides entry 53, hyaluronic acid and its salts entry 91, rose hips entry 163.)

LGFLEX Tablets, audited August 2026. Declared per film coated tablet: chondroitin sulphate 200 mg, collagen peptide type II 40 mg, sodium hyaluronate 30 mg, vitamin C 25 mg, rose hip extract 100 mg, Boswellia serrata (Aflapin) 100 mg. Declared category "NUTRITIONAL HEALTH SUPPLEMENT". Recommended usage: "As directed by the Specialist."

| Ingredient | Per tablet | Schedule | Floor per day | Ceiling per day | Tablets, min | Tablets, max |
|---|---|---|---|---|---|---|
| Boswellia serrata gum resin extract | 100 mg | III Part A, entry 5 | 250 mg | 1,500 mg | 3 | 15 |
| Undenatured type II collagen | 40 mg | III Part A, entry 37 | none | 40 mg | 0 | **1** |
| Chondroitin sulphate | 200 mg | III Part B, entry 42 | none stated | none stated | - | - |
| Vitamin C | 25 mg | I | 15 per cent RDA if claimed | 1 RDA, 80 mg | 1 | 3 |
| Sodium hyaluronate | 30 mg | III Part B, entry 91 (hyaluronic acid and its salts) | none stated | none stated | - | - |
| Rose hip extract | 100 mg | III Part B, entry 163 | none stated | none stated | - | - |

Intersection of the Boswellia window (3 to 15 tablets) and the collagen window (0 to 1 tablet) is **empty**.

At one tablet a day the collagen ceiling is exactly reached but Boswellia delivers 100 mg, well below its 250 mg floor. At three tablets Boswellia reaches 300 mg but collagen reaches 120 mg, three times its permitted maximum.

Findings recorded:

1. The formulation cannot be dosed lawfully on any schedule, if the collagen is undenatured type II. N22 6(2)(c)(i) read with Schedule III Part A entries 5 and 37.
2. The declaration "Collagen Peptide (Type II)" is itself the ambiguity. A peptide is hydrolysed, which points to Part B entry 53 with no cap, under which three tablets would be dosable. But 40 mg is the Part A signature quantity and is meaningless for a hydrolysed peptide, which is dosed in grams. The ingredient specification must be called for, because the answer decides whether finding 1 stands.
3. Aflapin is a standardised branded extract, so it is a Schedule III Part A item, so the product is a Nutraceutical and cannot be a Health Supplement. N22 6(1)(b).
4. No marker standardisation declared for the Boswellia. N22 6(2)(c)(i).
5. No part used, extract ratio or standardisation for the rose hip (Part B entry 163). N22 5(2)(a) footnote; ADV 15.10.2026 (plant part on the label).
6. Chondroitin sulphate at 200 mg per tablet against a published clinical range of 800 to 1,200 mg per day. Even at three tablets the delivered 600 mg is below it. N22 5(7) evidence to be called for.
7. Sodium hyaluronate at 30 mg per tablet against 80 to 200 mg in the published work. Same.
8. Vitamin C at 25 mg, 31.25 per cent of the ICMR 80 mg RDA, arithmetically correct and within permitted levels. The only ingredient on the pack that survives the test.
9. No recommended usage level is stated at all, so the FBO has not even asserted a dose against which any of this could be tested. N22 5(12)(a)(ii)(B).

The one-line conclusion for the client: one ingredient at an evidence-based dose, one at a legally impossible dose, one misdescribed, three unjustified, and no stated dose at which any of it could be defended.

## 4. Reference doses used in the evidence limb

These are the quantities the published literature uses. They are not law. They go into the N22 5(7) discussion, never into the Schedule column.

| Ingredient | Quantity used in published work |
|---|---|
| Chondroitin sulphate | 800 to 1,200 mg per day |
| Glucosamine sulphate | 1,500 mg per day |
| Undenatured type II collagen | 40 mg per day, of which about 10 mg is native collagen |
| Hydrolysed collagen peptide | 5 to 10 g per day |
| Hyaluronic acid, oral | 80 to 200 mg per day |
| Rose hip powder, Rosa canina | around 5 g per day |
| Boswellia, Aflapin | 100 mg per day |
| Boswellia, 5-Loxin | 100 to 250 mg per day |
| MSM | 1,500 to 3,000 mg per day |
| Curcumin, standardised | 500 to 2,000 mg per day, bioavailability dependent |
| Vitamin C, as a collagen synthesis cofactor | any level at or above RDA |

Where a client's product delivers less than a quarter of the published quantity, say plainly that the ingredient is present for the carton. Where it delivers more than the Schedule ceiling, the point is no longer evidential; it is a breach.

## 5. Standing cautions

Ingredients appearing in both Schedule II and Schedule III, such as Boswellia serrata, must be classified by their actual form. Oleoresin is Schedule II at 1 to 3 g. A standardised extract is Schedule III Part A at 250 to 1,500 mg. The classification decides the product category, so settle it first.

Never treat a Schedule III Part B entry as unlimited. It shifts the burden, it does not remove it.

Never convert a Schedule II raw-herb range into an extract quantity without the declared extract ratio. If the ratio is not on the label, the conversion is not available and the ingredient is unverifiable.

Where the product is intended for 5 to 16 years, halve every Schedule II range; for 2 to 5 years, quarter it, and add the medical advice condition of N22 5(10) (N16 3(26)).
