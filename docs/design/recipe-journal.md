---
version: "alpha"
name: "Handmade Recipe Journal"
description: "An editorial recipe notebook: warm paper, quiet binder details, handwritten annotations, and watercolor food illustrations. Personal, tactile, readable, and made for everyday cooking."
colors:
  primary: "#FAF7EF"
  secondary: "#382822"
  tertiary: "#A33D32"
  neutral: "#DADCCB"
  surface: "#FFFFFF"
  accent: "#596342"
  muted: "#70665D"
  border: "#D8D0C2"
typography:
  h1:
    fontFamily: "Georgia, Batang, serif"
    fontSize: "clamp(2.25rem, 5vw, 4rem)"
    fontWeight: 400
  body-md:
    fontFamily: "system-ui, Malgun Gothic, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
  annotation:
    fontFamily: "Segoe Print, cursive"
    fontSize: "1rem"
    fontWeight: 400
  metadata:
    fontFamily: "Consolas, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.sm}"
    padding: "12px 20px"
---

## Overview

A personal cookbook assembled over time, not a polished SaaS dashboard.
Combine the quiet spacing of an editorial binder with the warmth of a kitchen
scrapbook: cream pages, dark ink, a tomato-red accent, olive pencil marks, and
small watercolor ingredients. The interface should feel collected and lived-in
without making cooking instructions harder to scan.

The supplied references inform the visual language, not a layout to copy:

- Binder cover: restrained composition, generous margins, date stamps, thin edges.
- Annotated recipe page: readable ingredient lists, handwritten notes, underlines.
- Illustrated cookbook: watercolor produce, muted pigment, tactile paper.
- Kitchen drawing: informal cooking gestures and sparse hand-drawn arrows.

Use the first reference for structure and the remaining references for warmth.
Do not turn every screen into a dense illustrated collage.

- Density: 4/10 — Airy overall, structured density inside recipes.
- Variance: 5/10 — Gentle asymmetry, consistent functional controls.
- Motion: 2/10 — Quiet and purposeful.
- **Style:** Editorial, Handmade, Intimate, Kitchen Notebook.
- **Keywords:** paper, binder, recipe journal, watercolor, pencil, ink, marginalia.
- **Light/Dark:** Light-first. Dark mode is outside the current scope.

## Colors

