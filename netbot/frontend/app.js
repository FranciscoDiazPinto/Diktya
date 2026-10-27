import { createDashboard } from './modules/dashboard.mjs';

const dashboard = createDashboard({document, window, localStorage, fetch: (...args) => fetch(...args), Option, crypto, FormData});
dashboard.start();
