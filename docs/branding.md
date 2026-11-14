# Fin branding audit

The November 14, 2026 audit visually checked the browser favicon, Apple touch icon,
192px/512px app icons, maskable icon, header mark and sharing lockup. They already
contained the supplied sharkfin. The six deployed icon/mark files were byte-for-byte
identical to the local files. No wave artwork was found among the active logo assets.
Old design explorations under `design/logo-options/` are not served by the app.

The live homepage still declared the old, unversioned 32px favicon path, while
`/favicon.ico` returned 404. The homepage's social image was a coral photograph;
site, center and Dive Brief previews did not declare a social image. External
services could retain the former wave in cached icon or preview metadata.

## Current outputs

- `/brand/fin-icon-512.png`: stable, high-resolution favicon, serving the existing fin artwork.
- `/favicon.ico`: real multi-resolution ICO generated from the supplied fin icon.
- `/brand/fin-touch-icon.png`: fresh Apple touch-icon URL.
- `/brand/fin-icon-192.png`, `/brand/fin-icon-512.png` and
  `/brand/fin-icon-maskable-512.png`: manifest icons with fresh fin-specific URLs.
- `/brand/fin-mark.png`: existing header/welcome artwork under a fresh URL.
- `/brand/pelagia-fin-preview.png`: 1200 × 630 social image composed from the supplied
  white fin and wordmark. The homepage, site/center previews, directory, brief and
  other base-template pages declare it in Open Graph and Twitter image metadata.
- Individual shared dives retain their generated dive image and supplied fin
  lockup, with `brand=fin-v1` added to the metadata image URL to refresh image caches.

The PWA release digest includes the branding code and lockup artwork; the new icon
URLs are precached for offline use. Browser icons revalidate rather than receiving
a long immutable cache lifetime. Existing static URLs continue to serve the fin
artwork for backward compatibility.

## After deployment

Check the homepage source and the new image URLs. Request a homepage recrawl in
Google Search Console to refresh its favicon reference. Google and messaging apps
control their own cache refresh schedules, so already cached results or previously
sent messages may retain the former image until those services refresh them.
Installed home-screen icons may also refresh on the device's own schedule.

Google favicon guidance: https://developers.google.com/search/docs/appearance/favicon-in-search
