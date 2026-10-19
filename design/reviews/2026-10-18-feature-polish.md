# Recent feature layout review

October 18, 2026

Reviewed the profile, settings, account units, sharing carousel, sign-in, verification, and new/edit dive layouts using disposable sample data.

## Changes

- Replaced the settings text × with a centered SVG. Its old 36px text line did not fit the button's content area. Close controls now use a 44px square target with an 18px SVG, shared by settings, sharing, and installation instructions.
- Matched the settings Save button to the close button's 44px height and kept the header on one row.
- Used a centered SVG for the profile certification removal control.
- Fixed the email sign-in form's intrinsic grid sizing and reduced the button's excessive icon gap. On a 320px screen, its input and button now fit inside the card.
- Allowed long email addresses in verification instructions to wrap. The test address previously expanded a 320px page to 403px.

## Verification

- Eight screens at 320px, 768px, and 1440px: login, signup, email verification, profile, new dive, dive detail, edit dive, and feed. All 24 checks fit the viewport without document-level horizontal overflow.
- Settings and sharing dialogs at 320×740, 768×1024, 1440×1000, and 844×390. All eight checks stayed within the viewport and had no horizontal overflow; short settings dialogs retain vertical scrolling.
- Settings close icon has zero horizontal and vertical offset from its button center on mobile and desktop. Save and close both measure 44px high.
- Visually inspected profile identity/history, metric and imperial unit controls, both sharing image styles, portrait/landscape sharing controls, and sign-in/code entry.
- All 49 JavaScript tests passed. Python: 109 of 110 passed. The failure is `test_concurrent_onboarding_uses_one_identity_and_does_not_expose_email`, which expects the owner's email to be absent even though settings displays it. The same test fails in an isolated copy of unchanged HEAD.
- Screenshots are saved under `output/design-polish/`. Browser viewport testing does not include physical-device Safari or native installation/share sheets.
