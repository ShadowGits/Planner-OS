# Planner OS app artwork

Approved artwork: `planner-angel-demon-cartoon.png`.

Created with the built-in image-generation tool. Prompt: two goofy male 3D animated mascots, clearly an angel with a halo and feathered wings and a demon with horns, bat wings and a tail, pulling a cream daily planner apart. Navy background, ice-blue angel, wine/marsala demon, no lettering. The user selected this version on 2026-10-26.

Consumers:

- Android: `drawable-nodpi/planner_angel_demon.png`, rendered inside the adaptive foreground's safe area over navy. Android themed icons use a matching single-colour angel/demon/torn-book silhouette.
- PWA: 180, 192 and 512px regular PNG icons, plus a separate 512px maskable icon with safe margins. Manifest, touch icon and favicon use the `angel-demon-1` revision; the service worker caches every icon variant.

The approved drawing is preserved as the source. Icon packaging only scales it and adds the solid navy maskable margin.

Android package: 1.0.22 (version code 24), including the previously prepared cached-day and immediate-task-update changes. Publication requires approval under `.agents/AGENTS.md`.
