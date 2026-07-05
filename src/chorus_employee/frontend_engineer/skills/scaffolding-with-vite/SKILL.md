---
name: scaffolding-with-vite
description: How to scaffold a framework app with Vite and keep it verifiable — creating the project non-interactively, wiring CI-safe test/build/preview scripts, and pointing Playwright's webServer at the preview build.
when_to_use: Read when you chose a framework (React, Vue, Svelte, Solid, …) and need a build tool. It sets the project up so `npm test` and `npx playwright test` both run green; for framework-specific footguns see the matching doctor skill.
---

# Scaffolding with Vite

Vite is the common, framework-agnostic build tool: it scaffolds React, Vue, Svelte, Solid, Lit, and
vanilla+TS projects from one command, gives you a dev server and a production build, and stays out of
the way. The job here is to scaffold **non-interactively** and wire the scripts the verifier re-runs.

## The one rule

**Scaffold the framework with Vite, then wire CI-safe `test` + `build` + `preview` scripts and point
Playwright's `webServer` at the preview — so a non-interactive re-run reaches green on its own.**

## Scaffold non-interactively

```bash
# pick the template for your chosen framework: react, react-ts, vue, vue-ts, svelte, svelte-ts, solid, …
npm create vite@latest app -- --template react-ts
cd app && npm install
```

- Always pass the `--template` flag: the bare command is interactive and will HANG a non-interactive
  beat. The `--` forwards the flag through `npm create`.
- This is a real project with a `package.json`, a build, and a dev server — exactly what the DoD floor
  expects.

## Meta-frameworks

- If the intent needs server-side rendering, routing, or SEO, a meta-framework (e.g. Next.js, Nuxt,
  SvelteKit) may fit better than a bare SPA — see `choosing-a-frontend-stack`. Those bring their own
  create-command and dev/build/preview scripts; the same CI-safe + Playwright wiring below applies.

## Wire CI-safe scripts

- Add a unit runner (`component-testing` covers Vitest + Testing Library) and wire it run-once:

  ```json
  {
    "scripts": {
      "dev": "vite",
      "build": "vite build",
      "preview": "vite preview",
      "test": "vitest run"
    }
  }
  ```

- `vitest run` (not bare `vitest`) exits instead of watching — a watch mode hangs the re-run. Setting
  `CI=1` also forces run-once for tools that honor it.
- `npm test` must map to your unit run so the captured `unit.txt` and the re-run line up.

## Point Playwright at the build

- Build then preview, and let Playwright start it (see `playwright-e2e-authoring`):

  ```js
  webServer: {
    command: 'npm run build && npm run preview -- --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: true,
  }
  ```

- Testing the preview (production) build catches build-time breakage the dev server would hide.

## Before you finish

1. Did you scaffold non-interactively (`--template …`), so nothing waited on a prompt?
2. Is `npm test` wired to a run-once unit runner (no watch mode)?
3. Does Playwright's `webServer` build + serve the app, with ports in sync?
4. Do `npm test` and `npx playwright test` both reach green from a clean `npm install`?
