# Reports follow prompt and badge polish

The Reports follow prompt and Explore button are centered and render only when no dive sites are followed. The template checks the followed-at metadata retained by followed sites, so a featured report alone still shows the prompt, while following the featured site hides it. The prompt uses muted text, measured spacing, a rounded primary button with the existing blue gradient, and a quieter shadow. With no reports available, the same prompt sits in a rounded panel with the app's compass accent.

Removed DAILY REPORT from the Home/feed preview, including fragments returned by its refresh endpoint. FEATURED remains on featured cards.

Reviewed 24 browser layouts across empty, featured-only, followed-featured, and multiple-followed-site states at 1440, 1024, 768, 430, 390, and 320 px. Verified prompt visibility, exact horizontal centering, no horizontal overflow, 44 px button targets, badge removal, FEATURED preservation, keyboard activation, tap navigation into Explore, and correct active tabs after browser Back. No page errors occurred.

Validation: 26 Python tests for site favorites, feed report selection, and PWA assets passed. Patch whitespace checks passed. Screenshots and measurements are local fixture captures in output/reports-brand-polish/.
