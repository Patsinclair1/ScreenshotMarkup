# Paddy's to-do list (nothing has been submitted or signed up for)

## 1. Decide identity (blocks everything else)
- [ ] **Code host / owner.** Create a GitHub user or org (free) and public repos, e.g. `OWNER/screenshot-markup`
      and `OWNER/edgetune`. Then replace every `OWNER` / `owner` placeholder (app IDs, metainfo URLs,
      the EGO uuid `screenshot-markup@OWNER.github.io`, the extension's `APP_IDS`). Flathub requires the
      app ID to map to a domain or code-host account you control (`io.github.<user>` ↔ github.com/<user>),
      and verifies it. A domain you own also works (e.g. `com.patchworkfix.ScreenshotMarkup`).
- [ ] **Push the code** to those repos (I didn't push anything) and switch the Flatpak `dir` sources to `git` tag + commit.
- [ ] **Licence holder:** confirm MIT and fill in the name in both `LICENSE` files. For Edgetune, **get pajo's
      OK** that it's your code to license (pajo wrote the widget).
- [ ] **Names:** confirm "Screenshot Markup" and "Edgetune" (placeholder) are free on each store.

## 2. Store accounts and fees (checked 2026-10-16)
| Store | Cost | Source |
|---|---|---|
| Flathub | Free (submit a PR to github.com/flathub/flathub; needs a GitHub account) | https://docs.flathub.org/docs/for-app-authors/submission |
| GNOME Extensions (extensions.gnome.org) | Free account; manual review | https://extensions.gnome.org/upload/ |
| Snap Store | Free (Ubuntu One account, register the snap name) | https://snapcraft.io/docs/registering-your-app-name |
| Microsoft Store, Individual | **Free** (the $19 fee was waived in Sept 2025; ID + selfie verification). Company accounts became free too (May 2026) | https://learn.microsoft.com/en-us/windows/apps/publish/whats-new-individual-developer · https://blogs.windows.com/windowsdeveloper/2026/05/07/publish-to-microsoft-store-as-a-company-now-with-free-registration-and-faster-onboarding/ |
| Apple Developer Program | **US$99 per membership year** (local price shown at checkout); legal name shown as seller | https://developer.apple.com/programs/enroll/ |

## 3. Signing
- [ ] **Flathub:** none needed. Flathub builds and signs.
- [ ] **EGO:** none; upload the zip `packaging/ego/screenshot-markup@OWNER.github.io.shell-extension.zip` after renaming the uuid.
- [ ] **MSIX:** Store submissions are re-signed by Microsoft (no cert to buy). Only sideloaded/direct MSIX needs a
      code-signing certificate (paid OV cert, or Azure Trusted Signing ≈ US$10/month). The MSIX `Publisher` must
      match your Partner Center publisher ID.
- [ ] **macOS:** Developer ID Application certificate + notarisation (`xcrun notarytool`) for direct download;
      Mac App Distribution cert + App Store Connect for the store. Both need the $99 membership.

## 4. Spotify trademark rules (Edgetune) — https://developer.spotify.com/documentation/design
- [ ] Don't put "Spotify" (or anything that sounds/looks like it) in the app name, icon, company or website. "for Spotify"/"works with Spotify" in the description is OK.
- [ ] The icon must not look like Spotify's (green, circle, waves). The new icon is cream/cognac/black. **But** the default
      in-app palette `MinimalGreen` uses Spotify green (#1ED760), and there's a Spotify-logo-style button in the panel.
      Consider changing both before submitting. Add the "not affiliated with Spotify AB" line (already in metainfo/listing).
- [ ] Spotify metadata/art shown should link back to Spotify ("Open Spotify" button exists). Album art in screenshots is
      third-party artwork; re-shoot store screenshots without it or with art you have rights to.
- [ ] Spotify's Developer Terms apply only if you use the Web API (macOS port option). The Spicetify/debug-port extras
      are unofficial; keep them off in store builds.

## 5. Before submitting
- [ ] Run `flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest <yml>` and `... repo repo` after OWNER is filled in.
- [ ] Add 1–2 more screenshots per app (Flathub likes several), hosted at the raw GitHub URLs in metainfo.
- [ ] Log out/in test of the EGO extension version together with the Flatpak app.
