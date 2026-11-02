import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// The first test in a file pays for a cold render of the whole page (session -> /api/me -> the
// page's query -> first render of every component). With all files running in parallel jsdom
// workers that alone took 0.4-0.95 s, so Testing Library's default 1 s wait for `findBy*` /
// `waitFor` failed intermittently. 5 s is a wait budget, not a retry: an element that never
// appears still fails the test. Keep it below vite.config.ts `testTimeout`.
configure({ asyncUtilTimeout: 5_000 });

afterEach(() => cleanup());