- **Paper** (#FAF7EF) — Main page and recipe sheets.
- **Warm Ink** (#382822) — Titles, ingredients, and body copy.
- **Tomato Red** (#A33D32) — Primary actions and a few editorial accents.
- **Sage Backdrop** (#DADCCB) — The quiet surface behind the notebook.
- **White** (#FFFFFF) — Input surfaces and text on dark action fills.
- **Olive Ink** (#596342) — Secondary actions, selected filters, and note markers.
- **Muted Ink** (#70665D) — Dates, provenance, and secondary labels.
- **Paper Edge** (#D8D0C2) — Rules, sheet edges, and separators.

These are semantic roles, not an instruction to fill equal areas with each color.
Paper and ink dominate; tomato and olive are used sparingly. Keep watercolor
pigments in illustrations, not behind small text. Verify actual contrast for
every final foreground/background pair; pale paper-edge borders are decorative,
not sufficient as the only way to identify an input or selected state.

## Typography

- **Display / Hero:** An editorial serif, regular weight, comfortable spacing.
  Use the system serif stack above; Korean headings must remain legible.
- **Body / UI:** A clean system sans-serif. Ingredients and instructions must
  remain easy to read while standing in a kitchen.
- **Annotations:** A handwriting-like face for short decorative English labels
  or personal notes only. If the font is absent or Korean glyphs do not match,
  fall back to the body stack. Never render long instructions in cursive.
- **Metadata:** Small monospace for source labels, dates, and recipe numbers.
  Technical JSON and job identifiers belong in diagnostic UI, not the hero.

Scale:

- Hero: clamp(2.25rem, 5vw, 4rem).
- H1: 2.25rem; H2: 1.5rem; H3: 1.125rem.
- Body: 1rem / 1.7; metadata: 0.8125rem / 1.5.
- Recipe prose: maximum 65ch; avoid justified text and narrow newspaper columns.

Do not fetch fonts, install font packages, or convert Korean text into an image
without explicit approval. Do not use forced all-caps spacing on Korean copy.

## Layout

- **Canvas:** Sage backdrop with one central paper sheet; max width 1120px.
- **Spacing rhythm:** 8px base with 4px increments for compact details.
- **Page margins:** clamp(16px, 4vw, 48px); section gaps 32–64px.
- **Hero:** Small journal label, expressive title, short purpose statement, and
  at most one offset illustration. Keep the URL input prominent and functional.
- **Recipe detail:** A title block with source and serving metadata, followed by
  ingredients beside steps on desktop. Preserve a clear linear reading order.
- **Recipe library:** Consistent compact recipe sheets, titles, and useful
  metadata. No decorative asymmetry that changes the expected click target.
- **Mobile:** Below 768px, use a single column with ingredients before steps.
  Remove binder gutters and large decorative overlaps rather than shrinking text.
- **z-index contract:** base (0), decorative paper detail (1), sticky navigation
  (100), overlay (200), modal (300), toast (500).

Binder rings, punched holes, clipped notes, and thin paper rules are optional
details. Use at most one binder motif per main view. Decorations must not cover
text, steal pointer events, alter focus order, or create horizontal overflow.

## Elevation & Depth

Paper-on-table depth rather than clay, glass, or floating plastic cards.

- Sheet shadow: 0 4px 18px rgba(56, 40, 34, 0.08).
- Paper edge: a thin warm border; a second sheet may sit subtly behind it.
- Texture: extremely subtle grain from CSS or approved local assets. Do not
  apply filters to text or use heavy distressed overlays.
- Hover: a small contrast change and at most 1px lift, over 150–200ms.
- Active: remove the lift; preserve a clear pressed state.
- Entry: optional opacity transition, no cascading page-wide animation.
- Animate only transform and opacity. Respect prefers-reduced-motion and
  remove nonessential movement and shimmer for that preference.

## Shapes

Paper sheets use nearly square corners: 4–8px, not pill-shaped panels.
Inputs and buttons stay regular and predictable. Hand-drawn curves belong to
illustrations and isolated decorative strokes, not control boundaries.
Small recipe tags may use the 12px radius; do not make every element a sticker.

## Components

- **Primary Button:** Tomato-red fill, white text, 4px radius, minimum 44px
  touch target. One clear primary action per local task.
- **Secondary Button:** Olive or warm-ink outline on paper. Label describes the
  action; do not rely on an unexplained hand-drawn icon.
- **Cards:** Paper recipe sheets with a thin edge and restrained shadow.
  Recipe titles and open actions must remain obvious keyboard-accessible links
  or buttons; decorative rotations must not affect the whole interactive card.
- **Inputs:** Visible label above a regular field, dark enough boundary, and
  distinct focus-visible outline. Keep URL and transcript text readable.
- **Recipe Ingredients:** Aligned names, quantities, and units. Use real
  checkboxes when marking ingredients; handwritten notes never replace values.
- **Cooking Steps:** Numbered ordered list, one action group per step, generous
  line spacing. Illustrations cannot carry an instruction unavailable in text.
- **Annotations:** Short notes in margins or a lightly tinted note block.
  Underlines must not cross letters. Distinguish user notes from AI suggestions.
- **Filters:** Small labeled controls with an explicit selected state.
  Spice and allergy uncertainty must retain the project's existing warnings.
- **Loading:** Plain stage label and a quiet skeleton or progress indicator;
  never show invented progress percentages.
- **Empty State:** One modest ingredient drawing, a useful sentence, and an
  action such as adding a first recipe. No generic marketing filler.
- **Errors / Review:** Clear text with a recoverable action. Do not disguise
  failures, missing source evidence, or uncertain ingredients as decorative notes.

## Illustration & Photography

Choose watercolor vegetables, colored-pencil kitchen tools, or loose ink
drawings with imperfect edges and visible pigment variation. A tomato, herb
sprig, whisk, or pot is enough to establish the visual language.

- Keep drawings away from dense text and functional input areas.
- Use approved local assets or simple code-native SVG marks; preserve existing
  assets until replacement is explicitly in scope.
- New detailed bitmap illustrations require a separate image-generation task.
- Do not copy reference portraits, cookbook covers, artist signatures, or exact
  compositions. Do not use unrelated stock photos or remote placeholder URLs.
- User food photos may appear as small clipped prints when available, but the
  page must still work without a photo.
- Decorative images use empty alt text; informative images use meaningful alt.

## Do's and Don'ts

- Do preserve generous whitespace and a practical ingredient/step hierarchy.
- Do use paper, ink, watercolor, and a few human annotations as a coherent system.
- Do keep recipe data as selectable, accessible HTML text.
- Do verify 360px, 768px, and 1280px layouts, long Korean text, keyboard use,
  focus states, empty results, loading, errors, and review states.
- Do target 4.5:1 text contrast and 3:1 for large text and essential UI boundaries.
- Do reuse existing DOM hooks, API contracts, and approved assets.
- Don't use claymation, glossy 3D, glassmorphism, neon colors, or heavy gradients.
- Don't add emoji confetti, floating hearts, continuous movement, or sticker walls.
- Don't rotate whole recipe bodies or make instructions look like scanned text.
- Don't trade readability for handwritten typography or realistic binder decoration.
- Don't install a UI framework, icon package, font, or asset dependency implicitly.
- Don't change backend, storage, inference, or recipe semantics for a visual effect.

## Use Case

Hanip Note: collecting YouTube recipes, reviewing extracted ingredients,
keeping a personal recipe book, and planning meals from pantry ingredients.
This file guides requested UI work; it does not apply a stylesheet or change
the live website merely by existing.
