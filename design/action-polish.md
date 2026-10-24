# Pelagia action polish

October 23, 2026

This pass keeps Pelagia's ocean palette, page structure, and existing sharing flows. It gives likes, comments, sharing, and dive logging consistent icons and clearer spacing.

- Shared SVG icons replace the oversized CSS hearts and align share and plus icons across the feed, profiles, site and center headers, Dive Brief, and sharing dialog.
- Social actions have 44px touch targets, consistent rounded surfaces, and an outlined heart that fills when liked. Likes expose their selected state and counts to assistive technology.
- Dive cards group likes and comments on the left and place the owner's Share action on the right. Dive sites keep Like and Share together, with Log dive aligned to the right and the site's existing location prefill preserved.
- Comment actions open the dive at its composer and focus the input. The detail page's comment count is actionable. Comment inputs and Post controls align across dives, sites, and centers, with required fields and accessible button names.
- Profile logging buttons use the same 44px height as site logging. Existing keyboard focus indicators and modified-link behavior remain available.

## Verification

All 179 Python tests and 96 JavaScript tests passed. Browser checks used a disposable fixture database and headless Chrome at 320, 390, 768, and 1440px. They covered the feed, own and other divers' details, diver profiles, populated and empty sites, centers, logging, share dialogs, and anonymous previews, with no document-level horizontal overflow or undersized social actions.

Interaction checks covered liking and unliking, comment counts and posting, direct navigation to the composer, site-prefilled logging, clipboard copying, focus restoration after sharing, and anonymous account gates. Additional touch and reduced-motion checks covered keyboard focus, native-share payloads with a simulated share sheet, manual copy fallback, full and transparent image previews, and recovery from failed likes and comments while retaining typed comments.

Native OS share sheets and physical iOS/Android devices were not exercised. Review captures are available locally in `output/action-polish-review/`; generated screenshots are not part of the source change.

## Logged-dive layout follow-up

The detail page inherited a feed-style top border while removing the action row's padding. That placed the separator against the tops of two compact controls and made the discussion feel cramped.

The detail discussion now has 48px Like and Comment controls with visible labels, 12px between controls, and a separator below the row with 16px of breathing room. Phones use two equally sized columns; larger screens use compact controls aligned to the left. Labels and counts wrap together when space is limited, and both controls retain equal heights. The discussion and composer have consistent 16px spacing.

Responsive browser verification covered ten signed-in routes at twelve viewport sizes, from 320px phones through 1440px desktops, including both sides of the 640px breakpoint and an 844 × 390 landscape viewport. Assertions checked content clipping, parent containment, action spacing, equal mobile widths, touch targets, and composer visibility after comment navigation. Additional checks covered five-digit counts, 125% text sizing, accessible labels, liking, and posting comments. Share dialogs, newsletter controls, and all public previews were checked separately at 320, 390, 768, and 1440px against the clean main snapshot.

All 179 Python tests and 96 JavaScript tests passed against a clean main snapshot with this layout change, isolating it from unrelated backend edits in the shared workspace. Review captures are in `output/action-layout-followup/` and are not committed.
