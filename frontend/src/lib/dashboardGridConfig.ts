/**
 * Shared react-grid-layout constants (design §4), ported from the mahalo-dock
 * DashboardGrid proven under the identical Next 16.3.3 / React 19 stack.
 *
 * Kept in a pure (no-DOM) module so both the grid component and the pure layout
 * helpers / their unit tests reference one definition.
 */

export const BREAKPOINTS = { lg: 1200, md: 996, sm: 768, xs: 480, xxs: 0 } as const;

export const COLS = { lg: 12, md: 12, sm: 6, xs: 4, xxs: 2 } as const;

export const ROW_HEIGHT = 80;
export const GRID_MARGIN: [number, number] = [24, 24];
export const CONTAINER_PADDING: [number, number] = [0, 0];

/** Default size for a newly added widget (design §4). */
export const DEFAULT_WIDGET_W = 6;
export const DEFAULT_WIDGET_H = 8;
