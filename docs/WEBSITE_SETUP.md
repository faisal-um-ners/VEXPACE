# VEXPACE website (GitHub Pages)

The website source is in the `docs/` directory of this repository.

**Expected public address:** https://faisal-um-ners.github.io/VEXPACE/

## Enable the website

1. In GitHub open **Settings → Pages** for `faisal-um-ners/VEXPACE`.
2. Under **Build and deployment**, select **Deploy from a branch**.
3. Select **main** and **/docs**, then click **Save**.
4. After GitHub reports that publication has completed, open the public address above.

The site cannot be considered live until GitHub Pages is enabled and published.

## Pages

- `docs/index.html`: responsive homepage and feature gallery
- `docs/manual.html`: interactive documentation viewer
- `docs/examples.html`: searchable model examples
- `docs/site/site.css`: visual design and responsive layout
- `docs/site/main.js`: navigation, documentation, filtering and copy tools

The manual loads the current `main`-branch Markdown documents from
`raw.githubusercontent.com` and renders them using pinned versions of
Marked and DOMPurify from jsDelivr. An active internet connection is therefore
required to display manual content; a GitHub link is provided as fallback.

Website images use existing `docs/images/` files. The documentation and
example model files remain in the main VEXPACE repository. There are no
changes to particle-in-cell algorithms or simulation setup.

## Local preview

From the repository root run

```bash
python -m http.server 8000 --directory docs
```

Then open http://localhost:8000 in your browser.

## Custom domain

A custom website domain is optional. The standard Pages URL does not require a
purchased domain. Do not add `docs/CNAME` until a domain is purchased and DNS
records are configured.
