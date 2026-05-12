# Shared Packages Architecture

This project uses a **Monorepo** structure powered by **npm workspaces** to share code between microfrontends at build-time. This approach ensures that each microfrontend is independent of the others' runtime state while maintaining a single source of truth for common logic and UI.

## 1. Project Structure

The repository is organized as follows:

```text
/ (root)
├── package.json          # Defines npm workspaces
├── packages/             # Shared local packages
│   ├── core/             # Configuration and business logic
│   └── ui/               # Reusable UI components and styles
├── mfe-shell/            # The host application
├── mfe-dashboard/        # Dashboard microfrontend
└── mfe-details/          # Details/Corrections microfrontend
```

## 2. Shared Packages

### `@data-hygiene/core`
Contains shared constants and logic.
- **`API_URL`**: The base URL for the backend API, centralized so changes apply across all MFEs.
- **Usage**:
  ```javascript
  import { API_URL } from "@data-hygiene/core";
  ```

### `@data-hygiene/ui`
Contains shared UI components and global styles.
- **Components**: `Loader`, `ErrorPage`.
- **Styles**: `styles.css` (global resets, typography, and custom scrollbars).
- **Usage**:
  ```javascript
  import { Loader, ErrorPage } from "@data-hygiene/ui";
  ```

## 3. How It Works (npm Workspaces)

Instead of fetching components at runtime via Module Federation (which makes apps fragile if the source app is down), we use **Build-time Dependencies**:

1.  **Linking**: When you run `npm install` at the root, npm creates symlinks in the `node_modules` of each microfrontend that point to the local `packages/` directory.
2.  **Bundling**: When Vite builds a microfrontend, it bundles the shared code directly into that application's build.
3.  **Independence**: If `mfe-shell` is stopped, `mfe-dashboard` and `mfe-details` will continue to function and render their own `Loader` or `ErrorPage` because the code is already bundled inside them.

## 4. Development Workflow

### Adding a new shared component
1.  Create the component in `packages/ui/src/`.
2.  Export it from `packages/ui/src/index.js`.
3.  Use it in any MFE using `import { MyComponent } from "@data-hygiene/ui"`.

### Updating a shared package
If you modify code inside `packages/`, Vite's HMR (Hot Module Replacement) will automatically detect the changes and refresh the microfrontends that are using that code.

## 5. Summary of Benefits
- **Deduplication**: Write styles and common components once.
- **Reliability**: No runtime dependency on the shell for basic UI elements.
- **Consistency**: Centralized API configuration and styling ensures a unified experience.
