---
name: QEOS
description: Self-hosted test-results analytics; an authenticated Operate surface for triaging CI and reading suite health.
colors:
  page: "#f4f7f9"
  surface-1: "#ffffff"
  surface-2: "#eaf0f4"
  hover: "rgba(15, 27, 38, 0.05)"
  hover-strong: "rgba(8, 145, 178, 0.09)"
  text-primary: "#0f1b26"
  text-secondary: "#4b5d6e"
  text-muted: "#74879a"
  grid: "#e2e9ee"
  border: "rgba(15, 27, 38, 0.1)"
  border-strong: "rgba(15, 27, 38, 0.18)"
  accent: "#0891b2"
  accent-text: "#0e7490"
  accent-soft: "rgba(8, 145, 178, 0.1)"
  accent-fill: "#0e7490"
  accent-fill-hover: "#155e75"
  series-1: "#0891b2"
  series-2: "#eb6834"
  status-passed: "#0ca30c"
  status-failed: "#d03b3b"
  status-errored: "#c4501f"
  control-border: "#71879a"
  placeholder: "#56687a"
  status-skipped: "#a16207"
  skipped-fill: "#eab308"
  skipped-text: "#854d0e"
  danger-text: "#c23434"
  passed-text: "#15803d"
  errored-text: "#b2461a"
  thead: "#eaf0f4"
  danger-fill-hover: "#b83131"
  on-fill: "#ffffff"
  page-dark: "#0b1117"
  surface-1-dark: "#121b24"
  surface-2-dark: "#0e151d"
  hover-dark: "rgba(34, 211, 238, 0.05)"
  hover-strong-dark: "rgba(34, 211, 238, 0.12)"
  text-primary-dark: "#e6edf3"
  text-secondary-dark: "#93a3b5"
  grid-dark: "#1f2a35"
  border-dark: "rgba(147, 163, 181, 0.14)"
  border-strong-dark: "rgba(147, 163, 181, 0.24)"
  accent-dark: "#22d3ee"
  accent-text-dark: "#67e8f9"
  accent-soft-dark: "rgba(34, 211, 238, 0.12)"
  series-1-dark: "#22d3ee"
  series-2-dark: "#d95926"
  danger-text-dark: "#f08080"
  passed-text-dark: "#4ade80"
  errored-text-dark: "#ec835a"
  thead-dark: "#0f1820"
  status-errored-dark: "#ec835a"
  control-border-dark: "#5f7488"
  placeholder-dark: "#93a3b5"
typography:
  headline:
    fontFamily: "\"Inter Variable\", system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  title:
    fontFamily: "\"Inter Variable\", system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.3
  title-small:
    fontFamily: "\"Inter Variable\", system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.35
  stat:
    fontFamily: "\"Inter Variable\", system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "28px"
    fontWeight: 650
    letterSpacing: "-0.01em"
    fontFeature: "\"tnum\""
  body:
    fontFamily: "\"Inter Variable\", system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "\"Inter Variable\", system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "13px"
    fontWeight: 500
  label-small:
    fontFamily: "\"Inter Variable\", system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
  mono:
    fontFamily: "ui-monospace, \"SF Mono\", \"Cascadia Mono\", Consolas, monospace"
    fontSize: "12.5px"
rounded:
  sm: "6px"
  md: "10px"
  pill: "999px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "12px"
  space-4: "16px"
  space-5: "24px"
  space-6: "32px"
  space-7: "48px"
  topbar-height: "48px"
  rail-width: "56px"
  rail-expanded-width: "220px"
components:
  button:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
    height: "34px"
  button-hover:
    backgroundColor: "{colors.hover-strong}"
  button-primary:
    backgroundColor: "{colors.accent-fill}"
    textColor: "{colors.on-fill}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
    height: "34px"
  button-primary-hover:
    backgroundColor: "{colors.accent-fill-hover}"
  button-danger:
    backgroundColor: "{colors.status-failed}"
    textColor: "{colors.on-fill}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
    height: "34px"
  button-danger-hover:
    backgroundColor: "{colors.danger-fill-hover}"
  button-ghost:
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "7px 12px"
  input:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
    height: "34px"
  card:
    backgroundColor: "{colors.surface-1}"
    rounded: "{rounded.md}"
    padding: "{spacing.space-5}"
  nav-link:
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "7px 12px"
    height: "34px"
  nav-link-active:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.text-primary}"
  badge:
    backgroundColor: "{colors.surface-1}"
    typography: "{typography.label-small}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  badge-failed:
    textColor: "{colors.danger-text}"
  topbar:
    backgroundColor: "{colors.surface-1}"
    height: "{spacing.topbar-height}"
    padding: "0 16px 0 12px"
  rail:
    backgroundColor: "{colors.surface-1}"
    width: "{spacing.rail-width}"
    padding: "8px 0"
  project-tile:
    backgroundColor: "{colors.surface-1}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "{spacing.space-4}"
  code-block:
    backgroundColor: "{colors.page}"
    typography: "{typography.mono}"
    rounded: "{rounded.sm}"
    padding: "{spacing.space-3}"
---

# Design System: QEOS

## Overview

**Creative North Star: "The Triage Desk"**

QEOS is an internal Operate surface. People open it after a red build or in a weekly review, and every visual decision serves one question: what is broken, what is flaky, what is getting worse. The system is restrained on purpose. Cool blue-grey slate neutrals carry the structure, one cyan accent marks interaction and location, and the four validated status hues are kept for test outcomes only. Since nothing else on screen is saturated, a red dot means a failure.

Density is moderate. The body text is 14px with an 8px-based spacing scale. Cards, tables and tiles sit on a quiet page tone, a top bar carries the brand, a breadcrumb (with the project switcher) and the user menu, and a slim icon rail on the left holds every view. Light and dark are both first-class and follow the OS (`prefers-color-scheme`). There is no manual toggle. Every text pair is computed against its actual background in both themes and clears WCAG AA (4.5:1). Where a hue fails that test, the system adds a separate text token rather than accepting the miss.

Depth is light and ambient: hairline borders do the structural work, and a faint shadow lifts cards off the page. Motion is short and functional (120ms colour/border transitions, a 120ms rail reveal, a 120ms command palette fade, a 200ms drawer slide) and switches off under `prefers-reduced-motion`.

**Key Characteristics:**
- Cyan Slate: cool blue-grey slate neutrals, one cyan accent, status hues reserved for status.
- Every readable text pair is at least 4.5:1 in both themes. Each accent and danger hue has a separate role token for text and for fill.
- Status is never colour alone. A word or label always sits beside the hue.
- Top bar + icon rail shell. The rail expands over the content on hover or focus and can be pinned open; at 640px and below it becomes a focus-managed drawer.
- Icons come only from lucide-react, marked `aria-hidden`, and always sit beside visible text or inside an `aria-label`ed control.
- Touch targets are 44px under `pointer: coarse`. Body text grows to 16px under 640px.

## Colors

The palette (Cyan Slate, chosen 2026-10-08 after Midnight Indigo was rejected for its violet) is a cool blue-grey slate neutral with one interaction cyan, plus a colour-blind-validated status set that never decorates. Dark-theme counterparts carry the `-dark` suffix in the frontmatter. Status hues, `accent-fill` and `on-fill` are the same in both themes.

### Primary
- **Signal Cyan** (`accent`): focus rings, the active nav icon, the brand mark, project-tile hover border; non-text only in light (3.7:1 on white), `#22d3ee` in dark (9.6:1 on Paper). Text selection uses Button Cyan.
- **Link Cyan** (`accent-text`): all links and any accent text (5.4:1 on white, 4.7:1 on Sidebar Mist; the dark value `#67e8f9` is 12:1 on Paper).
- **Button Cyan** (`accent-fill`, hover `accent-fill-hover`): the fill of primary buttons and of text selection. White on it measures 5.4:1 (hover 7.3:1). The same value is kept in dark mode so white text stays legible.
- **Cyan Wash** (`accent-soft`): a translucent tint of the accent for soft selected states.

### Status (reserved)
- **Passed Green** (`status-passed`), **Failed Red** (`status-failed`), **Errored Orange** (`status-errored`), **Skipped Yellow** (`status-skipped`): the validated status palette from PRODUCT.md. Use them for status dots, chart series of outcomes and badge icons. A status colour is always followed by its word or a label naming it, and never stands alone as a shape: dots, badges and chart bars also differ by shape or texture (see Status Dot and Badges, Chart Textures). Errored Orange is `#c4501f` in light (4.65:1 on Paper, 4.32:1 on Mist Page) and `#ec835a` in dark (6.59:1 on Paper). Skipped Yellow is one family in both themes: the mark `status-skipped` (dot ring, chart lines) is `#a16207` in light (4.92:1 on Paper) and `#facc15` in dark (11.35:1 on Paper); the word on a pill is `skipped-text` (`#854d0e`, 6.85:1 on Paper, `#facc15` in dark); the run bar is the bright `skipped-fill` (`#eab308` in light, `#facc15` in dark), a plain solid like passed with no edge (user decision 2026-10-15); in light it is 1.95:1 on Paper, under the 3:1 non-text rule, and the bar's accessible name and tooltip carry the status. Skipped stays apart from re-run (amber, diagonal stripes) by shape: the run bar is solid where re-run is striped, the dot is a ring, chart series are thin lines and the run panel uses a dashed-circle icon. Every status colour reaches 3:1 on Paper in both themes; `lib/contrast.test.ts` checks it.
- **Danger Text** (`danger-text`): error copy, the error banner border and text, and the failed badge label. It exists because the dot red is a chart/dot hue, not a text colour. It measures 4.6:1 on the banner's red tint in light and 6.0:1 in dark.
- **Passed Text** (`passed-text`) and **Errored Text** (`errored-text`): the readable text of the passed/ready and errored status pills, beside Danger Text for failed. Light `#15803d` is 5.02:1 on Paper (4.54 on a hovered row) and `#b2461a` 5.55:1 (5.02 hovered); dark `#4ade80` is 9.98:1 and `#ec835a` 6.59:1 on Paper. They exist for the same reason as Danger Text: the status hues are for marks, not words.
- **Danger Fill** (`status-failed`, hover `danger-fill-hover`): the confirm button of a destructive action. White on it measures 4.8:1 in both themes, while red *text* on the dark surface would fail AA.

### Chart Series
- **Series Cyan** (`series-1`) and **Series Ember** (`series-2`): the two lines of a comparison chart, such as branch A against branch B. They are for non-status series only.

