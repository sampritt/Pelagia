# Reports page heading and footer

Reports now opens with a visible, compact “Daily reports” heading. Below the report list, smaller text reads “Follow dive sites to get daily reports in your feed.” A native “Explore dive sites” link uses the existing primary button style and opens Explore. The empty state shares this footer so it has only one Explore button.

Reviewed populated and empty pages at 1440, 768, 390, and 320 px. The heading is 15 px, footer copy 13 px, and button target 44 px tall. Confirmed spacing above the cards and below the list, mobile text wrapping, no horizontal overflow, button placement below the copy, successful Explore navigation, and browser Back restoring Reports with the correct active tab. No browser page errors occurred.

Validation: 25 Python tests for site favorites, feed report selection, and PWA assets passed; patch whitespace checks passed. Browser screenshots and measurements are local fixtures in output/reports-heading-footer/.
