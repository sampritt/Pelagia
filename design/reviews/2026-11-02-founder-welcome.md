# Founder welcome card

Home, Feed, and the post-signup welcome route show Sam’s introduction above The Dive Brief when the viewer has never logged a dive and follows no user accounts. Soft-deleted logs still count as having logged a dive. Site follows, incoming followers, and an imported starting dive count do not affect eligibility.

The card greets the viewer by username, presents the requested message in separate paragraphs, and ends with the current `davyjones` account photo, a profile link, and the existing blue Follow control. Profiles and this card share one form macro and the existing CSRF-protected follow script, including its pending, error, retry, and Following states. Eligibility is reevaluated on each page request. The founder’s own feed does not offer self-follow, and an unavailable founder account omits the card. Missing photos use the existing initial-avatar convention.

The layout uses Pelagia’s white cards, navy typography, shared borders and radius, and blue primary action. Desktop keeps the identity and action together; narrow screens wrap the button to a full row when needed. The button has a 44px minimum height, and long usernames wrap without horizontal overflow.

Validation: 52 Python tests passed across founder welcome, user follows, profiles, Dive Brief, and PWA behavior. Chrome review passed at 1440, 1024, 768, 430, 390, and 320px, including loaded circular photos, placement above the Brief, touch targets, a 120-character username, missing-photo fallback, failed follow and retry, persistence, followed-diver feed content, profile unfollow, and ordinary form submission with JavaScript disabled. No browser script errors or horizontal overflow. Desktop and mobile screenshots were visually inspected. Review uses isolated local accounts and a fixture photo; production resolves the founder photo from the account record.

Screenshots and browser results: `output/founder-welcome-review/`.
