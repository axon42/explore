# Explore website concept

2026-09-12. Local mock for review, not a public website or account rollout.
User follow-up: retain this design for now; a more restrained photographic direction is deferred.

- [Landing mock](../frontend/public/website-preview/index.html): `/website-preview/index.html`
- [Product mock](../frontend/public/website-preview/product.html): `/website-preview/product.html`
- Both use the existing localhost port 5173. The app remains at `/`.

## Direction
Warm editorial art direction: cream paper, sage, terracotta, butter yellow, dark ink and a cobalt
accent. Expressive serif headlines paired with quiet system sans-serif. Surreal architectural
artwork depicts two chairs and a shared point of insight. The references inform atmosphere and
composition, not copied brand names, testimonials or invented customer claims.

Landing: large typographic/visual opening, three product ideas, a listening principle, a simple
before/during/after narrative and a product-tour CTA. Product page: interactive preparation,
conversation and report examples, proposed personal/team spaces, and honest availability FAQs.
Planned features are visibly labeled. No signup collection, tracking, fabricated social proof,
pricing promises, paid calls or live recording. Website colors do not replace the product UI.

## Delivery boundary
Plain local HTML/CSS and a small tour script; no framework, remote font or external request.
The product tour is synthetic and does not connect to app APIs. CTAs navigate the mock or the
existing local app. Publishing, authentication, invitations and billing require separate work.
Before launch: approve copy/visual direction, finish capture rehearsal, verify claims and actual
availability, implement chosen CTAs, and validate metadata, accessibility and image performance.

## Mock verification
Inspected both pages on desktop and mobile. Playwright with Chrome passed at 1440, 390 and
320 px: navigation, loaded artwork, all three tour scenes, question discard/restore/status,
evidence dialog dismissal/focus return, FAQs and planned-feature labels. No horizontal
overflow, JavaScript errors, failed requests, external requests or app API calls on these
explicit preview routes. Firefox remains the user's app-testing browser; this automated
mock check used the installed Chrome browser. Frontend lint and production build passed.

## Original artwork
Built-in image generation was used (not the CLI). Project asset:
`frontend/public/website-preview/assets/conversation.png`.

Final prompt:
> Use case: stylized-concept. Asset type: original editorial hero artwork for Explore, a customer-interview research product. Generate an image only, no website UI, no lettering, no logos. A beautifully art-directed surreal miniature architectural stage: two small cobalt blue sculptural chairs face each other on a pale terracotta circular platform, under a monumental soft ivory arch that resembles the outline of a conversation bubble. Through the arch is a dreamy sky with pale turquoise atmosphere and one delicate cloud. A single small butter-yellow orb floats above the space between the chairs, suggesting an insight. Gallery-like stillness, playful but sophisticated, matte plaster and painted wood textures, soft grain, warm afternoon sun, precise long shadows. Background pale sage and warm cream, hints of dusty pink. Centered composition suitable for a tall landing page image panel, artwork fills frame with breathing room around the subjects. Influences are surreal editorial collage and physical art installation, not generic futuristic tech graphics. No people, no screens, no extra objects, no watermarks. High quality portrait 4:5 composition.

## Product-tour refinement (2026-09-12)
Retain the approved cream/sage/terracotta palette and editorial type. The public product tour now
includes a small searchable sample-meeting sidebar, preparation/conversation/report scenes, explicit
workflow-gap/hypothesis examples and a concise during/after explanation. This is local static HTML,
CSS and small DOM interactions; no new framework, external request, signup or billing behavior.
Personal/team spaces remain labeled planned. Desktop/mobile search, scene navigation and evidence
dialog behavior are browser-tested. Meeting tags stay on the roadmap.
