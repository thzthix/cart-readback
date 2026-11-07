# CartReadback design entry point

The active [buyer-interface design contract](cart_readback/ui/DESIGN.md) defines
our small editorial buying desk. Read it before UI changes. This root file makes
that existing contract discoverable; it is not a competing token system.

- [Research and implementation map](docs/DESIGN_RESEARCH.md): getdesign.md,
  primary UX/accessibility sources, practitioner critiques and exact application.
- Ordinary buyer UI: `cart_readback/ui/index.html`, `styles.css`, `app.mjs`.
- Separate Gemini result viewer: `cart_readback/ui/viewer.html`, `viewer.mjs`.
  It uses the same paper/ink/forest visual language but has no checkout controls.
- [Gemini viewer privacy contract](docs/GEMINI_RESULT_VIEWER_V1.md): inline
  style is hash-authorized; no stylesheet fetch precedes fragment removal.

Start with the chosen keyboard, exact source, buyer conditions and uncertainty.
Use a real comparison table and neighboring source/result columns, not a generic
hero, feature-card grid, decorative AI symbol, invented metric or testimonials.
Changing a font alone is not a design method, and appearance cannot identify AI
authorship. Preserve truth labels and explicit unknown/conflict states.

The ordinary buyer design already existed before issue #56. The initial Gemini
viewer did not carry that visual system; issue #56 connects its review-only
surface and restores a version-controlled research trail. See the linked research
record for observed checks and the still-blocked rendered-browser stage.
