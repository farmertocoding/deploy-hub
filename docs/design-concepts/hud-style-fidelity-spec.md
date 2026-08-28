# Deploy Hub HUD Style Fidelity Specification

This specification records the visual construction observed on the [HUD reference dashboard](https://seantheme.com/hud/index.html) and explains how it should be applied to Deploy Hub. It is a design specification, not frontend code.

The reference was inspected in both dark and light modes on 2026-08-27. The important finding is that the HUD material is not conventional blurred glassmorphism. Its depth comes from transparent content surfaces placed over three fixed background layers.

## 1. Background layer model

Render the page in this visual order:

1. **Base color**
2. **Atmospheric cover image** centered and scaled to cover
3. **Strong vertical fog gradient** that subdues the cover
4. **Repeating cutting-mat grid** above the fog
5. **Transparent application content and panels**
6. **Opaque or near-opaque header and appearance panel**

The cover creates the cloudy, fog-glass sensation. The grid gives the application its cutting-mat precision. The panels must remain transparent so both layers continue through their interiors.

Do not substitute opaque card fills or generic `backdrop-filter` blur. That loses the distinctive reference effect.

## 2. Measured reference tokens

### Shared typography and geometry

| Token | Reference value | Deploy Hub use |
|---|---:|---|
| Font family | `Chakra Petch`, sans-serif | All shell, navigation, table, status, and chart text |
| Base font size | `0.875rem` / 14px | Body and table values |
| Letter spacing | `0.046875rem` / 0.75px | Global text tracking |
| Base line height | `1.5` | Body copy and controls |
| Small panel heading | approximately 12.25px | Uppercase panel titles and column groups |
| Primary panel radius | 4px | Panels and large regions |
| Small control radius | 2px | Compact buttons, fields, and chips |
| Background pattern tile | 75px × 75px | Fixed cutting-mat grid |
| Header height | approximately 52px | Persistent global header |

### Dark mode

| Layer/token | Reference value |
|---|---|
| Base background | `#1d2835` |
| Atmospheric cover | `cover-dark.jpg`, center/cover |
| Fog overlay | `linear-gradient(180deg, rgba(50,70,80,.90) 0%, #0d101b 100%)` |
| Cutting-mat texture | `pattern-dark.png`, repeat, 75px |
| Body text | `rgba(255,255,255,.75)` |
| Standard border | `rgba(255,255,255,.25)` |
| Theme accent | `#3cd2a5` |
| Header surface | `rgba(29,40,53,.95)` |
| Appearance-panel surface | `rgba(68,85,94,.95)` |

### Light mode

| Layer/token | Reference value |
|---|---|
| Base background | `#ffffff` |
| Atmospheric cover | `cover.jpg`, center/cover |
| Fog overlay | `linear-gradient(180deg, rgba(255,255,255,.90) 0%, rgba(255,255,255,.99) 100%)` |
| Cutting-mat texture | `pattern.png`, repeat, 75px |
| Body text | `rgba(0,0,0,.75)` |
| Standard border | `rgba(0,0,0,.20)` |
| Theme accent | `#249d79` |
| Header surface | `#ffffff` |
| Appearance-panel surface | `rgba(255,255,255,.95)` |

Light mode is not dark mode with inverted colors. It uses its own cover, grid image, fog gradient, border contrast, header surface, and darker teal accent.

## 3. Panel construction

Every primary HUD-style panel uses five simultaneous frame elements:

1. Transparent interior.
2. Top and bottom 1px edge lines inset 15px from both sides.
3. Left and right 1px edge lines inset 15px from top and bottom.
4. Four 10px × 10px corner containers.
5. Each corner contains a 2px horizontal stroke and a 2px vertical stroke forming an L.

Reference contrast:

- Long edge lines: roughly 25–30% foreground opacity in dark mode and 10–20% in light mode.
- Corner brackets: roughly 75% foreground opacity.
- No panel shadow.
- No opaque panel background.
- No thick neon outline.

This contrast difference makes the corners feel like registration marks on a technical drawing rather than ordinary borders.

## 4. Cutting-mat background

The grid should read as an instrument surface, not graph paper pasted behind the UI.

- Use a 75px repeating major tile.
- Include faint minor subdivisions.
- Keep grid contrast low enough that tables remain readable.
- Allow occasional very subtle luminous intersections or calibration points.
- Keep the grid fixed relative to the viewport so scrolling content feels placed over a stable control surface.
- Continue the grid through the sidebar and transparent panels without discontinuities.
- Place the atmospheric cover beneath the grid, never above it.

## 5. Fog-glass feeling

The desired feeling is produced by atmospheric layering rather than frosted-card blur:

- The cover supplies vague shapes, light blooms, and depth.
- The strong gradient veil turns the cover into fog.
- Transparent panels allow the fog and grid to remain visible.
- The nearly opaque header establishes a stable foreground plane.
- Thin frame lines create the impression of floating measurement regions.

Avoid:

- Blurred translucent rectangles.
- Large radial-gradient blobs.
- Glossy reflections.
- Strong drop shadows.
- Opaque navy or white card slabs.
- Rounded consumer-SaaS cards.

## 6. Typography hierarchy

- Page titles: 28–32px, medium/semibold, sentence case.
- Large metrics: approximately 28px, bold.
- Panel headings: approximately 12px, uppercase, semibold.
- Body/table text: 14px.
- Secondary metadata: 12–13px with reduced opacity.
- Statuses: uppercase 11–12px, word plus symbol.
- Global tracking: approximately 0.75px.

Use Chakra Petch consistently. Mixing a generic geometric font into charts or tables will weaken the style.

## 7. Controls and status language

- Buttons are rectangular, compact, and text-labelled.
- Use 1px translucent borders and 2–4px radii.
- Primary actions use the theme accent without glow.
- Navigation controls stay neutral or use accent text.
- Destructive actions use red outline and an explicit destructive verb.
- Warnings use amber; failures use red; healthy/running uses teal.
- Do not make every chip a filled pill.
- Use compact outline icons with consistent optical weight.
- Interactive charts and cards require explicit text links; the whole decorative region is not silently clickable.

## 8. Appearance switch

The global header includes a real `Appearance` control. It opens a compact framed popover with preview thumbnails for:

- **Dark**
- **Light**

Behavior:

1. Selecting a mode updates every background layer, foreground token, chart color, border color, and control state together.
2. The selected preview shows a visible check and text label.
3. The setting persists per user and workspace.
4. The application may initially follow the operating-system preference, but an explicit user selection overrides it.
5. Switching appearance never changes environment, permissions, filters, selected object, or deployment state.
6. Charts must be redrawn with the new contrast tokens; they must not merely inherit a CSS filter.
7. Reduced-motion preferences disable animated background transitions.

## 9. Deploy Hub fidelity checklist

Before accepting a visual or implementation, verify:

- Is the cutting-mat grid visible through every major panel?
- Is the atmospheric cover visible but heavily veiled?
- Are cards actually transparent?
- Are long panel edges fainter than the corner brackets?
- Are all four 10px L corners present?
- Does light mode use its own cover, grid, fog gradient, and teal value?
- Does the 52px header sit on a more opaque visual plane?
- Is Chakra Petch used at the correct tracking and density?
- Are controls compact and minimally rounded?
- Are charts small and operational rather than decorative?
- Does every visible control have a defined use in the functional screen contract?

If any of the first eight checks fail, the result may resemble a generic dark dashboard but it will not reproduce the HUD reference style.