### Neutral
- **Mist Page** (`page`; slate `#0b1117` in dark): the app background. Code blocks also use it to sit one step below the card surface.
- **Paper** (`surface-1`; `#121b24` in dark): cards, inputs, buttons, tiles, badges and the active nav item.
- **Sidebar Mist** (`surface-2`): recessed panels (secret blocks). Its dark value is also the chrome in dark mode.
- **Chrome** (`chrome`): an alias, not a new colour. The top bar, the rail and the drawer use it: Paper in light, Sidebar Mist in dark.
- **Ink** (`text-primary`): headings, body and values.
- **Graphite** (`text-secondary`): all readable secondary text, including labels, metadata, table headers, `.muted` copy and inactive nav (6.8:1 light, 6.7:1 dark).
- **Tick Grey** (`text-muted`): chart axis ticks only. It is below AA for text (about 3.7:1) and must never carry readable copy.
- **Rule** (`grid`): table row dividers and list separators.
- **Header Band** (`thead`): the background of a data table's header row. An alias of Sidebar Mist in light; in dark `#0f1820`, a step lighter than Sidebar Mist and just under Paper. Graphite on it is 5.91:1 (light) and 6.95:1 (dark).
- **Hairline** (`border`) and **Hairline Strong** (`border-strong`): translucent borders for containers and for buttons.
- **Control Edge** (`control-border`): the border of inputs, selects, textareas and checkboxes, at least 3:1 against every surface they sit on (WCAG 1.4.11). Light `#71879a`: 3.73 on Paper, 3.46 on Mist Page, 3.24 on Sidebar Mist. Dark `#5f7488`: 3.59 on Paper, 3.79 on Sidebar Mist, 3.92 on Mist Page. Used for form controls only, so the rest of the interface stays light.
- **Placeholder** (`placeholder`): placeholder text at full opacity, at least 4.5:1 (light `#56687a`: 5.74 on Paper, 5.00 on Sidebar Mist; dark `#93a3b5`: 6.74 on Paper).
- **Hover** (`hover`) and **Hover Strong** (`hover-strong`): translucent washes for row hover and button/nav hover; Hover Strong is cyan-tinted and also fills label tags.

### Named Rules
**The Reserved Hue Rule.** Green, red, orange and skipped-yellow mean test outcomes. They never decorate, brand or highlight anything else. The only non-status uses are destructive confirmation (red fill) and error messaging (danger text), and both mean "something failed or will be destroyed".

**The Never Alone Rule.** A status colour is never the only signal. Every dot, badge and series carries its word ("12 failed", "Passed") or a legend.

**The Computed Pair Rule.** No text/background pair ships without being computed at 4.5:1 or better in both themes. When a hue fails, add a role token (`-text`, `-fill`) instead of using the hue anyway.

## Typography

**Display Font:** none (the product has no display role)
**Body Font:** Inter (variable, self-hosted via `@fontsource-variable/inter`), falling back to the system UI stack
**Label/Mono Font:** ui-monospace stack (ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace)

**Character:** A single sans family across every role, separated by weight (500 to 650) and small size steps rather than by contrasting faces. Mono marks machine text such as commit SHAs, failure messages and CI snippets.

### Hierarchy
- **Headline** (650, 22px, 1.25, -0.01em): the one page heading, which is the project name or view name.
- **Title** (600, 17px, 1.3): card and section headings.
- **Title Small** (600, 15px, 1.35): sub-section headings.
- **Stat** (650, 28px, tabular figures, -0.01em): the single headline number in an overview card. The tile value is a 26px sibling.
- **Body** (400, 14px, 1.5): everything else. It rises to 16px under 640px, because iOS zooms into inputs below 16px and phones read better at that size.
- **Label** (500, 13px): form labels, metadata rows and tile labels, in Graphite.
- **Label Small** (600, 12.5px): badges and filter chips.
- **Table Header** (600, 11px, uppercase, 0.05em tracking): data table headers, in Graphite on the Header Band.
- **Pill** (600, 11px): status pill words.
- **Mono** (12.5px, or 0.92em inline): failure messages, SHAs and code blocks.

### Named Rules
**The Tabular Numbers Rule.** Tables, tiles and stat figures use `font-variant-numeric: tabular-nums` so columns of counts and rates align.

**The 16px Phone Rule.** Body text is 14px on desktop and 16px at 640px and below. Do not set input text below the body size.

## Layout

An app shell runs the full height of the viewport: a 48px sticky top bar across the full width, a 56px icon rail on the left (220px when pinned open) and a fluid main column, all on Chrome. The page scrolls under the top bar, and `scroll-padding-top` keeps a focused control clear of it. Content sits in a centred page container (max 1120px) with 32px/24px padding, reduced to 24px/16px under 640px. Single-card focus pages (sign in, register, verify) narrow to 400px with 48px top padding.

Spacing follows a 4px-based scale (4, 8, 12, 16, 24, 32, 48). Cards own their vertical rhythm through 16px block margins, which collapse between siblings so conditional stacks stay evenly spaced. Inside a grid, the grid gap owns the spacing and card margins are zeroed.

Grids are auto-fitting rather than column-counted:
- **Overview grid:** `auto-fit, minmax(260px, 1fr)` with a 16px gap. A *wide* widget spans the full row (the latest run and the test-case tiles by default); below two columns wide and normal look the same and widgets stack in layout order.
- **Tiles:** `auto-fit, minmax(170px, 1fr)` with a 12px gap.
- **Project grid:** `auto-fill, minmax(220px, 1fr)` with a 12px gap.

Breakpoints:
- **1280px and up:** a new visitor gets the rail pinned open; below, it starts collapsed. The reader's choice (pin toggle) is remembered in localStorage.
- **640px and below:** the rail becomes an off-canvas drawer (min(85vw, 300px)) behind the top bar's menu button; a 40% black backdrop closes it. The breadcrumb moves to a second line of the top bar. Body text goes to 16px and page and card padding tighten.
- **641px and up:** a list's table header sticks under the top bar while its table fits its card (see Data Tables).
- **`pointer: coarse`:** inputs, selects, buttons, filter chips, rail links and menu items grow to a 44px minimum height, and table cells to 12px padding, without changing density on mouse devices.

### Named Rules
**The Grid Gap Owns It Rule.** Inside a grid, children carry no margins. Outside one, a card's own block margin sets the rhythm.

**The Coarse Pointer Rule.** Every interactive control reaches 44px under `pointer: coarse`.

## Elevation & Depth

The system is a hybrid that leans flat. Hairline borders carry structure, and two ambient shadow levels exist. Shadows never signal status and are never hard-edged or offset.

### Shadow Vocabulary
- **Resting lift** (`box-shadow: 0 1px 2px rgba(17,17,16,0.04), 0 1px 3px rgba(17,17,16,0.06)`; dark: `0 1px 2px rgba(0,0,0,0.4)`): cards and project tiles.
- **Overlay** (`box-shadow: 0 8px 24px rgba(17,17,16,0.12), 0 2px 6px rgba(17,17,16,0.08)`; dark: `0 12px 32px rgba(0,0,0,0.5), 0 2px 8px rgba(0,0,0,0.4)`): elements that float over content, namely the rail while it expands over the page, the user menu, the open drawer, the command palette and the focused skip link.

### Named Rules
**The Two Levels Rule.** Resting surfaces get the resting lift and floating layers get the overlay. There is no third level, and hover does not raise elevation. Hover changes border colour or background tint instead.

## Shapes

Corners are gently rounded and come in two sizes. Controls (buttons, inputs, nav links, code blocks, the error banner, the skip link) use 6px. Containers (cards, project tiles) use 10px. Badges are full pills (999px) and status dots are 8px circles. Borders are 1px translucent hairlines, never heavier. The focus ring is a 2px accent outline offset 2px (offset 0 on text fields).

## Components

### Buttons
Quiet by default. Only one action in a group is filled.
- **Shape:** gently rounded (6px), 34px minimum height (44px on coarse pointers), 6px 10px padding, weight 500, with 6px between icon and label.
- **Default:** Paper fill, Ink text, Hairline Strong border. Hover applies the Hover Strong wash.
- **Primary:** Button Blue fill with white text and no visible border. Hover goes to the deeper fill. There is one primary per form or action group.
- **Danger:** Failed Red fill with white text. It appears only as the confirm step of an in-place destructive confirmation, never as a first-click trigger.
- **Ghost:** transparent fill and border. Used for icon-only controls (menu, close, the rail's pin toggle).
- **Disabled:** 55% opacity with a default cursor.
- **Motion:** 120ms ease-out on background and border colour, removed under reduced motion.

### Destructive Confirmation (signature)
A destructive action never runs on the first click. The trigger is a default button. Clicking it swaps in place for a group with three parts: a one-sentence consequence ("what stops working"), a Danger confirm button that takes focus, and a default Cancel. Cancel or Escape backs out and returns focus to the trigger. There is no modal.

### Status Dot and Badges
- **Status dot:** a 10px mark in the status hue with a shape of its own: circle for passed, triangle for failed, square for errored, ring for skipped. It is `aria-hidden` and always followed by its word or count label ("3 failed").
- **Run verdict badge** (`RunStatusBadge`): icon and word, *Passed*, *Failed* or *Errored* (failures first, then errors). Overview and any run summary use this component; `note` appends text ("Passed · 2 quarantined"). The runs list shows the same verdict (`runVerdict`) as a Status Pill (`RunVerdictPill`).
- **Badge:** a Paper pill with a Hairline border, 12.5px/600, holding a 14px lucide icon and a word. *Passed* has Ink text with a green icon. *Failed* has Danger Text and a border at 40% of the failed red. Badges are for summaries (the Overview verdict, notification delivery); table rows use the Status Pill. The one exception is a provenance marker, such as the Entra badge on a member row: it says where the row comes from, not what its status is, so it is a muted badge.
- **Status pill** (`StatusPill`): the status inside a table row. A small pill (11px/600, 1px 7px padding, 999px radius) with no fill, its word in the tone's readable text token and a Hairline at 45% of the status hue, plus a 12px lucide icon whose shape differs per tone, so the word and the shape carry it without the colour (Never Alone). Tones: *passed* (circled check, Passed Text), *ready* (plain check, Passed Text: a ready case is not a test result), *failed* (circled cross, Danger Text), *errored* (triangle, Errored Text), *running* (loader, not spinning, Link Cyan), *queued* (clock) and *cancelled* (slash) in Graphite, and *neutral* (Graphite, Hairline Strong, no icon) for a draft or archived case. Used for case status (`CaseStatusPill`), run verdicts in the runs list (`RunVerdictPill`) and requested-run status. A requested run's pill holds only the status word ("Running", "Cancelled", "Didn't start"); the rest of its line ("1 test · started by ana", the error) follows it in the cell.

### Run Strip
A compact visual history of a test's own last results (up to 10), one link per run, in a 24px-tall strip. The strip holds one 6×18px bar per run the test was in, with a 2px gap, oldest on the left. Runs of other suites are left out, so there are no gaps and a test with fewer results has a shorter strip; bars do not line up by run across rows (each bar's tooltip names its run). A feature row merges its scenarios' strips: the newest 10 runs any scenario was in, each with the worst status (failed > re-run > passed > skipped).

