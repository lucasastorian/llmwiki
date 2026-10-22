import { withDeadline } from "./deadline";

export const CONTENT_ELIGIBILITY_TIMEOUT_MS = 5_000;
export const CONTENT_BOOTSTRAP_TIMEOUT_MS = 30_000;

export interface ContentStartupState<T> {
  __llmwikiLoaded?: boolean;
  __llmwikiInitPromise?: Promise<void>;
  __llmwikiController?: T;
}

export interface ContentStartupDependencies<T> {
  isEligible(): boolean | Promise<boolean>;
  createController(): T;
  bootstrap(controller: T): Promise<void>;
  dispose(controller: T): void;
  eligibilityTimeoutMs?: number;
  bootstrapTimeoutMs?: number;
}

/** Repeated injections share one startup via state on the isolated world's Window. */
export function ensureContentStarted<T>(
  state: ContentStartupState<T>,
  dependencies: ContentStartupDependencies<T>,
): Promise<void> {
  if (state.__llmwikiLoaded) return Promise.resolve();
  if (state.__llmwikiInitPromise) return state.__llmwikiInitPromise;

  let startup: Promise<void>;
  startup = Promise.resolve()
    .then(async () => {
      const eligible = await withDeadline(
        Promise.resolve().then(() => dependencies.isEligible()),
        dependencies.eligibilityTimeoutMs ?? CONTENT_ELIGIBILITY_TIMEOUT_MS,
        "Content-script eligibility check timed out",
      );
      if (!eligible) return;

      const controller = dependencies.createController();
      try {
        await withDeadline(
          dependencies.bootstrap(controller),
          dependencies.bootstrapTimeoutMs ?? CONTENT_BOOTSTRAP_TIMEOUT_MS,
          "Content-script bootstrap timed out",
        );
      } catch (error) {
        dependencies.dispose(controller);
        throw error;
      }

      state.__llmwikiController = controller;
      state.__llmwikiLoaded = true;
    })
    .finally(() => {
      if (state.__llmwikiInitPromise === startup) {
        state.__llmwikiInitPromise = undefined;
      }
    });

  // Assigned before the queued callback runs, closing the duplicate-controller race.
  state.__llmwikiInitPromise = startup;
  return startup;
}
