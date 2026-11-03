# User follows

Follow/Following appears beneath the dive count and certification on other users' profiles. A tap immediately saves the relationship; tapping Following unfollows. The 44px button updates in place, disables while saving, and reports failures without changing the previous state. A normal form submission works without JavaScript.

A directed user_follows table persists both follower and following lists, with unique pairs, a self-follow constraint, reverse lookup index, and cascading account deletion. Startup schema initialization installs the table for existing databases. Follow requests require login and CSRF protection and set an explicit desired state so retries cannot toggle the relationship twice.

Home and /feed select only the current diver's logs and followed divers' logs, before applying the feed limit. Existing ordering and soft-delete filtering remain in place. Other profile histories remain viewable.

Reviewed at 1440, 390 and 320px using local fixtures. Browser checks confirmed follow, persisted Following after navigation, appearance in Home, unfollow, and removal from Home. No overflow at 320px. Screenshots: output/user-follow-review/.

Python checks cover feed filtering before limits, soft deletion, one-way relationships, persistence through schema initialization, duplicate requests, self-follow, unknown users, login/CSRF, HTML fallback, and cascading deletion. Related profile, account-deletion, favorites, Brief, units and depth-profile tests pass.
