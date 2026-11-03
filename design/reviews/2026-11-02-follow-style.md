# Diver follow styling

Use the same chip-button/social-action/following styles and favorite star as dive-site follows. Remove the primary-action gradient, shadow, fixed width and success messages. Keep the shared 44px touch target, reduce the gap below profile metadata to 8px, and hide the empty status region. Errors remain visible and retryable.

Certification tags use a neutral surface and quieter weight so metadata does not compete with the interactive follow state. Profiles without a bio omit the empty bio row.

Visually reviewed local fixtures on desktop (1440px) and mobile (390px, plus the long certification at 320px): bio + certification, neither, long bio only, and long certification only. Checked the real dive-site Follow control as a comparison. Confirmed no horizontal overflow at the narrow breakpoint, clean wrapping, and silent follow/unfollow with the star retained. Screenshots: output/follow-style-review/.

Validation: 17 user-follow/profile tests and seven PWA tests passed; JavaScript syntax and patch checks passed.