- **Links:** each bar is a link to what the test looked like in that run: on a case row (and a feature page's scenario card) the case as of the run (`cases/12?run=435`), on a feature row the feature as of the run (`cases/feature?path=…&run=435`); a strip with no such target opens the run itself. The strip is a `group` named by its summary ("Last 10 runs: 7 passed, 2 failed, 1 re-run"); each link is named "Run #435, 6 Oct, 10:02: failed", the same text as its tooltip, and the bar inside it is `aria-hidden`.
- **Log values:** each link's name and tooltip add one line per pattern with values in that run, whatever its status (`trip_id: 3960562, 3960563`; patterns by name, at most five values, then `+2 more`). Text only, no links; the bar stays a link. A feature row's bar merges its scenarios' values per pattern, duplicates removed.
- **Keyboard:** the strip is one tab stop (roving `tabindex`), on the newest bar until another bar takes focus; Left and Right move one bar, Home and End go to the oldest and newest, Enter opens. A long table gains one stop per row, not ten.
- **Bars** carry hover tooltips. Colours signal the last attempt's outcome in that run:
  - **Passed:** `--status-passed` (green).
  - **Failed:** `--status-failed` (red) with a notch cut from the top to signal failure without colour alone.
  - **Re-run:** `--status-rerun` (amber: #b07800 light, #e0a000 dark) with diagonal stripes to distinguish it without relying on hue (dark stripe tone #8a6200, 3.2:1 on the surface).
  - **Skipped:** a plain bright yellow fill (`--skipped-fill`: #eab308 light, #facc15 dark) with no edge, shaped like a passed bar (user decisions 2026-10-15: solid, bright, no border). Only hue tells skipped from passed in the strip; the bar's tooltip and accessible name say the status.
  - Each bar except skipped-in-light meets at least 3:1 non-text contrast against the cell's background in both themes. The light skipped bar is 1.95:1 on white (known limitation, user decision 2026-10-15); in dark it is 11.35:1.
- **WCAG:** the notch and stripes satisfy 1.4.1 (use of colour) for failed and re-run; skipped and passed bars differ by hue only (user decision), with the status in each bar's name and tooltip. Each bar's link fills the strip's 24px height and its 2px gap, so the hit areas touch with no dead space; at 8px wide they are below 2.5.8's 24px (known limitation: the column has room for 10 runs, not 10 targets of 24px). Keyboard users reach every bar with the arrow keys.
- **Accessibility:** when the test has no results, the cell shows the muted text "No runs yet"; on a feature page's scenario card, whose status pill already says so, it shows nothing.
- **Rendering:** until data arrives, the strip keeps its 24px space but stays empty (a hidden "Loading last runs" label for screen readers), so changing page never flashes grey bars. If the request fails, a dash appears and the rest of the page continues working.
- **Column placement:** "Last runs" goes after Title as `hide-narrow`, hidden at 640px and below. A legend above the table explains the colours and shapes. It is hidden when no case on the page is linked. An unlinked case shows only the text "not linked", with no empty strip.

### Log Values
Values a test logged (ADR-032), defined per project in Settings → **Log values**, the card after Masking and built like it: a `table.data` of Name, Pattern and Link ("None" in Muted text when unset) with a Remove `ConfirmButton` per row ("Its values disappear from every run."), and an add form (`form-stack masking-form`): Name; Regular expression with a 24px round **?** toggle (`help-toggle`, `aria-expanded`) that opens an inline help box (`help-popover`, a group named "How values are captured": one group is that part, no group the whole match, values come from the masked log; three example `fchip` buttons fill the field and return focus to it; Escape closes the box and returns focus to **?**); an optional Link (placeholder `https://backoffice.example.com/trips/{value}`); optional log lines with **Preview**, which lists what it found as `name: value` `chip`s with a count ("2 values found:", or "No values found in these lines."). A server refusal is shown under its own field (`field-error`, `aria-invalid`, part of the field's description, focus moved there); a limit or any other error is an `ErrorBanner`. While past runs are scanned, "Scanning past runs…" (a polite status) sits under the list, which is read again every 3 s until the scan ends. Viewers see the list only.

Under the last-result pill on the test case page, and under each scenario card's head on the Feature page, a "Log values" line (a `group` named "Log values", or "Log values of TC-12" on a card): the label in 600 weight, then per pattern `name:` and its values as plain mono text separated by commas, patterns separated by "·". Each value is a text button (`log-value-text`, "Copy trip_id 3960562", title "Click to copy", a Cyan Wash on hover) that writes the value to the clipboard and says "Copied" for 2 s in a polite live region (or that it could not copy); with the pattern's link template a 12px external-link icon beside it ("Open trip_id 3960562 (opens in a new tab)", `rel="noopener noreferrer"`) opens the template with the value URL-encoded, built only from an https template. It follows the result shown: the latest, or the run a Last runs bar opened. No values, no line.

Each value also carries a small "runs" link ("Runs with trip_id 3960562") to the Runs page filtered by that value and pattern. Next to the message on each run-page row (and only there: the test case page and the scenario cards stay to the values), a **Log** toggle (`log-panel-toggle`, `aria-expanded`, named "Log of <test>") opens the result's whole masked log inline (`log-full`: mono, wrapping, 60vh scroll), fetched only when first opened; every occurrence of one of the result's values is a `mark` titled with its pattern name. Above the text: **Copy log** (with "Copied" in a polite live region) and a **Download** link (`<test>-run-<id>.txt`). "No log for this result." in Muted text when there is none, or on a 404 from an older server; a failed request is an `ErrorBanner` with Retry.

### Run from QEOS
Starting a GitHub Actions run from the cases, and watching it end.

- **Play:** a Primary button with the Play icon ("Run", "Run selected (n)", "Run suite"). When disabled, the reason sits beside it in Graphite text, linked when Settings can fix it.
- **Confirmation:** an inline, non-modal card with `role="dialog"` that lists up to 10 cases then "+n more", `repo @ branch`, and the amber `.warn-note` "Tests may create real bookings in staging". For a suite with manual cases the title reads "Run n automated cases (m manual cases skipped)?" and lists only the automated ones. Focus goes to Cancel, Escape backs out, and Run reads "Starting…" and ignores a second click. Under `repo @ branch` a Graphite line gives the duration estimate for the linked cases (ingestion's `POST /analytics/duration-estimate`): "Estimated duration ≈ 12 min (up to 15 min)", with " · 3 tests without history" when some have none (cases with no linked test count too), "No history to estimate yet" when none has any, "under 1 min" below a minute and "1 h 40 min" past 90 minutes. While it loads, a one-line skeleton in a `role="status"` named "Estimating duration" holds the place; when it fails, the line is simply absent. The estimate never holds Play back: Run sends what is known at that moment, and the request stores it. Suite detail shows the same estimate as a muted meta line under the header (`PageHeader` `meta`), from the suite's automated cases, and only when there is history.
- **Selection bar:** sticky at the bottom of the list, with checkboxes on imported rows for editors only. A 200-case cap disables the remaining boxes. The select-all box is indeterminate while only some of the page is selected. Once the selection has linked cases, a Graphite " · ≈ 6 min" follows the Run button: asked 400 ms after the selection stops changing, keyed by the sorted test keys (so the dialog reuses it), and the previous total stays while the next loads, so it never flickers. It is not a live region: a screen reader hears the estimate in the dialog instead of on every tick.
- **Add to suite** (selection bar, editors only, next to Run selected; spec 2026-10-19 §5.5): a default button with the ListPlus icon and `aria-expanded`. It opens an inline card (`role="dialog"`, never a modal) named "Add n cases to a suite" inside the bar. A Suite select lists the manual suites (repository suites are read-only and left out), then "New suite…", which shows a Name field. Focus goes to the Suite select (to the Name field after "New suite…"); Cancel and Escape close the card and return focus to the button. A missing choice or an empty name shows a `field-error` under its field with `role="alert"`, `aria-invalid` and `aria-describedby`, and focus moves to that field. A taken name shows "A suite with this name already exists." the same way; other failures show in an `ErrorBanner`. On success the card swaps for a `role="status"` line "Added 3 cases to Smoke (2 were already there)." (the parenthesis only when some were), an "Open <suite>" link and Close (focused). The selection is kept so the person can add the same cases elsewhere or run them.
- **Run likely affected** (Cases page header, editors only, like Play; spec 2026-10-12 §2.2): a secondary button with the Crosshair icon, `aria-expanded` and (while open) `aria-controls` naming the panel. It opens and closes an inline card under the Run panel, never a modal:
  - **Form:** a Branch field (focused on open; defaults to the CI target's branch until the person types) and **Find tests**, which reads "Finding…" while it works, with a one-line skeleton in a `role="status"` named "Finding likely affected tests". Find tests is the view's primary while the panel is open and nothing is selected (New case steps down); once cases are selected, the selection bar's Run takes it.
  - **Source:** QEOS takes the newest run with changed files among the branch's last 20 runs, scores its changed paths now (`POST /analytics/impact`) and maps the suggested tests to cases by their linked automated test (`POST /cases/search`, pages of 200), strongest suggestion first, at most 200 cases. Only runnable cases (imported, not archived, as the selection boxes) are selected, since Play refuses a run holding a manual case.
  - **Status sentence** (`role="status"`, one sentence per answer): "Selected 2 linked cases for 3 likely affected tests", "1 likely affected test, none linked to a case" (or "to an imported case" when some are linked to manual cases), "No tests are likely affected by the latest change on main", "Not enough history on main yet to suggest tests: 5 of 20 runs with changed files", "No run on main has change data yet", or "Run #70 has no readable change data" (the run counts changed files, but none can be read back). Nothing is ever preselected when nothing is suggested or linked.
  - **Source line:** a muted line with the run it came from ("run #70", linked) and its changed file count; under not enough history it says only the always-included tests were suggested.
  - **Tests Play cannot run** under two `h3` lists, each test linked to its history: "Not runnable from QEOS (no linked case)" and "Not runnable from QEOS (linked only to a manual case)".
  - **Selection:** the linked cases replace the Cases selection, so the selection bar, its Run dialog and the duration estimate follow. The person can still change it.
  - **Closing:** the header button again, Escape inside the panel or the close button (a ghost X, 28px, 44px under `pointer: coarse`), with focus back on the header button (`useFocusReturn`). An error is an Error Banner with Retry.
- **Run panel:** a card with `role="status"`. It has one state line with an 18px lucide icon whose shape differs per state (clock, spinning loader, check, cross, slash, alert), with colours from tokens, so state never rests on colour alone. The spin stops under reduced motion. It has "View in GitHub". Stop uses the Destructive Confirmation pattern ("Stop this run?" then "Stop run"), then "Stopping…", then "Stopped by <name>". When a run ends while Stop is answered, the panel quietly shows the final state. The results line appears only for a run that completed on GitHub: "Waiting for results…", or a link to the results, or after 5 minutes "Results not received: check the QEOS upload step". A completed run whose conclusion is skipped reads "Skipped" with the dashed-circle icon and the Skipped Yellow tone (its own tone, apart from cancelled's slash and Graphite), since it did not run. When the server holds an `error` for the request, the panel shows it: under the state line as a muted line on an active request ("GitHub: token invalid or expired"), and in the state text of a cancelled row ("Cancelled: The run is no longer on GitHub"). The Requested runs tab shows the same line under the status. The elapsed time on a running request is `aria-hidden`, and a visually hidden line states the status and changes only when the status does, so a screen reader is not interrupted every second. An ended run stays for 60 minutes after it ended (the later of `stopped_at` and `checked_at`), however long it ran. The panel re-reads the clock every 30 s, so that message appears without any other update, and not at all while there is no request.
- **Token expiry:** the amber `.warn-note` for owners and admins, from 14 days before expiry, inside a `role="status"` region that is always present so a change is announced. An expired token reads "Expired on <date>" in the Settings connection line, never "Connected".
- **Settings connection form:** the first field is "Repository link", placeholder `https://github.com/owner/name`. It keeps what was pasted (a saved target shows as its link) and a Graphite hint line under it reads "Runs in **owner/name**" once the value parses, joined to the field's description, so the parsed repository is never a guess. After a save, the repository is added to the Repositories card when missing, and a Graphite `role="status"` line says "Added owner/name to Repositories." (or that it could not be added); the save itself never depends on it.
- **Requested runs:** a tab beside Runs (route `runs/requested`) listing every Play with who requested it, the case count, the status, who stopped it, and links to GitHub and to the results. A request that stored an estimate adds a muted line under its status: "≈ 4 min left" while running (from `requested_at` plus the estimate, refreshed with the list's poll), "running longer than estimated" past it, and "estimated 12 min · took 14 min" once completed (took = the matched QEOS run's own duration; unmatched, when the end was seen minus `requested_at`; with no end time at all, only "estimated 12 min"). Older requests without an estimate show nothing extra.

### Cards / Containers
- **Corner Style:** 10px.
- **Background:** Paper on the Mist Page.
- **Shadow Strategy:** resting lift (see Elevation & Depth).
- **Border:** 1px Hairline.
- **Internal Padding:** 24px, or 16px under 640px and inside tile grids.
- **Anatomy:** an optional head row (title left, badge or action right), body, and a foot pinned to the bottom (`margin-top: auto`) that holds the one-click "go deeper" link.
- A card that holds a data table scrolls horizontally inside itself. A list's table card (`sticky-head`) is measured (`useIsWide`: a ResizeObserver on the card and its table, `scrollWidth > clientWidth`); while its table fits, the card opens up so the header can stick to the page, and a table wider than its card keeps its scroll (`is-wide`) with a plain header. No clipping, no nested scroll box.

### Sortable Headers
`SortableTh` puts a button inside the `th`. The `th` carries `aria-sort` (`ascending`, `descending`, or `none`; absent state is `none`), and the button shows an arrow: a double chevron when idle, an up or down arrow on the sorted column. Clicking the sorted column flips it; another column starts descending for figures and dates, ascending for names. The sort lives in the URL as `sort` and `dir` (`lib/sort.ts`, defaults left out), so reload, share and Back keep it. Sorting happens on the server when the API has a sort parameter for that column (Test results: failures, duration, name), otherwise on the rows already loaded, and the page says so ("Sorted within these 50 rows"). Missing values always sort last.

### Narrow Meta
Columns that phones drop (`hide-narrow`) come back as a muted second line in the row's first cell (`NarrowMeta`: label in 600 weight, then the value). It is `display: none` above 640px, so a value is never read twice. Use it on every table that hides columns: Runs (status first), Test results, Flaky, Branches, Compare, Report, Requested runs, the import plan and Cases. Where a column is a graphic (the Cases run strip) the line carries a count instead ("1 failed, 2 passed of the last 3").

### Chart Textures
Outcome series are never told apart by hue alone. `ChartPatternDefs` defines the fills once per page: passed is solid, failed is diagonal stripes, errored is dots, skipped is thin lines, drawn in the surface colour over the status colour. The chart bars and the legend swatches point at the same ids. Comparison lines differ by dash (the second line is dashed) and carry point markers.

Each chart is a `figure` with an off-screen caption that states the totals and the notable point, uses Recharts' `accessibilityLayer` (arrow keys step through the tooltip) and has no `role="img"`. Below it a native `details` (`DataTableDisclosure`, "Show data table") holds the full series as a table. The legend (`SeriesLegend`) is a row of toggle buttons (`aria-pressed`): a hidden series is struck through. Titles, captions, column headings and the last-value tile name the granularity (day, week, month); X ticks are short `Intl` dates ("Mar 4"), thinned on narrow screens; tick text is Graphite, not Tick Grey.

### Secret Block
A value the server shows once (API key, invitation link, recovery codes) sits in a `SecretBlock`: Sidebar Mist fill, Hairline Strong border, a bold one-line note saying it cannot be shown again, the value in mono (wraps anywhere), and a Copy button whose result ("Copied") is announced politely. Recovery codes add Download and an "I saved these codes" button that dismisses them; the codes are not hidden until the reader says so.

### Data Tables
Dense by default. Rows are separated by Rule hairlines, with no zebra striping and no vertical lines; hovering a row applies the Hover wash.

- **Header:** the Table Header style (11px/600 uppercase, 0.05em tracking, Graphite) on the Header Band, never wrapping. Above 640px, on a list whose table fits its card, it is sticky at `top: 48px`, just under the top bar, inside the page scroll (a wide table keeps its sideways scroll and a plain header instead). The page's `scroll-padding-top` covers the top bar plus a sortable header row (`--thead-height`, 41px: 48 + 41 + 8 = 97px), so a row reached by keyboard never lands under either (WCAG 2.4.11). A sorted column keeps its `SortableTh` arrow.
- **Rows:** cells use 8px 12px padding and are top-aligned; every body row is at least 40px tall, room for a 24px control (row checkbox, run strip, row link) with 8px around it. Checkboxes, sort buttons and row links keep 24px targets.
- **Numbers** (`.num`, on the `th` and its `td`s): counts, durations and rates are right-aligned with tabular figures. Words (Priority: low, medium, high) stay left-aligned. A sortable number header puts its arrow on the left, so the label lines up with the figures.
- **Status:** a Status Pill, never bare text.
- Phones keep the existing behaviour: the run strip column and `NarrowMeta` are unchanged.
- **Case titles** (`.case-title`) are the row's primary text at 14.5px/500 in Ink, Link Cyan and underlined on hover or focus. The weight is 500, not 600: the title leads by size and colour, so a long list does not read as a wall of bold.

### Cases: Group by Feature or Scenario
The Cases list has two views of the same filters, chosen by **Group by** (a segmented pair of buttons in the filter bar, `role="group"` named by its visible "Group by" label, each button `aria-pressed`) and stored in the URL as `group=scenario` (Feature, the default, writes nothing). A pressed segment takes the Signal Cyan edge, Link Cyan text on the Cyan Wash and 600 weight, so the state does not rest on colour; under `pointer: coarse` the segments are 44px tall. Switching keeps the filters and goes back to page 1; Apply and Clear all keep the grouping.

- **Scenario view** is the case table as it was.
- **Feature view** is one table with the Scenario view's columns: Title, Last runs, Priority, Status, Automated. Each `.feature` file is a row (`GET /features`, 50 a page): a 24px chevron disclosure (`aria-expanded`, named "Show scenarios of Login"; 44px on coarse pointers), the feature name at 500 linking to the Feature page, its folder in Muted text under it, and under Last runs the same run strip as a scenario row (same bars, link and aria summary), and only the strip: no failing count. The strip is one status per run, the worst over the feature's scenarios (failed, then re-run, skipped, passed, not run: one skipped scenario among green ones makes the feature skipped); `GET /features` sends each row's `test_keys` (distinct automated keys, at most 200), the page fetches every row's strips together in chunks of 200 keys and merges them. A feature with no linked scenario says a muted "not linked" (an older server's row leaves the cell empty); on phones the meta line gives the same count summary as a scenario row. The run legend shows in Feature view whenever a row on the page has keys, expanded or not. A file with no Feature name is titled by its file name without the `.feature` extension (here and on the Feature page); its path keeps the extension. Priority, Status and Automated on a feature row aggregate the scenarios that match the filters (computed by `GET /features`, or from the cases when the page groups them itself): Priority is the highest priority as plain text (labelled "Highest priority: high"); Status is one pill when every scenario shares a status, otherwise the counts as muted text without pills ("2 ready · 1 draft", ordered ready, draft, archived, only statuses that have scenarios); Automated is "All linked" with the Bot icon and `.linked` class, a muted "Manual" when none is linked, or "3 of 5 linked". A value the server did not send leaves its cell empty. On phones Priority and Automated join the row's narrow meta line; Status stays in its column. The Cases list uses a fixed column layout in both views (`table.cases-table`, `table-layout: fixed`): select 36px, Last runs 112px, Priority 80px, Status 112px, Automated 120px, Title takes the rest, so paging or switching view never moves a column; only the content adapts. Feature names, folders and scenario titles in the Cases list sit on one line, cut at 60ch (or the cell width) with an ellipsis (`.truncate`); the full text stays in the `title` tooltip and the accessible name, and the Feature page shows it whole. The manual cases form one last row, "No feature (manual)", which has no link and no checkbox (nothing to run). Expanding a row adds its scenarios as rows of the same table (a `tbody` named "Scenarios of Login") on a Sidebar Mist band, titles indented to line up under the feature name and each scenario's checkbox smaller (18px, a 24px target; 24px on coarse pointers) in the slot under the feature's chevron, the select column left empty, so the scenarios read as the feature's children and every column lines up with the feature above. A file's scenarios come from its detail in file order, kept to the row's filtered case numbers, and the manual group's from `/cases` with the same filters.
- **Suites tab** groups the suites: one collapsible `<details>` per workflow group (Flights, Hotels, ...; ordered by name), then "Made in QEOS" for hand-made suites. The summary is an `h2` with the suite count in Graphite and the workflow file name beside it. Each group is a `table.data` with an sr-only caption. A repository suite row carries a "From repository" badge, and a sharded one a second badge "Half 1 of 2". The New suite form stays below and makes hand-made suites.
- **Repository suite page** (origin "repository") is read-only: a card "From the repository" with a definition list (workflow, suite id, repository, shard, test paths), the sharded note "GitHub splits this folder between Half 1 and Half 2 at run time; both list the whole folder.", and "Managed by the repository: change the workflow to change this suite." Under it the case list without move, remove, save, find or delete controls. A hand-made suite page is unchanged.
- **Failing count:** the failed latest-result keys (the request the Failing tile shares) resolved to case numbers in one `/cases/search` of at most 200; a row counts its case numbers in that set. When more than 200 cases fail, rows show no count rather than a partial one.
- **Suite filter** (Filters disclosure, after Link): "Any" or "Not in any suite" (`suite=none` in the URL, a "Suite: Not in any suite" chip). It keeps the imported, active cases that are in no repository suite, so the gaps can be selected and added to a suite. The feature list cannot apply it, so the Feature view groups the matching cases itself.
- **Filters the feature list cannot apply** (Latest result, Suite, Period, Archived) make the Feature view group the matching cases itself, from one read of up to 200; past that a status line says so and offers the Scenario view.
- **Period** (2026-10-16): the same chips as the Report (7, 30, 90 days, "Custom…" with the `PeriodRange` row under the chips) keep only the cases with a result in that period; with a Latest result filter, the status is the latest result within the period ("failed in the last 7 days"). No period by default. In the URL as `period=7` or `from`/`to`; the custom chip reads "Custom: 1 Oct – 8 Oct 2026" and removing it clears both dates. Origin, Feature and Azure DevOps are no longer filters here (the `@ADO:` label still exists; search finds it).
- **Selection:** a feature row's checkbox selects every runnable scenario it holds and is tri-state (`indeterminate` while only some are picked); "Run selected" works the same in both views.
- **Search in:** a select beside Search (Feature, Scenario, Both), stored as `search_in` only when chosen; otherwise it follows the view (Feature in Feature view, Scenario in Scenario view). The placeholder names what is searched. A chosen scope shows in the search chip ("Search (both): pay"). The Ctrl K palette is unchanged.

### Feature Page
`/projects/:id/cases/feature?path=…`: the feature name as the `h1` (the file name until it loads) and the path as the subtitle, with Run feature (Play for every scenario of the file, editors only) as the one primary. The raw file, as last imported, is a numbered Gherkin block: line numbers in Muted text drawn from `data-line` (never read out or copied), long lines wrapping under their own text. Each scenario's heading line ends with a mono link chip ("TC-12", 24px tall, Link Cyan on Paper with a Hairline Strong edge) and the case's run strip, or "not linked". A file imported before raw files were stored shows the scenarios rebuilt from the cases' Gherkin (a case without Gherkin by its title) under an info note: "Re-import this file to see it exactly as written." Cases whose heading is not found in the file are listed under it. Opened from a Last runs bar (`&run=435`), a note under the counts says "Showing run #435, 6 Oct, 10:02." with the run linked and "Show latest"; every scenario's pill, counts and failed step come from that run, a scenario that was not in it shows a muted "Not in run #435" pill (the counts say "not in run"), and the first marked step is scrolled into view. A scenario whose result is skipped marks the step it stopped at (undefined, pending, ambiguous, or its first step when a hook skipped it; collector 0.9.1) the same way in Skipped Yellow: the line's wash and left bar in `--status-skipped`, the word "skipped" in `--skipped-text` with the dashed-circle icon (`.gk-failed.gk-skipped`, a screen reader hears "Skipped step:"), the same tooltip with the reason where the error would be (what the test attached to that step as text, whole, else the step's status such as "Undefined step"), and a Background step reads "Skipped in Background: …" in the same tone. The scenario page marks its Gherkin the same way. The test case page does the same with `?run=435`: the note adds the case's status ("…: Failed."), or says "This case was not in run #435." (or that a manual case has no result in it), and a run of another project reads "Run #435 is not in this project.".

### Failed Steps (run page)
A card "Failed steps" under "Failures by cause" on a run with a failed Cucumber step (spec `docs/superpowers/specs/2026-10-14-failed-steps-across-cases-design.md`). One row per step, most test cases first: a 24px disclosure button (`aria-expanded`, chevron turning 90°, no motion under reduced motion) holding the step's pattern in mono ("When I search {…}"), then a Graphite line in tabular figures, "failed in 12 test cases · failing since run #430, 14 Oct (5 runs) · last passed in run #429" ("new in this run", "failing for more than 50 runs" or "… 90 days" when capped). A step grouped by text adds a muted note: "Grouped by step text: update the collector to 0.8.0 to group parameter variations." Open, a row lists its error groups: the shape in mono as an `h3` with its count, one real example message in muted text, and the test cases, each linked to its case as of this run (`cases/12?run=61`, the lowest case number when several link the test) or, without a case, to its history, followed by the step text it ran in muted mono; "and N more" past 50. Each row is `#step-<key>`: a link there opens and scrolls to it. The card renders nothing until loaded and nothing for a run without failed steps; a failed request is an Error Banner with Retry inside the card.

The failed-step tooltip on the test case page and the feature page's cards adds, under the error, one 12.5px link to the step's row on the run page: "Also failed in 11 other test cases in this run · failing since run #430" (or "Only this test case · new in this run", "… failing for more than 50 runs"). It is loaded with the tooltip's run, one request per run on the page shared by every card; without it (an older server, a request that failed) the tooltip is as before.

### Filter Chips
A row (`FilterChips`, a `group` named "Quick filters") between a list's filter form and its table. The full form stays as it was; the chips are a shortcut onto the same URL state, never a new server filter.

- **Quick chips:** toggle buttons (`aria-pressed`) in a 999px pill, 28px tall, 12.5px/500: Graphite on Paper with a Hairline Strong edge. Pressed, a chip takes a Signal Cyan edge, Link Cyan text on the Cyan Wash layered over Paper (4.76:1 light, 9.43:1 dark) and a 12px tick, so the state does not rest on colour. Chips that set the same URL key are one choice: pressing Ready while Draft is on switches the value, and pressing the pressed chip clears it. Cases: Failing (`result=failed`), Never ran (`result=never`), Linked (`linked=true`), Manual (`linked=false`), Draft, Ready (`status`). Runs: Failed (`status=failing`), Passed (`status=passing`), main (`branch=main`). Flaky has no quick chips: "Show quarantined" stays the one control for including quarantined tests, and the API has no reason filter for "Suspected". Test results has no outcome filter, so it has no quick chips either.
- **Applied chips:** every other filter in force, including thresholds away from their default, is a chip reading "Name: value" ("Label: flights", "Folder: features / hotels", "Search: legroom") with a 24px remove button named "Remove filter Label: flights". A value a pressed quick chip already shows is not repeated. The row is always mounted (empty, taking no room, when there is nothing to show).
- **Log value:** on Runs, the `value` and `pattern` keys are one chip, "Log value trip_id: 3960562" (or "Log value: 3960562"); removing it drops both. While it is on, each run's link carries the two keys, and the run page shows only the results holding the value, under "3 of 120 results hold trip_id 3960562" with a "Show all results" link; the counts, tiles, failed steps and groups stay the whole run's.
- **+ Filter:** a dashed chip, on pages whose secondary filters sit in a disclosure (Cases, Runs). It opens the disclosure and moves focus to its first control.
- **Clear all:** a ghost button in Link Cyan at the end of the row, shown while any filter is applied; it keeps the sort. It is the list's only clear control (the forms have no "Clear filters" of their own).
- **Focus:** removing a chip moves focus to the chip that takes its place, else the one before it, else the row (`tabIndex=-1`); Clear all moves it to the row. Focus never drops to the page body.
- **Disclosure:** a filter a pressed quick chip shows does not open the Filters disclosure (it would show twice); a filter only the form shows still opens it, even on phones. The summary still counts every filter inside. Runs' "More filters" is controlled: removing its last chip leaves it open.
- **Drafts:** the form follows the URL only in the fields the URL changed, so pressing a chip keeps Search text typed but not yet applied. Clear all is the exception: it blanks the whole form (defaults for thresholds), unapplied drafts included.
- **Announcing:** on Runs a filter change is announced in the existing status line once its runs arrive ("12 runs", "50+ runs"); new runs arriving take precedence. The other lists have no results-count region, so none is added.
- **Behaviour:** chips write the URL (a history entry each, so Back and Forward step through them) and reset paging. The row wraps on narrow screens; Tab moves through the chips and Space or Enter toggles one. Under `pointer: coarse` chips are 44px tall.

### Report Filter Bar
The Report page's filters live in the URL (`period` or `from`/`to`, `branch`, `env`, `ci`, `origin`, `area=kind:value`, `suite`), so a report can be bookmarked and shared and Back undoes a change. One row of `FilterChips`: the period presets (7, 30, 90 days, and "Custom…", which reads "Custom: 9 Sep – 8 Oct 2026" when pressed), a chip per filter in force, "+ Filter" and "Clear all" (which keeps the period). Pressing "Custom…" shows the custom range as its own compact row right under the chips (`PeriodRange`, a form named "Custom period": From, To, Apply, Cancel while no range is applied, the range error inline on its own line); the dates never sit inside the Filters disclosure. The branch starts on the project's default branch and shows it ("Branch: main (default)"); removing that chip means every branch ("Branch: all branches"). The form is a disclosure, closed until "+ Filter" opens it: text fields apply with Apply; selects apply at once. Area is two steps (Feature, Folder or Label, then the value: a searchable `FilterSelect`, or `FolderSelect` for folders). Area and suite chips carry a tooltip: only automated tests linked to a case are counted. A link with invalid parameters loses them and says so in a dismissible notice. A polite live region says "Report updated" once every section asked after a change (Summary, Failure causes, Regressions) has settled and none failed; it is cleared first and written again 150 ms later, so a screen reader reads the same words twice in a row.

### Delta Tiles
The Report's KPI tiles (`DeltaTile`) are KPI Tiles with a change against the previous period of the same length: a lucide arrow (or a dash) and the words ("up 1.2 pts vs previous 30 days"), then the verdict "better" or "worse" in 600 weight. The colour follows the verdict, not the direction: Passed Text for better, Danger Text for worse, Graphite for neutral metrics (runs, executions). Pass rate moves in points, counts and durations in percent. The tile's accessible name is the whole sentence. Without previous data the sub-line says "No data in the previous period".

### Print Header
A `.print-only` block under the Report's title: the period with its days and time zone, the period the deltas compare with, every filter as "Name: value", and when the report was generated. On paper the filter bar and every button are hidden (`.no-print`), each chart and table header avoids a page break, table headers repeat, and every "Show data table" disclosure opens on `beforeprint` and closes again after; the opened tables print whole (their on-screen height cap and scrolling are lifted).

### Report: Failure Causes and Regressions
Failure causes: horizontal bars of the 10 biggest causes (the headline cut to 80 characters; a new cause is striped and its label starts with "New · ", a recurring one is solid), then a table with a Status Pill per cause ("New" in the failed tone, "Recurring" neutral), "seen since at least <date>" (the start of the previous period) when the first sighting is before the period, a sparkline with its numbers in off-screen text, and a 24px chevron (`aria-expanded`; 44px on coarse pointers) that opens the cause's tests on a Sidebar Mist band. Causes that stopped are listed under "Resolved since the previous period". Regressions: four plain tiles (Newly failing, Fixed, Still failing, Median time to fix with "(n at least)"), the "Instability (flips)" chart (bars of flaky tests, a dashed line for their share) with a note on how it differs from the Flaky page, and three tables whose test cells link to the history on that branch and whose run cells (failing since, last passed, fixed at, the count of consecutive failures) link to the run. A start the look-back cut off reads "at least since". The Report no longer has a Flaky table; the Flaky page is unchanged.

### Report: By Area, Coverage and Duration
A "Group by" segmented control (Feature, Folder, Label, Suite; `aria-pressed`, 44px on coarse pointers) is shared by By area and Coverage and kept in the URL (`group`, `depth`) as a view setting: Feature, the default, is left out of the URL, and "Clear all" keeps the grouping. Folder adds a Depth select whose default is the shallowest depth with two groups. The page always loads case-areas, not only under an area or suite filter, because both sections group by it; its version joins the report's query key only when an area or suite filter is set. If case-areas fails, both sections show its error with Retry.

By area: horizontal pass-rate bars for the 15 worst areas with at least 10 executions, the failure count as a text label at each bar's end, then a sortable table (`SortableTh`) worst first: lowest pass rate, then more failures, with areas under 10 executions last and marked "few runs". Each area links to the Cases list (or the suite) with that filter, and a "Tests without a case" row closes the table. Labels and suites carry a note that groups overlap and are not summed; a note under the table says a flaky test here has at least 5 outcomes and flips in at least 30% of consecutive pairs.

Coverage and duration is one frame over the `tests` and `duration` requests; Retry asks again only for the one that failed. Coverage: four plain tiles (Active cases, Linked (automated), Manual, and Automated, not run in this period), stacked linked and manual bars for the 15 largest features or folders (labels and suites fall back to feature, since they overlap) with the manual series striped, the "Automated, not run in this period (under the current filters)" table of up to 200 cases (the rest in its CSV), and a link to the tests without a case. When `tests.truncated` is set, a test past the 50,000-row cap would look never run or unlinked, so the never-run tile and table, the tests-without-a-case count and By area's "Tests without a case" row are hidden, with a note that the list was cut at 50,000 tests. Duration: the heading names its basis, "Run time (wall clock)" or "Time in selected tests (summed)" (with test filters on), and a sentence under it says which. Average (solid) and p90 (dashed) lines, both with markers, with the previous period's average as a dotted reference line labelled "Previous average"; then the slowest areas by total test time, with the average per execution. The Summary's "Average run time" tile stays wall time even with test filters on.

Legends: both charts have a `SeriesLegend` whose entries show or hide a series ("Linked (automated)", "Manual (striped)"; "Average", "p90 (dashed)"); the legend names the texture or dash, so no series is told apart by colour alone.

### Test Impact
Likely affected tests (spec `docs/superpowers/specs/2026-10-12-test-impact-analysis-design.md`, ADR-029).

- **Run page card** "Likely affected tests", on every run: beside Changes when the run reported changes, and when it did not, compact (`.impact-card-compact`): only as wide as its content, the heading and "No change data for this run" on one line, so older runs are not cluttered.
  - **Layout:** the two share a row when there is room (`.run-change-cards`, columns of at least 420px) and stack on narrow screens.
  - **Suggestions,** strongest first: each is a link to the test's history, followed by its evidence in Graphite with tabular figures and the unit in a code span ("newly failed in 4 of 6 runs that changed `src/payment/` (normally 3%)"; the "normally" part is left out when the test never newly failed otherwise), or by a neutral Status Pill label (*test file changed*, *no history yet*, *failing on this branch*).
  - **Outcome line:**
    - "Suggested 12 tests · 3 newly failed · all 3 were suggested" with an "All caught" pill in the passed tone (circled check);
    - or "… · 1 not suggested:" with a "Missed" pill in the failed tone (circled cross) and each missed test linked, indented under that sentence so it never reads as a suggestion;
    - "no new failures" when there are none, and "outcome not recorded yet" while it is written. While it waits, the card asks again every 3 seconds, for about 2 minutes at most; after that the sentence stays until the page is opened again.
  - **Plain Graphite sentences** for "Not enough history yet: N runs with changed files, needs 20" (the labelled tests are still listed; with none, "Nothing to suggest yet."), "No change data for this run", and a run with changes but no stored suggestion ("uploaded before test impact analysis, or scoring failed").
  - **Replayed:** a neutral "Replayed" pill beside the heading, and a sentence that says so.
  - Lists past 15 fold behind a ghost "Show all n" button that becomes "Show fewer" (`aria-expanded`). Loading is a skeleton in the card's own status region; a failure is an Error Banner with Retry inside the card, so the rest of the run page stays usable.
- **Suggested tests first** (spec `docs/superpowers/specs/2026-10-13-suggested-tests-first-design.md`):
  - **Run page line** (`.run-stages`, tabular figures), under the run's metadata, only for a run uploaded by
    `run-impact`. For example: "Suggested tests first: stage 1 (suggested) 12 tests in 1m 05s · stage 2 (the rest)
    340 tests in 14m 10s · first failure after 42.5 s (full suite 15m 15s)".
    - A run of only the suggested tests starts with a neutral "Suggested only" Status Pill and reads "Suggested
      tests only", or "Suggested tests only, stopped after stage 1" after a `--fail-fast` stop.
    - Durations use `formatDuration`, as everywhere else.
    - Each "·" is bound to the item before it by a no-break space, so a narrow screen wraps after a separator and
      no line starts with one.
  - **Runs list:**
    - the same neutral pill beside the run number ("Suggested only · stopped after stage 1" for a stop);
    - the quick chip **Full runs only**;
    - the **Runs** filter under More filters: Full suite only, or Suggested tests only.
  - **Impact card of a subset run:**
    - a neutral "Not evaluated" pill beside the heading;
    - instead of the outcome, the sentence "Suggested tests only, not evaluated: only the suggested tests ran, so
      this run cannot show what the suggestion missed.", and only that: never also "Not enough history yet";
    - the suggestion is still listed, and the card never polls.
  - **API keys (Project Settings):**
    - a **Test suggestions** column reading On or Off as words;
    - for owners and admins, an active key's cell holds the Collection card's switch (`.switch-compact`, named "Test
      suggestions for key ci", "Saving…" while the PATCH runs), and the create form has a "Can read test suggestions"
      checkbox, off by default;
    - one muted help line under the form: "Lets `qeos-collector impact` and `run-impact` read this project's test
      suggestions." (members also read "Only owners and admins allow test suggestions.");
    - a failure (a 409 when the key was revoked meanwhile) is an Error Banner with the API's message, and the list
      is read again.
- **Report section** "Test impact" (`#report-impact`, the Report's last section). It follows no Report filter but the period, and has no gate.
  - **Period:** the Report's when it is the last 7, 14 or 30 days up to today; otherwise the last 30 days, and the note says why ("the Report's period is not the last 7, 14 or 30 days").
  - **Two Stats side by side** (`.impact-figures`, `.stat-big`, tabular figures): the catch rate ("75.0%", then "Suggestions caught 9 of 12 new failures") and the tests suggested per run ("6.4", one decimal at most, then "tests suggested per run, on average"), so a high rate bought by suggesting everything shows (spec §9). Without new failures the rate is "—" with "No new failures in 4 runs with a stored suggestion", never 0%.
  - **Note:** the period, every branch, the other filters not applied.
  - **Replayed runs present:** a definition list (`.impact-parts`, not the Overview's figure list) with Live and Replayed ("caught 3 of 4 new failures in 10 runs").
  - **Misses:** a table of up to 50 with a screen-reader caption, linking the test's history on that branch and the run, the start in the run strip's date format, and the Suggestion column reading "Live" or a neutral "Replayed" pill; "And n more." under it.
  - **No run with a stored suggestion:** "No run with a stored suggestion in the last 7 days". Loading and failure behave as in every Report section.

### Inputs / Fields
- **Style:** Paper fill, Hairline Strong border, 6px radius, 34px height (44px on coarse pointers). Labels stack above the field at 13px/500 in Graphite.
- **Hover:** the border darkens to Tick Grey.
- **Focus:** the border turns Signal Cyan, with a 2px accent outline at offset 0.
- **Filter dropdown:** a filter dropdown with more than 15 options is a searchable list (`FilterSelect`): a search field at the top of the open list, matching anywhere and ignoring accents, with an "x of y" count. Up to 15 options stay a native select.
- **Folder dropdown:** the folder filter (`FolderSelect`) looks like the other filters; its popup is a dialog with a search box, an "x of y" count and the folder tree. Searching keeps matching folders and their ancestors, Enter picks the first match, Esc and Tab close it, and picking applies at once.
- **Text field** (`TextField`): label, input, hint and error as one block. The error appears under the field when it is left (not while typing), is linked with `aria-describedby`, sets `aria-invalid`, and is never inside the `<label>`. A password field has a Show/Hide toggle (an eye icon with off-screen text, `aria-pressed`) outside the label. Checkboxes are drawn 18px (24px when they are a row's only target, in a table cell) with the Control Edge border; a label around one is the hit area.
- **Public pages** (`AuthShell`): the QEOS name and subtitle are a lockup paragraph; each page has its own h1 ("Sign in", "Create account", "Reset your password").
- **Sign in with Microsoft** (`MicrosoftButton`, `.sso-button`): Microsoft's wording with the four-square mark (an inline SVG, `aria-hidden`, 18px) before it, full width with the label centred like the primary, under an "or" divider with a hairline each side (`.auth-divider`, `aria-hidden`). While the Microsoft window is open it reads "Opening Microsoft…" and is disabled, so a second window cannot open. Closing that window is not an error: nothing shows. An MSAL failure shows in the Error Banner as "Microsoft sign-in failed (<code>). Try again, or sign in with your password." (without the password clause in SSO-only mode); a refusal from QEOS's own API keeps its detail. The Google button takes the card's width (Google draws it at a fixed pixel width, 200-400).
- **Sign in, SSO-only mode** (ADR-031, from `GET /auth/methods`): one card with one line ("Sign-in is through your Microsoft work account."), the provider button as the card's primary (the same `MicrosoftButton`, `primary`), then a closed native `<details>` "Administrator sign-in" (the `.more-filters` summary style) holding the email and password form for superusers. No Register or Forgot-password links. While `/auth/methods` loads, or if it fails, the normal form shows; the server enforces the mode either way. Register, Forgot password, Reset password and Verify email show instead a notice card (`SsoOnlyNotice`): h1 "Sign in with Microsoft", the status line "Sign-in is through Microsoft only." and a "Go to sign in" link; also when the server answers 403 `sso_only` and `/auth/methods` was unavailable.
- **Security page, Microsoft account card** (ADR-031): shown to every user in SSO-only mode, otherwise only when the build has Microsoft sign-in. Linked: a status line with the check icon, "Linked to Microsoft". Not linked: one muted line, "Your QEOS password" only when the account has one, and the card's primary "Link Microsoft account" (MSAL popup, then the link request); success is a `success-note`, a refusal an `ErrorBanner`. A build without Microsoft sign-in shows only the state and the muted "no Microsoft sign-in configured" line: no password field, no button. In SSO-only mode the Password card is hidden for everyone but superusers; it waits for the account to load, and is shown if the account cannot be loaded (the server still refuses a non-superuser in the mode).
- **Security page, Microsoft-only sign-in card** (superusers, ADR-031): a status line "Microsoft-only sign-in: On/Off" (icon and text), one muted sentence on how to change it (`AUTH_SSO_ONLY` in `.env`, restart auth-service; never switched from the page), "12 of 15 active users have linked Microsoft.", then the unlinked users in a `table.data` (User, Next sign-in): a secondary "Allow link at next sign-in" button per row (accessible name includes the email) or "Allowed until <date>". Errors in `ErrorBanner`.
- **Organization page, Microsoft roles card** (`MicrosoftRolesCard`, ADR-033): shown to organization owners only, and only when the build has Microsoft sign-in. An h2 "Microsoft roles" and a muted lead line ("People assigned to these app roles in Entra get the role below at each Microsoft sign-in. Owners are always granted by hand."). Then a `table.data` with App role (mono, `<code>`), QEOS role and a Remove button per row that uses the Destructive Confirmation ("Remove this mapping? Members keep their role until their next Microsoft sign-in."; the accessible name includes the app role). Under the table, an inline form: an App role text field, a QEOS role select (admin, member, viewer; never owner) and Add. Empty: "No app roles mapped yet." Loading: "Loading app roles…". A failed load shows an `ErrorBanner` with Retry inside the card. A duplicate app role shows as a `field-error` under the form, linked to the field with `aria-describedby`; the error has `role="alert"` so it is announced; other failures show in an `ErrorBanner`. Starting an add clears a remove's error and the reverse, so only the latest action's banner shows. Under the lead line, a `p.mfa-status` with `role="status"` gives the approval state in words with an icon (`aria-hidden`): "Applied at each Microsoft sign-in" (CircleCheck), or "Not applied yet. A QEOS superuser must approve Microsoft roles for this organization (Security page) before they add or change anyone." (CircleSlash). Nothing shows while the state is unknown.
- **Security page, Microsoft roles approval card** (`EntraSyncAdminCard`, superusers only, ADR-033 amendment): an h3 "Microsoft roles approval", a muted lead line, then a `table.data` (sr-only caption) with Organization (name, slug muted below), Mappings, Status and an actions column. Status is a badge in words: "Approved" (`badge-passed`, CircleCheck) or "Waiting for approval" (`badge-muted`, CircleSlash). Approve is a plain button; Revoke uses the Destructive Confirmation ("Stop Microsoft roles for <name>? Members Entra added stay, and no sign-in changes them."). Both carry the organization in their accessible name and are disabled while a save runs. Empty: "No organization has mapped Microsoft roles yet." Errors show in an `ErrorBanner`.
- **Entra badge** (Organization page, Members table): a member whose role comes from an Entra app role has a muted badge "Entra" after the role (`badge badge-muted`, `title` "Managed by Entra"). The word "Entra" is visible and a visually hidden ", managed by Entra" follows it, because an `aria-label` on a span with no role is ignored. The Remove button for that row stays focusable and has `aria-disabled="true"` instead of `disabled`, looks disabled, and does nothing on click. Its accessible name is "Remove <email or user N>" and its description (`aria-describedby` to a visually hidden span) is "Managed by Entra: remove the app role instead."; `title` carries the same text for mouse users. Keyboard and screen-reader users can reach the button and hear the reason.
- **One primary:** each view has one primary button. A dirty form's Save takes it from Run; Run on a selection takes it from New case; Import takes it from Preview once there is a plan.
- **Inline form:** a one-row create form of label and input pairs ending in its submit and Cancel buttons. It wraps on narrow widths.

### Navigation
- **Top bar:** 48px, Chrome with a bottom hairline, sticky. In order: the brand (lucide mark in Signal Cyan with the bold 15px wordmark, a link to the project picker), the breadcrumb, a spacer, the search trigger (see Command Palette) and the user menu.
- **Breadcrumb:** `<nav aria-label="Breadcrumb">` with an `<ol>`: Org (link to the organization) / Project / section (on detail pages, e.g. Runs) / Page. The project item *is* the project switcher, a compact native select grouped by organization, labelled "Project". The last item is the page, Ink at 600 with `aria-current="page"`; the others are Graphite links. Slashes are CSS decoration with empty alt text. The org crumb holds a placeholder until it is known so the trail does not shift, and it is hidden from 641 to 900px so the bar never overflows.
- **User menu:** a 32px round avatar (the email's initials, Link Cyan on Cyan Wash) that discloses a popup (Paper, overlay shadow, 10px radius): the email, then a plain list of Security and Organization links, a Monitoring button (superusers only, while monitoring is on: it hands over the Grafana cookie and leaves for `/grafana/`, and a refusal shows as an inline error under it) and, below a hairline, Sign out. It is a disclosure (`aria-expanded`, `aria-controls`, normal Tab order), not an ARIA menu, because its items are navigation. Escape closes it and returns focus to the avatar; a click or focus outside, or following an item, closes it. Sign out clears the query cache, so the next account in the tab never sees the previous one's data.
- **Icon rail:** 56px of Chrome with a right hairline. Project views (Overview, Runs, Test results, Flaky, Branches, Trends, Report, Test cases, Settings), then a hairline, then the workspace items (All projects, Organization). Each item is a 40px-tall target with an 18px lucide icon and a visually hidden label; the item on screen has `aria-current="page"`, a Cyan Wash fill, a Link Cyan icon and a 3px Signal Cyan bar on its inline-start edge. Hover (after a 200ms rest) or keyboard focus inside (not the focus a mouse click leaves behind) expands it to 220px *over* the content with the overlay shadow: the rail's box switches width at once (it overflows its grid track, so nothing moves) while the sheet behind it slides in with a 120ms transform and the labels fade in; no layout property is animated, and nothing animates under reduced motion. While collapsed, each label shows as a tooltip (Ink chip, Paper text) on hover or focus; Escape hides tooltips until the pointer or focus moves again. On viewports under 600px tall the collapsed rail scrolls with 32px items, and its tooltips switch to fixed positioning so the scroll box does not clip them. The pin toggle at the bottom ("Expand sidebar" / "Collapse sidebar", `aria-pressed`) keeps it open at 220px, pushing the content. Below 1024px wide a stored pin is ignored (but kept for wider screens).
- **Mobile (640px and below):** the top bar adds a ghost menu button before the brand and wraps the breadcrumb to a second line. The rail becomes the drawer, which slides in over 200ms `cubic-bezier(0.2, 0, 0, 1)` with labels visible and a close button. Opening it focuses the first link. Escape, the backdrop, the close button or following a link closes it; focus returns to the menu button, except after a link, when it goes to the new page's heading.

- **Menus never underline.** Rail and drawer links, breadcrumb links, user-menu items and view tabs (Cases/Suites, Runs/Requested runs) have no underline at rest or on hover; the hover tint and the active background are the affordance. Underlines are kept only for inline links in body text (WCAG 1.4.1). One explicit rule in `index.css` covers all of these and outranks the in-sentence link rule.

### Command Palette
Global search and jump-to, in the top bar and on the keyboard. It is **the one sanctioned modal** in QEOS: a command palette is the standard pattern for "go anywhere from anywhere", and it holds nothing that could be lost. Every other confirmation and form stays in place (see Destructive Confirmation).

- **Trigger:** between the breadcrumb and the avatar, a 32px field-shaped button on Mist Page with a Hairline Strong edge: a search icon, "Search cases, runs, tests…" in Graphite, and a `kbd` hint ("Ctrl K", or "⌘K" on Apple platforms). It carries `aria-haspopup="dialog"` and `aria-keyshortcuts`. On phones it is a ghost icon button named "Search". Ctrl K / ⌘K opens it from anywhere, and "/" opens it when focus is not in a field (also when the layout types "/" with AltGr). A key another handler already took (`defaultPrevented`) or one typed mid-composition (IME) is left alone.
- **Dialog:** `role="dialog"`, `aria-modal`, named "Search", 640px wide (the viewport less 16px each side), 12vh from the top (16px on phones), Paper with the overlay shadow over a scrim of the page tone at 78% (`color-mix` of `--page`), so it reads in both themes. It is portalled to `<body>`; while it is open every other child of `<body>` is `inert` and the page does not scroll, and both are undone on close. The search field is its only Tab stop: Tab stays on it. Esc (wherever focus is) or a press on the scrim closes it, and focus returns to where it was when the palette opened (the trigger when nothing held focus). Opening a result moves focus to the new page's heading instead.
- **Combobox:** the field is a WAI-ARIA combobox (`aria-controls`, `aria-autocomplete="list"`, `aria-activedescendant`) over a listbox of groups (`role="group"` named by its visible uppercase label). Arrow Down and Up move the active option (wrapping), Home and End jump to the first and last, Enter opens it, and the pointer moves the active option on hover. The active option takes the Hover Strong wash with a 2px Signal Cyan inline-start bar. Options are at least 40px tall (44px on coarse pointers).
- **Sources:** Recent (the last 5 opened, newest first, in `localStorage` under the signed-in user's id; signing out forgets every list; blocked storage just means none) and Pages (the project's views and the workspace pages, matched on name from the first letter) need no request. From two characters, and 200ms after the last keystroke, Test cases (title, Gherkin text and the case key: "TC-12", "tc12" or "12" finds case 12 first; the key and title show), Test results (test names, over the Test results view's 30 days), Suites (name contains, opening the suite; the server returns them by name and the palette keeps 5) and Runs are asked in parallel, 5 each; a superseded request is aborted. "#433" or "433" reads run 433's summary (header and counts, no results) and leads the list as "Run #433" with its branch and failed count when it exists (a 404 or 403 just means no run); other text matches runs whose branch contains it, in any case (`branch_contains`). Projects come from the lists the project switcher loads. Outside a project only Pages and Projects are offered, and Recent keeps only workspace items and the current project's.
- **States:** the matched text is a `mark` (Cyan Wash, Ink, weight 600). A source that fails shows one Danger Text line in its own group ("Couldn't search tests right now"), skipped by the arrows; the other groups carry on. With nothing found the dialog says `No matches for "…"`. A visually hidden polite status announces "5 results" or the no-match sentence once every source has answered.
- **Motion:** a 120ms fade and settle (scale from 0.98) on open; nothing under reduced motion.

### KPI Tiles
A row of summary tiles under a list's page header, above its quick filters. Cases has four: Cases (the total, with "N imported"), Pass rate (this week, as Overview's card), Failing (linked cases whose latest result is failed, the Failing chip's join counted) and Flaky (the Flaky view's default 14-day count, with the quarantined count).

- **Shape:** a Paper card (10px radius, Hairline, resting lift) with 12px 16px padding: an uppercase 11px/600 Graphite title, the value at 24px/650 in tabular figures, and a 12.5px sub-line. A 14px lucide mark before the title says the tone, by shape and colour: a dotted circle in Signal Cyan for neutral, a check circle in Passed Green for good, an alert circle in Failed Red for bad. There is no coloured side edge (a thick side stripe reads as generated UI and as a status bar). Pass rate is good when up or flat and bad when down; Failing is bad above zero; the rest are neutral.
- **Never colour alone:** the pass-rate sub-line always has a lucide arrow (up, down, or a dash for flat) *and* the word ("up 3.1 pts vs last week") in Passed Text or Danger Text; the arrow is an icon, not a Unicode glyph.
- **Grid:** 4 columns, 2 under 1024px, 1 under 360px.
- **Links:** a tile that leads somewhere is a link (Failing to `?result=failed`, which presses the Failing chip; Flaky to the Flaky view) with a Signal Cyan border on hover and no underline. Its name is the whole sentence ("Failing 17 linked cases whose latest result failed"). A tile that is not a link is a `group` named by the same kind of sentence ("Pass rate 92.4%, up 3.1 points versus last week").
- **Requests:** a tile reuses the query of the screen that owns the figure, under the same key, and keeps an answer for a minute: Pass rate and Flaky are Overview's queries (Flaky asks with quarantined tests included and each reader counts what it shows), the total is the list's folder total, and Failing is the list's own "Failing" join (latest failed keys, then the search the list sends with only Failing applied), so its number is that list's total and opening the tile costs no request.
- **States:** each tile loads (its own skeleton in a polite status), fails and retries on its own. A failed tile shows "—" and a Retry button ("Retry pass rate") and is not a link while it fails. A missing week is said, never shown as zero ("no runs this week").

### Overview Widgets and Edit Mode
The Overview is a grid of widgets (spec `docs/superpowers/specs/2026-10-11-customisable-overview-design.md`). Each widget is a card whose `h2` is its title as a link to its full view with the same filters (Ink, underlined on hover); its card foot links to the same view. It loads, fails and retries on its own (Error Banner with Retry); a widget set to a branch with no runs in its period says so in a Graphite sentence ("No runs on release in the last 30 days", `EmptyBranch`) with a **Change settings** button that opens edit mode on that widget's settings, never an error or a zero; a widget that throws while rendering shows "This widget failed to load" with Retry in its own card while the rest of the page keeps working, and renders again when its settings change. A widget's code loads only when a layout places it. Widgets reuse the query of the screen that owns the figure, under the same key (as KPI Tiles do). The built-in layout is Latest run (wide), Failing in latest run, Pass rate this week and Flaky tests.

- **Customise** (page header, every role) opens edit mode. A bar in Cyan Wash with a Hairline Strong border reads "Editing your Overview" and holds **Add widget**, **Reset to project default**, **Cancel** and **Save** (primary, enabled once something changed). The page shows the draft; nothing is stored until Save, and neither a background refresh nor a failed poll replaces the draft. Switching project leaves edit mode (after the unsaved-changes guard), so a draft never crosses projects. Focus moves to the bar's title on entry and back to Customise on exit.
- **Widget toolbar** (edit mode only): ghost icon buttons, 28px (44px under `pointer: coarse`), each named for its widget: "Move Pass rate this week up", "Show Pass rate this week wide" (`aria-pressed`), "Pass rate this week settings" (only for a widget with settings), "Remove Pass rate this week". Settings open an inline form in the card (selects for rows, period, view and branch, a text field for the git author name) with Apply (primary) and Close; Escape closes it. **All branches** removes the branch setting (no branch means every branch), so a git branch named `all` is an ordinary choice.
- **Focus and announcements:** a move keeps focus on the moved widget's button, or on the card itself when that button becomes disabled at an end; a removal moves focus to the next widget, or to Add widget; a card focused from the keyboard shows the focus ring; one polite live region says what changed ("Pass rate this week moved to position 2 of 4"), and says it again when the same words repeat.
- **Add widget** opens a card that starts with "Start from a template" (QA lead, Developer, Flaky hunt, each listing its widgets, with a Use button named "Use the QA lead layout"): a template replaces the draft, focus moves to its first widget, the live region says "QA lead layout applied: 5 widgets", and Cancel still undoes it. Under it, "Widgets" lists every widget type with a one-line description and an Add button. At 24 widgets the Add buttons are disabled and the card says why.
- **Leaving:** Cancel with changes asks in place "Discard your changes?" (Discard in danger, Keep editing); navigating away or closing the tab uses the unsaved-changes guard.
- **Conflict:** when the same layout was saved elsewhere meanwhile, an alertdialog in the bar reads "Changed by <email> on <date> since you started" (or "This layout was removed since you started") with Reload (focused) and Overwrite (resends over the stored version); both are disabled while a request runs (focus then rests on the bar's title), and Escape dismisses it, except while a request runs. A Reload that cannot read the stored layout says so and keeps the draft.
- **Default changed:** a muted note "The project default changed on <date>" beside Reset to project default, when the default is newer than the personal layout.
- **Edit project default** (owners and admins): Customise becomes a disclosure with "Customise your Overview" and "Edit project default" (other roles keep the plain button). The bar reads "Editing the project default · everyone without a personal layout sees this" with "Last changed by <email> on <date>" under it, and its reset reads "Reset to built-in default". Editing starts from the project default even when the editor's own personal layout is what they see. Save confirms in place ("Everyone without a personal layout will see this layout.", **Save for everyone**, **Back**); the confirm step is primary, not danger, because nothing is destroyed.
- **Catalogue (15):** Latest run, Failing in latest run, Pass rate this week, Flaky tests, Pass-rate trend (the Trends chart: a line with markers, named by the card's heading, with a sentence for screen readers), Failure causes, Regressions and flips, Recent runs (each verdict as a Status Pill), Branch health (pass rate, runs and last run per branch; no verdict), Slowest tests, Coverage (plain figures in a definition list), Test cases (the four Cases KPI tiles), My recent failures, My suites and Impact accuracy (the Report's Test impact figure under the same query: the catch rate as a Stat, "Caught 9 of 12 new failures", the tests suggested per run beside it, a dash when there were no new failures, replayed runs said; with no run with a stored suggestion, the empty state with **Change settings**). Lists use the failure-list rows; counts use the locale's grouping ("2,124") and every widget card uses tabular figures. Report widgets ask for their own section and refresh when a new latest run arrives; run widgets poll every 30 seconds. My recent failures without a name to match says so with the same **Change settings** button as the empty-branch state.

### Page Header
Every signed-in page starts with `PageHeader`: the page name as the one `h1` (22px/650), an optional Graphite subtitle line under it, actions on the right (at most one primary, the rest secondary) and optional view tabs (Cases/Suites, Runs/Requested runs) underneath. Under 640px the actions wrap below the title. The org and project are not repeated: the breadcrumb carries them. Section headings inside a page are `h2`.

### Project Tile
A Paper tile with a 10px radius, Hairline border and resting lift, holding a folder icon and the project name at 600. On hover the border turns Signal Cyan, with no lift and no underline.

A project pending deletion (ADR-034; owners and admins only) is a recessed tile instead: Recessed Panel fill, a dashed strong border, no lift and Graphite text, not a link. It is a `role="group"` named "<name>, deletion pending" holding the name, a 12.5px line "Deletion pending · removed on 23 Oct 2026, 14:05 · deleted by <email>" and a default **Restore** button (no confirmation: it only undoes; its accessible name is "Restore <name>"). It is not faded, so its text and button keep full contrast. A refused restore (a live project took the name) shows an Error Banner under the grid.

### Delete Project (Settings → Data)
The last block of the Data card, owners and admins only, above a hairline: "Delete this project", one Graphite sentence (hidden at once, deleted permanently 7 days later, restorable meanwhile) and a default **Delete project** trigger with the trash icon. Under a legal hold the trigger is disabled and "Release the legal hold before deleting this project." follows it. It is the Destructive Confirmation pattern with one more part: the trigger swaps in place for a group named "Delete <name>?" with what is deleted and when, a pointer to **Download all results** above, a labelled field "Type the project name to confirm" that takes focus, the Danger confirm **Delete permanently in 7 days** (disabled until the name matches exactly, case included; Enter submits only then) and Cancel. Escape or Cancel backs out and returns focus to the trigger. A refusal is an Error Banner inside the group. On success the page goes to the project list.

### Pending Deletion Notice
A pending project's URLs show one card instead of the view: an h1 "This project is scheduled for deletion" with the trash icon in Graphite, "It will be deleted permanently on <date>, with its runs, results, logs, test cases, suites and settings.", then **Restore project** (primary) for owners and admins, or "Ask an owner or admin if this is a mistake." for everyone else. Restoring reloads the project and its view.

### Error Banner
A 6px-radius box with a Danger Text border and text over a 6% failed-red tint, with an optional Retry button. It uses `role="alert"`. An Overview widget that throws while rendering keeps the failure inside its own card: its heading, then this banner saying "This widget failed to load" with Retry, while the other widgets keep working. Loading and empty states are plain Graphite sentences that say what is absent and how data arrives. They never show a zero in place of missing data.

### Code Block
Mist Page fill, Hairline border, 6px radius, 12px padding, 13px mono, and horizontal scroll. It is used for copyable CI snippets. An expanded failure message inside a table cell is mono 12.5px with preserved line breaks and no box. A read-only Gherkin block colours keywords, tags, tables, doc strings and comments, plus step values: quoted "values" use `--gk-string` and `<placeholders>` use `--gk-param` on a light tint of `--gk-param-bg`; each meets 4.5:1 on Sidebar Mist in both themes. A numbered block (a whole `.feature` file) wraps long lines instead of scrolling, with the line number in a 4ch gutter and any line annotation (a case chip) at the end of its line.

### Accessibility Plumbing
- A **skip link** stays hidden until focused, then appears top-left as a Paper chip with the overlay shadow.
- **Route focus:** on each user navigation (not the first render, not redirects), focus moves to the new page's `h1`. Lazily loaded views (Trends, Branches) render their PageHeader outside the Suspense boundary, so the h1 exists at once and keeps focus while the view loads. The skip link still targets the content region. Headings and regions take focus without a visible ring; the ring belongs to controls.
- **Titles:** each view sets `document.title` as "View · Project · QEOS".
- **Focus not obscured (top):** above 640px the page's `scroll-padding-top` covers the sticky top bar and a sticky sortable table header row.
- **Focus not obscured:** a bar stuck to the bottom of the viewport (the Cases selection bar) writes its height to the page's `scroll-padding-bottom` while it exists and pads the table, so a row reached by keyboard scrolls above it.
- **Landmarks:** the top bar is the `banner`, the rail is `nav` "Main", the breadcrumb is `nav` "Breadcrumb", and the page is `main`.
- **Command palette:** the one modal besides the phone drawer (see Command Palette): focus trapped on its field, Esc closes it and gives focus back.
- **Drawer:** on phones the open rail is a modal dialog (focus trapped, Escape from anywhere closes it). Following a link in it hands focus to the new page's heading, not back to the menu button. Widening the window past the breakpoint closes it and removes the dialog role.
- **Live regions:** a status card announces only its status line (`role="status"` on that line), never the links and buttons around it.

## Do's and Don'ts

### Do:
- **Do** use `accent-text` for links and blue text and `accent-fill` behind white text. Keep `accent` for rings, icons, selection and hover borders.
- **Do** use `text-secondary` for all readable secondary copy. Use `text-muted` only for chart axis ticks.
- **Do** pair every status hue with its word, count or legend.
- **Do** use `danger-text` for error copy and the failed-red fill only for the confirm step of a destructive action.
- **Do** take icons from lucide-react only, sized 14 to 20px and `aria-hidden="true"`, beside visible text or inside a control with an `aria-label`.
- **Do** give every interactive control a 44px minimum under `pointer: coarse` and keep 16px body text under 640px.
- **Do** compute any new text pair in both themes before shipping. It must be 4.5:1 or better.
- **Do** confirm destructive actions in place, with the consequence stated in one sentence and focus moved to the confirm button.
- **Do** give each view a `document.title` and move focus to its content on navigation.
- **Do** put the one-click "go deeper" link in a card's foot.

### Don't:
- **Don't** open a modal. Confirm in place and edit in the page. The command palette is the single sanctioned exception (and the phone drawer is the rail, not a dialog of its own).
- **Don't** use green, red, orange or skipped-yellow for anything that is not a test outcome, error or destruction.
- **Don't** set body or link text in `accent` or `status-failed`, because neither reaches AA as text on every surface.
- **Don't** add a third shadow level, raise elevation on hover, or use hard offset shadows.
- **Don't** use icons from any other set, emoji or Unicode glyphs as icons, or an icon without a text label.
- **Don't** add a manual theme toggle or a light-only colour. Every token needs a dark counterpart or a reason it holds in both themes.
- **Don't** show zero, a placeholder number or sample data where the API returned nothing. Show the absence.
